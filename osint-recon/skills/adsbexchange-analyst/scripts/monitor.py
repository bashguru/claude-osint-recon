#!/usr/bin/env python3
"""
osint-recon : adsbexchange-analyst : monitor.py
===============================================

A SINGLE-SHOT aircraft check for the live API. It is NOT a long-running loop. Each
time a Claude Desktop scheduled task fires, it runs this once: one live API call,
one condition test, one read/update of a small local state file, and it exits. The
state file lets it alert ONLY on the run where the condition first becomes true
(one alert per transition), not on every run.

Data source: the ADS-B Exchange v2 live API (last-known position only, no history).
Key source: the credential store in creds.py (never printed). Scheduling and the
alert delivery are handled by the calling skill / Claude Desktop, not here.

Dependency-free (Python 3.8+, standard library only).

Conditions
----------
  --within-nm N / --within-mi N   aircraft within N nautical / statute miles of a point
  --on-ground                     aircraft is on the ground (optionally "at" the point)
  --departure                     aircraft was on the ground at the point, now airborne
  --above-alt FT / --below-alt FT barometric altitude threshold
  --above-speed KT / --below-speed KT  ground-speed threshold
When several are given, all must hold (except --departure, which is an edge event).

Reference point (for proximity / on-ground-at / departure)
----------------------------------------------------------
  --airport CODE        looks up a small built-in table of common airports, OR
  --ref-lat / --ref-lon explicit coordinates (the skill supplies these for any
                        airport not in the table).

Example
-------
  python3 monitor.py check --registration N76528 --airport KAUS --within-mi 100 \\
      --state ./monitors/N76528_KAUS.json --interval-min 5
"""

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import creds  # noqa: E402  (sibling module; never prints the key)

GATEWAY_BASE = "https://gateway.adsbexchange.com/api/aircraft/v2"
RAPIDAPI_BASE = "https://adsbexchange-com1.p.rapidapi.com/v2"
RAPIDAPI_HOST = "adsbexchange-com1.p.rapidapi.com"
USER_AGENT = "osint-recon-adsbexchange-analyst/1.0"
NM_PER_MILE = 0.868976
EARTH_NM = 3440.065  # mean Earth radius in nautical miles
MONTHLY_BUDGET = 10000  # base live plan, approximate

# Small convenience table (lat, lon). The skill supplies --ref-lat/--ref-lon for
# anything not listed here, so this stays tiny and stdlib-only.
AIRPORTS = {
    "KAUS": (30.1945, -97.6699), "KATL": (33.6367, -84.4281),
    "KLAX": (33.9416, -118.4085), "KJFK": (40.6413, -73.7781),
    "KORD": (41.9742, -87.9073), "KDFW": (32.8998, -97.0403),
    "KDEN": (39.8561, -104.6737), "KSFO": (37.6213, -122.3790),
    "KLAS": (36.0840, -115.1537), "KSEA": (47.4502, -122.3088),
    "KMIA": (25.7959, -80.2871), "KBOS": (42.3656, -71.0096),
    "KIAD": (38.9531, -77.4565), "KTEB": (40.8501, -74.0608),
    "KHOU": (29.6454, -95.2789), "EGLL": (51.4700, -0.4543),
}


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def haversine_nm(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return EARTH_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_ref(args):
    if args.ref_lat is not None and args.ref_lon is not None:
        return float(args.ref_lat), float(args.ref_lon)
    if args.airport:
        code = args.airport.strip().upper()
        if code in AIRPORTS:
            return AIRPORTS[code]
        raise SystemExit(json.dumps({
            "error": "unknown_airport",
            "message": ("Airport %s is not in the built-in table. Pass --ref-lat "
                        "and --ref-lon with its coordinates." % code)}))
    return None, None


def build_request(args, key, source):
    sel = ("registration", args.registration) if args.registration else \
          ("callsign", args.callsign) if args.callsign else \
          ("icao", (args.hex or "").lower())
    name, value = sel
    if not value:
        raise SystemExit(json.dumps({
            "error": "no_target",
            "message": "Give one of --hex, --registration, or --callsign."}))
    if args.endpoint == "rapidapi":
        url = "%s/%s/%s/" % (RAPIDAPI_BASE, name, value)
        headers = {"x-rapidapi-key": key, "x-rapidapi-host": RAPIDAPI_HOST,
                   "Accept": "application/json", "User-Agent": USER_AGENT}
    else:
        # Force a collection response for a single ICAO with a trailing comma.
        v = value + "," if name == "icao" else value
        url = "%s/%s/%s" % (GATEWAY_BASE, name, v)
        headers = {"api-auth": key, "Accept": "application/json",
                   "User-Agent": USER_AGENT}
    return url, headers, name, value


def fetch(url, headers, timeout, key):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        code = e.code
        hint = {401: "invalid or missing API key", 403: "forbidden (key or plan)",
                429: "rate-limited (slow the cadence)"}.get(code, "HTTP error")
        raise SystemExit(json.dumps({
            "error": "http_%d" % code, "message": "%s. Try --endpoint %s." % (
                hint, "gateway" if "rapidapi" in url else "rapidapi"),
            "detail": creds._redact(str(e.reason), key)}))
    except urllib.error.URLError as e:
        raise SystemExit(json.dumps({
            "error": "network", "message": "Could not reach the API.",
            "detail": creds._redact(str(e.reason), key)}))
    except json.JSONDecodeError:
        raise SystemExit(json.dumps({
            "error": "bad_response", "message": "API did not return JSON."}))


def pick_aircraft(data, name, value):
    ac = data.get("ac") or data.get("aircraft") or []
    if not ac:
        return None
    if name == "registration":
        for a in ac:
            if str(a.get("r", "")).upper() == value.upper():
                return a
    if name == "callsign":
        for a in ac:
            if str(a.get("flight", "")).strip().upper() == value.upper():
                return a
    # icao/hex or fallback: first entry with a usable position
    for a in ac:
        if a.get("lat") is not None and a.get("lon") is not None:
            return a
    return ac[0]


def load_state(path):
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_state(path, state):
    if not path:
        return
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def evaluate(args, ac, ref_lat, ref_lon, prev_state):
    """Return (condition_met, facts, on_ground_at_ref)."""
    facts = {}
    if ac is None:
        facts["status"] = "not_broadcasting"
        return False, facts, False

    lat, lon = ac.get("lat"), ac.get("lon")
    alt = ac.get("alt_baro")
    on_ground_flag = (alt == "ground")
    alt_ft = 0 if on_ground_flag else (alt if isinstance(alt, (int, float)) else None)
    gs = ac.get("gs")
    facts.update({
        "status": "live", "registration": ac.get("r"), "hex": ac.get("hex"),
        "callsign": (ac.get("flight") or "").strip(), "type": ac.get("t"),
        "lat": lat, "lon": lon, "alt_baro": alt, "ground_speed_kt": gs,
        "on_ground": on_ground_flag, "seen_s": ac.get("seen"),
        "db_flags": ac.get("dbFlags"),
    })

    dist_nm = None
    if ref_lat is not None and lat is not None and lon is not None:
        dist_nm = haversine_nm(lat, lon, ref_lat, ref_lon)
        facts["distance_nm"] = round(dist_nm, 1)
        facts["distance_mi"] = round(dist_nm / NM_PER_MILE, 1)

    within = args.within_nm
    if args.within_mi is not None:
        within = args.within_mi * NM_PER_MILE
    near_ref = (dist_nm is not None and within is not None and dist_nm <= within)
    on_ground_at_ref = bool(on_ground_flag and (near_ref if within is not None else True))

    checks = []
    if within is not None and not args.departure:
        checks.append(near_ref)
    if args.on_ground:
        checks.append(on_ground_at_ref if within is not None else on_ground_flag)
    if args.above_alt is not None:
        checks.append(alt_ft is not None and alt_ft >= args.above_alt)
    if args.below_alt is not None:
        checks.append(alt_ft is not None and alt_ft <= args.below_alt)
    if args.above_speed is not None:
        checks.append(gs is not None and gs >= args.above_speed)
    if args.below_speed is not None:
        checks.append(gs is not None and gs <= args.below_speed)

    if args.departure:
        was_on_ground = bool(prev_state.get("on_ground_at_ref", False))
        airborne_now = (not on_ground_flag) and lat is not None
        met = was_on_ground and airborne_now
    else:
        met = all(checks) if checks else False

    return met, facts, on_ground_at_ref


def describe(args):
    if args.departure:
        return "departure from %s" % (args.airport or "the reference point")
    parts = []
    if args.within_mi is not None:
        parts.append("within %g miles of %s" % (args.within_mi, args.airport or "point"))
    elif args.within_nm is not None:
        parts.append("within %g nm of %s" % (args.within_nm, args.airport or "point"))
    if args.on_ground:
        parts.append("on the ground%s" % (" at %s" % args.airport if args.airport else ""))
    if args.above_alt is not None:
        parts.append("at or above %d ft" % args.above_alt)
    if args.below_alt is not None:
        parts.append("at or below %d ft" % args.below_alt)
    if args.above_speed is not None:
        parts.append("at or above %d kt" % args.above_speed)
    if args.below_speed is not None:
        parts.append("at or below %d kt" % args.below_speed)
    return " and ".join(parts) if parts else "(no condition set)"


def budget_warning(interval_min):
    if not interval_min or interval_min <= 0:
        return None
    per_month = int(round(43200.0 / interval_min))  # ~minutes in a month
    if per_month > MONTHLY_BUDGET:
        return ("A check every %g min is about %d requests/month, over the ~%d "
                "base plan limit. Consider a longer interval."
                % (interval_min, per_month, MONTHLY_BUDGET))
    if per_month > MONTHLY_BUDGET * 0.8:
        return ("A check every %g min is about %d requests/month, near the ~%d "
                "base plan limit." % (interval_min, per_month, MONTHLY_BUDGET))
    return None


def cmd_check(args):
    target = args.registration or args.callsign or args.hex
    key, source = creds.resolve_key(explicit=args.key, key_command=args.key_command,
                                    file=args.file)
    if not key:
        print(json.dumps({
            "error": "no_key", "target": target,
            "message": ("No ADS-B Exchange API key is stored. The live API is about "
                        "10 USD/month via RapidAPI (no free tier). Store one with "
                        "creds.py, or have the skill walk you through getting a key. "
                        "A one-time globe-UI spot check is possible meanwhile.")}))
        sys.exit(3)

    ref_lat, ref_lon = resolve_ref(args)
    url, headers, name, value = build_request(args, key, source)
    data = fetch(url, headers, args.timeout, key)
    ac = pick_aircraft(data, name, value)

    prev = load_state(args.state)
    met, facts, on_ground_at_ref = evaluate(args, ac, ref_lat, ref_lon, prev)

    was_in = bool(prev.get("in_condition", False))
    transition = met and not was_in

    state = {
        "schema": 1, "target": target, "selector": name,
        "condition": describe(args),
        "in_condition": met, "on_ground_at_ref": on_ground_at_ref,
        "last_checked_utc": now_utc(),
        "last_distance_nm": facts.get("distance_nm"),
        "last_status": facts.get("status"),
        "last_alert_utc": now_utc() if transition else prev.get("last_alert_utc"),
    }
    save_state(args.state, state)

    if facts.get("status") == "not_broadcasting":
        msg = "%s is not currently broadcasting a position; nothing to report." % target
    elif transition:
        msg = "ALERT: %s is now %s." % (target, describe(args))
        if facts.get("distance_mi") is not None:
            msg += " Distance %.0f mi (%.0f nm)." % (facts["distance_mi"], facts["distance_nm"])
    elif met:
        msg = "%s still meets the condition (%s); already alerted, staying quiet." % (
            target, describe(args))
    else:
        msg = "%s does not meet the condition (%s) right now." % (target, describe(args))

    out = {
        "target": target, "condition": describe(args),
        "condition_met": met, "alert": transition,
        "checked_utc": state["last_checked_utc"], "key_source": source,
        "message": msg,
    }
    out.update(facts)
    bw = budget_warning(args.interval_min)
    if bw:
        out["budget_warning"] = bw
    print(json.dumps(out))


def build_parser():
    p = argparse.ArgumentParser(
        prog="monitor.py",
        description="Single-shot ADS-B Exchange live check for a scheduled monitor.")
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="Run one live check and update the state file.")
    tgt = c.add_argument_group("target (choose one)")
    tgt.add_argument("--hex", help="ICAO hex, e.g. A4400F.")
    tgt.add_argument("--registration", help="Tail number, e.g. N76528.")
    tgt.add_argument("--callsign", help="Callsign, e.g. UAL2177.")
    ref = c.add_argument_group("reference point")
    ref.add_argument("--airport", help="Airport code (built-in table) for proximity.")
    ref.add_argument("--ref-lat", help="Reference latitude (for any airport).")
    ref.add_argument("--ref-lon", help="Reference longitude (for any airport).")
    cond = c.add_argument_group("conditions")
    cond.add_argument("--within-nm", type=float, help="Within N nautical miles of the point.")
    cond.add_argument("--within-mi", type=float, help="Within N statute miles of the point.")
    cond.add_argument("--on-ground", action="store_true", help="Aircraft is on the ground.")
    cond.add_argument("--departure", action="store_true",
                      help="Was on the ground at the point, now airborne.")
    cond.add_argument("--above-alt", type=float, help="At or above this barometric altitude (ft).")
    cond.add_argument("--below-alt", type=float, help="At or below this barometric altitude (ft).")
    cond.add_argument("--above-speed", type=float, help="At or above this ground speed (kt).")
    cond.add_argument("--below-speed", type=float, help="At or below this ground speed (kt).")
    c.add_argument("--state", help="Path to the state file (alert-once tracking).")
    c.add_argument("--interval-min", type=float, help="Cadence in minutes (budget warning only).")
    c.add_argument("--endpoint", choices=["gateway", "rapidapi"], default="gateway",
                   help="API endpoint. Default gateway (api-auth). Use rapidapi for "
                        "an API Lite / RapidAPI key.")
    c.add_argument("--timeout", type=float, default=20.0)
    c.add_argument("--key", help="Explicit key (discouraged).")
    c.add_argument("--key-command", help="Shell command whose stdout is the key.")
    c.add_argument("--file", help="Path to the local key config.")
    c.set_defaults(func=cmd_check)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
