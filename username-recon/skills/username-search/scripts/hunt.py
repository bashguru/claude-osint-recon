#!/usr/bin/env python3
"""
username-recon : hunt.py
========================

A dependency-free re-implementation of the Sherlock "username enumeration"
tradecraft. It checks whether a username exists across many public websites by
requesting each site's profile URL and interpreting the response.

This script intentionally uses ONLY the Python standard library so it runs
anywhere Python 3.8+ is installed -- no `pip install` required.

Subcommands
-----------
  search   Check one or more usernames across the site list.
  verify   Self-heal: probe a site with a known-good and a known-bad username
           to confirm its detection rule still works (see site-healing skill).
  update   Refresh the site manifest (data.json) from the upstream community list.
  list     Show how many sites are loaded (optionally filtered).

Detection methods (mirrors the Sherlock manifest schema)
--------------------------------------------------------
  status_code   Account exists if the HTTP status is 2xx (HEAD request is enough).
  message       Account exists if a known "not found" string is ABSENT from the body.
  response_url  Redirects are disabled; account exists if the status is 2xx.

Run `python hunt.py --help` or `python hunt.py search --help` for usage.

Authorized use only. This tool queries publicly accessible pages. Use it for
your own footprint, consented investigations, security research, or other lawful
purposes. Respect each site's Terms of Service and rate limits.
"""

import argparse
import concurrent.futures
import csv
import gzip
import io
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from time import monotonic

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0"
)

# Upstream community-maintained site list (Sherlock project, MIT licensed).
UPSTREAM_MANIFEST_URL = (
    "https://raw.githubusercontent.com/sherlock-project/sherlock/"
    "master/sherlock_project/resources/data.json"
)

# Web Application Firewall fingerprints. When one of these appears in a response
# the result is ambiguous (we were blocked, not told whether the account exists),
# so we report WAF instead of a misleading "found"/"not found".
WAF_FINGERPRINTS = [
    r".loading-spinner{visibility:hidden}body.no-js .challenge-running{display:none}",  # Cloudflare
    r'<span id="challenge-error-text">',          # Cloudflare error page
    r"AwsWafIntegration.forceRefreshToken",        # AWS WAF / CloudFront
    r'{return l.onPageView}}),Object.defineProperty(r,"perimeterxIdentifiers",{enumerable:',  # PerimeterX
]

# Result status values.
FOUND = "found"          # account exists (Sherlock: CLAIMED)
NOT_FOUND = "not_found"  # account does not exist (Sherlock: AVAILABLE)
ILLEGAL = "illegal"      # username not valid for this site (failed regexCheck)
WAF = "waf"              # blocked by a WAF; result unknown
ERROR = "error"          # network/other error
UNKNOWN = "unknown"      # could not determine

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.normpath(os.path.join(HERE, "..", "data", "data.json"))


# --------------------------------------------------------------------------- #
# Manifest loading
# --------------------------------------------------------------------------- #

def load_manifest(path=None):
    """Load the site manifest.

    Resolution order:
      1. Explicit --manifest path argument.
      2. USERNAME_RECON_MANIFEST environment variable.
      3. Bundled data/data.json next to this script.
    """
    path = path or os.environ.get("USERNAME_RECON_MANIFEST") or DEFAULT_MANIFEST
    if not os.path.exists(path):
        raise SystemExit(
            f"[!] Site manifest not found at: {path}\n"
            f"    Run `python hunt.py update` to download it, or pass --manifest."
        )
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Drop the JSON-schema pointer key if present.
    data.pop("$schema", None)
    return data, path


def filter_sites(site_data, only=None, include_nsfw=False):
    """Return a pruned copy of the manifest.

    only          -- iterable of site names to keep (case-insensitive). None = all.
    include_nsfw  -- if False, drop sites flagged "isNSFW".
    """
    out = {}
    only_lower = {s.lower() for s in only} if only else None
    for name, info in site_data.items():
        if only_lower is not None and name.lower() not in only_lower:
            continue
        if not include_nsfw and info.get("isNSFW"):
            continue
        out[name] = info
    return out


# --------------------------------------------------------------------------- #
# HTTP layer (standard library only)
# --------------------------------------------------------------------------- #

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Disable redirect following so we can inspect 3xx responses directly.

    Returning None from redirect_request causes urllib to raise an HTTPError
    carrying the 3xx status, which we catch and read below.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _decode_body(raw_bytes, http_headers):
    """Decode a (possibly compressed) response body to text, best-effort."""
    if not raw_bytes:
        return ""
    encoding = (http_headers.get("Content-Encoding") or "").lower()
    try:
        if "gzip" in encoding:
            raw_bytes = gzip.GzipFile(fileobj=io.BytesIO(raw_bytes)).read()
        elif "deflate" in encoding:
            try:
                raw_bytes = zlib.decompress(raw_bytes)
            except zlib.error:
                raw_bytes = zlib.decompress(raw_bytes, -zlib.MAX_WBITS)
    except Exception:
        pass  # fall through with whatever we have
    return raw_bytes.decode("utf-8", errors="replace")


def http_request(url, method="GET", headers=None, timeout=30,
                 allow_redirects=True, payload=None, proxy=None, verify=True):
    """Perform an HTTP request with the standard library.

    Returns a dict: {status, final_url, body, elapsed, error}.
    `status` is None when a transport error occurred (see `error`).
    """
    headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    handlers = []
    if not allow_redirects:
        handlers.append(_NoRedirect)
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    start = monotonic()
    try:
        resp = opener.open(req, timeout=timeout)
        raw = resp.read()
        return {
            "status": getattr(resp, "status", resp.getcode()),
            "final_url": resp.geturl(),
            "body": _decode_body(raw, resp.headers),
            "elapsed": round(monotonic() - start, 3),
            "error": None,
        }
    except urllib.error.HTTPError as e:
        # 3xx (redirects disabled) and 4xx/5xx land here. Still useful: we have
        # a real status code and often a body.
        try:
            raw = e.read()
        except Exception:
            raw = b""
        return {
            "status": e.code,
            "final_url": getattr(e, "url", url),
            "body": _decode_body(raw, getattr(e, "headers", {}) or {}),
            "elapsed": round(monotonic() - start, 3),
            "error": None,
        }
    except Exception as e:  # URLError, timeout, ssl, encoding, etc.
        return {
            "status": None,
            "final_url": url,
            "body": "",
            "elapsed": round(monotonic() - start, 3),
            "error": f"{type(e).__name__}: {e}",
        }


# --------------------------------------------------------------------------- #
# Core tradecraft: build a request for a site and interpret the response
# --------------------------------------------------------------------------- #

def interpolate(obj, username):
    """Replace every {} placeholder in a str / dict / list with the username."""
    if isinstance(obj, str):
        return obj.replace("{}", username)
    if isinstance(obj, dict):
        return {k: interpolate(v, username) for k, v in obj.items()}
    if isinstance(obj, list):
        return [interpolate(v, username) for v in obj]
    return obj


def username_allowed(site_info, username):
    """Honor a site's regexCheck: returns False if the username can't exist there."""
    rx = site_info.get("regexCheck")
    if rx and re.search(rx, username) is None:
        return False
    return True


def classify(site_info, resp):
    """Apply the site's detection rule(s) to a response dict.

    Mirrors Sherlock's logic for the three error types. A site may list more
    than one error type; they are combined the same way Sherlock combines them.
    """
    body = resp.get("body") or ""
    status = resp.get("status")

    # 1) Were we blocked by a WAF? Then the result is unreliable.
    if any(fp in body for fp in WAF_FINGERPRINTS):
        return WAF

    error_type = site_info["errorType"]
    if isinstance(error_type, str):
        error_type = [error_type]

    result = UNKNOWN

    # --- message: account exists if the "not found" string is ABSENT ---------
    if "message" in error_type:
        errors = site_info.get("errorMsg")
        if isinstance(errors, str):
            errors = [errors]
        errors = errors or []
        error_present = any(msg in body for msg in errors)
        result = NOT_FOUND if error_present else FOUND

    # --- status_code: account exists if status is 2xx ------------------------
    if "status_code" in error_type and result != NOT_FOUND:
        error_codes = site_info.get("errorCode")
        if isinstance(error_codes, int):
            error_codes = [error_codes]
        result = FOUND
        if status is None:
            result = NOT_FOUND
        elif error_codes and status in error_codes:
            result = NOT_FOUND
        elif status >= 300 or status < 200:
            result = NOT_FOUND

    # --- response_url: redirects disabled; exists if 2xx ---------------------
    if "response_url" in error_type and result != NOT_FOUND:
        if status is not None and 200 <= status < 300:
            result = FOUND
        else:
            result = NOT_FOUND

    return result


def check_site(name, site_info, username, timeout=30, proxy=None, verify=True):
    """Check a single site for a username. Returns a result record (dict)."""
    url_user = interpolate(site_info["url"], username.replace(" ", "%20"))
    record = {
        "site": name,
        "url_main": site_info.get("urlMain"),
        "url_user": url_user,
        "status": UNKNOWN,
        "http_status": None,
        "elapsed": None,
        "error": None,
    }

    # Pre-filter: skip sites where the username is structurally impossible.
    if not username_allowed(site_info, username):
        record["status"] = ILLEGAL
        return record

    # What URL do we actually probe? Some sites expose a separate probe endpoint.
    url_probe = site_info.get("urlProbe")
    url_probe = interpolate(url_probe, username) if url_probe else url_user

    # Choose HTTP method.
    method = site_info.get("request_method")
    if method is None:
        # HEAD is enough for status_code detection; others need the body.
        et = site_info["errorType"]
        et = et if isinstance(et, list) else [et]
        method = "HEAD" if et == ["status_code"] else "GET"

    payload = site_info.get("request_payload")
    if payload is not None:
        payload = interpolate(payload, username)

    # response_url detection requires that we DON'T follow redirects.
    et = site_info["errorType"]
    et = et if isinstance(et, list) else [et]
    allow_redirects = "response_url" not in et

    headers = {"User-Agent": DEFAULT_UA}
    if "headers" in site_info:
        headers.update(site_info["headers"])

    resp = http_request(
        url_probe, method=method, headers=headers, timeout=timeout,
        allow_redirects=allow_redirects, payload=payload, proxy=proxy, verify=verify,
    )
    record["http_status"] = resp["status"]
    record["elapsed"] = resp["elapsed"]
    if resp["error"]:
        record["status"] = ERROR
        record["error"] = resp["error"]
        return record

    record["status"] = classify(site_info, resp)
    return record


def run_checks(site_data, username, max_workers=20, timeout=30,
               proxy=None, verify=True, progress=False):
    """Check `username` across all sites in `site_data`, concurrently."""
    results = []
    workers = max(1, min(max_workers, len(site_data) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(check_site, name, info, username, timeout, proxy, verify): name
            for name, info in site_data.items()
        }
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            done += 1
            if progress:
                print(f"\r  checked {done}/{len(futures)} sites...",
                      end="", file=sys.stderr, flush=True)
        if progress:
            print("", file=sys.stderr)
    results.sort(key=lambda r: r["site"].lower())
    return results


# --------------------------------------------------------------------------- #
# Output rendering (adaptive: the skill picks the format per user request)
# --------------------------------------------------------------------------- #

def render_console(username, results, include_all=False, use_color=True):
    found = [r for r in results if r["status"] == FOUND]

    def c(code, text):
        return f"\033[{code}m{text}\033[0m" if use_color else text

    lines = [f"\nResults for '{username}'  ({len(found)} found / {len(results)} checked)"]
    lines.append("-" * 60)
    for r in found:
        lines.append(f"[{c('92','+')}] {r['site']:<22} {r['url_user']}")
    if include_all:
        for r in results:
            if r["status"] == FOUND:
                continue
            tag = {NOT_FOUND: c("90", "-"), WAF: c("93", "waf"),
                   ERROR: c("91", "err"), ILLEGAL: c("90", "n/a")}.get(
                       r["status"], "?")
            extra = f"  ({r['error']})" if r.get("error") else ""
            lines.append(f"[{tag}] {r['site']:<22} {r['status']}{extra}")
    if not found and not include_all:
        lines.append("(no accounts found; use --include-all to see every site)")
    return "\n".join(lines)


def render_json(username, results, include_all=False):
    rows = results if include_all else [r for r in results if r["status"] == FOUND]
    return json.dumps(
        {
            "username": username,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_checked": len(results),
            "total_found": sum(1 for r in results if r["status"] == FOUND),
            "results": rows,
        },
        indent=2,
    )


def render_csv(username, results, include_all=False):
    rows = results if include_all else [r for r in results if r["status"] == FOUND]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["username", "site", "url_main", "url_user", "status",
                "http_status", "elapsed_s", "error"])
    for r in rows:
        w.writerow([username, r["site"], r["url_main"], r["url_user"],
                    r["status"], r["http_status"], r["elapsed"], r.get("error") or ""])
    return buf.getvalue()


def render_markdown(username, results, include_all=False):
    found = [r for r in results if r["status"] == FOUND]
    out = [f"# Username recon report: `{username}`", ""]
    out.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    out.append(f"- Sites checked: {len(results)}")
    out.append(f"- Accounts found: {len(found)}")
    out.append("")
    out.append("## Accounts found")
    out.append("")
    if found:
        out.append("| Site | Profile URL |")
        out.append("| --- | --- |")
        for r in found:
            out.append(f"| {r['site']} | {r['url_user']} |")
    else:
        out.append("_No accounts found._")
    if include_all:
        other = [r for r in results if r["status"] != FOUND]
        out.append("")
        out.append("## Other sites (not found / blocked / error)")
        out.append("")
        out.append("| Site | Status | HTTP | Note |")
        out.append("| --- | --- | --- | --- |")
        for r in other:
            out.append(f"| {r['site']} | {r['status']} | {r['http_status']} "
                       f"| {r.get('error') or ''} |")
    out.append("")
    return "\n".join(out)


RENDERERS = {
    "console": render_console,
    "json": render_json,
    "csv": render_csv,
    "md": render_markdown,
}


# --------------------------------------------------------------------------- #
# Subcommand: search
# --------------------------------------------------------------------------- #

def cmd_search(args):
    site_data, path = load_manifest(args.manifest)
    site_data = filter_sites(
        site_data,
        only=args.site or None,
        include_nsfw=args.nsfw,
    )
    if not site_data:
        raise SystemExit("[!] No sites to check after filtering.")

    print(f"[*] Loaded {len(site_data)} sites from {path}", file=sys.stderr)

    for username in args.username:
        results = run_checks(
            site_data, username,
            max_workers=args.max_workers, timeout=args.timeout,
            proxy=args.proxy, verify=not args.insecure,
            progress=(args.format == "console" and not args.out),
        )
        if args.format == "console":
            text = render_console(username, results, include_all=args.include_all,
                                  use_color=not args.no_color)
        else:
            text = RENDERERS[args.format](username, results,
                                          include_all=args.include_all)

        if args.out:
            out_path = args.out
            if len(args.username) > 1:
                base, ext = os.path.splitext(args.out)
                out_path = f"{base}_{username}{ext}"
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"[*] Wrote {out_path}", file=sys.stderr)
        else:
            print(text)


# --------------------------------------------------------------------------- #
# Subcommand: verify  (self-healing diagnostics)
# --------------------------------------------------------------------------- #

def random_username(length=12):
    import random
    import string
    return "".join(random.choice(string.ascii_lowercase + string.digits)
                   for _ in range(length))


def verify_site(name, site_info, timeout=30, proxy=None, verify=True):
    """Probe a single site twice to confirm its detection rule still works.

    Uses the manifest's own `username_claimed` (a known-existing account) and a
    random username that should NOT exist. A healthy site returns FOUND for the
    known username and NOT_FOUND for the random one.
    """
    known = site_info.get("username_claimed")
    diag = {
        "site": name,
        "errorType": site_info.get("errorType"),
        "known_username": known,
        "known_result": None,
        "known_http": None,
        "random_username": None,
        "random_result": None,
        "random_http": None,
        "verdict": None,
        "note": None,
    }

    if not known:
        diag["verdict"] = "no_oracle"
        diag["note"] = "Manifest has no username_claimed; cannot auto-verify."
        return diag

    # Make sure the random username is legal for the site.
    rnd = random_username()
    for _ in range(5):
        if username_allowed(site_info, rnd):
            break
        rnd = random_username()
    diag["random_username"] = rnd

    r_known = check_site(name, site_info, known, timeout, proxy, verify)
    r_rnd = check_site(name, site_info, rnd, timeout, proxy, verify)
    diag["known_result"] = r_known["status"]
    diag["known_http"] = r_known["http_status"]
    diag["random_result"] = r_rnd["status"]
    diag["random_http"] = r_rnd["http_status"]

    # Interpret the two probes.
    if r_known["status"] == ERROR or r_rnd["status"] == ERROR:
        diag["verdict"] = "error"
        diag["note"] = r_known.get("error") or r_rnd.get("error")
    elif r_known["status"] == WAF or r_rnd["status"] == WAF:
        diag["verdict"] = "waf_blocked"
        diag["note"] = "A WAF intercepted the probe; detection cannot be trusted."
    elif r_known["status"] == FOUND and r_rnd["status"] == NOT_FOUND:
        diag["verdict"] = "healthy"
    elif r_known["status"] == NOT_FOUND and r_rnd["status"] == NOT_FOUND:
        diag["verdict"] = "false_negative"
        diag["note"] = ("Known account read as NOT found. Detection rule is likely "
                        "stale (site changed its 'not found' message, status code, "
                        "or URL).")
    elif r_known["status"] == FOUND and r_rnd["status"] == FOUND:
        diag["verdict"] = "false_positive"
        diag["note"] = ("Random username read as FOUND. Rule is too loose (site now "
                        "returns 200 for everything, or the error string moved).")
    else:
        diag["verdict"] = "inconclusive"
        diag["note"] = f"known={r_known['status']} random={r_rnd['status']}"
    return diag


def cmd_verify(args):
    site_data, path = load_manifest(args.manifest)
    if args.all:
        targets = filter_sites(site_data, include_nsfw=args.nsfw)
    else:
        targets = filter_sites(site_data, only=args.site, include_nsfw=True)
        missing = [s for s in args.site
                   if s.lower() not in {k.lower() for k in site_data}]
        if missing:
            print(f"[!] Not in manifest: {', '.join(missing)}", file=sys.stderr)
    if not targets:
        raise SystemExit("[!] No sites to verify.")

    print(f"[*] Verifying {len(targets)} site(s)...", file=sys.stderr)
    diags = []
    workers = max(1, min(args.max_workers, len(targets)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(verify_site, n, i, args.timeout, args.proxy,
                          not args.insecure): n for n, i in targets.items()}
        for fut in concurrent.futures.as_completed(futs):
            diags.append(fut.result())
    diags.sort(key=lambda d: d["site"].lower())

    if args.format == "json":
        print(json.dumps({"checked": len(diags), "results": diags}, indent=2))
        return

    # Console summary grouped by verdict.
    order = ["false_negative", "false_positive", "waf_blocked", "error",
             "inconclusive", "no_oracle", "healthy"]
    by_verdict = {}
    for d in diags:
        by_verdict.setdefault(d["verdict"], []).append(d)
    print(f"\nVerification summary ({len(diags)} sites)")
    print("-" * 60)
    for v in order:
        group = by_verdict.get(v, [])
        if not group:
            continue
        print(f"\n{v.upper()}  ({len(group)})")
        for d in group:
            line = f"  {d['site']:<22} known={d['known_result']} random={d['random_result']}"
            if d.get("note") and v not in ("healthy",):
                line += f"\n      -> {d['note']}"
            print(line)
    broken = [d for d in diags if d["verdict"] in
              ("false_negative", "false_positive")]
    print("\n" + "-" * 60)
    print(f"{len(broken)} site(s) need repair. See the site-healing skill to fix the manifest entry.")


# --------------------------------------------------------------------------- #
# Subcommand: update
# --------------------------------------------------------------------------- #

def cmd_update(args):
    url = args.url or UPSTREAM_MANIFEST_URL
    dest = args.manifest or DEFAULT_MANIFEST
    print(f"[*] Downloading manifest from {url}", file=sys.stderr)
    resp = http_request(url, method="GET",
                        headers={"User-Agent": DEFAULT_UA}, timeout=args.timeout)
    if resp["error"] or not resp["body"]:
        raise SystemExit(f"[!] Download failed: {resp['error']}")
    try:
        data = json.loads(resp["body"])
    except json.JSONDecodeError as e:
        raise SystemExit(f"[!] Downloaded content is not valid JSON: {e}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    n = len([k for k in data if k != "$schema"])
    print(f"[*] Saved {n} sites to {dest}")


# --------------------------------------------------------------------------- #
# Subcommand: list
# --------------------------------------------------------------------------- #

def cmd_list(args):
    site_data, path = load_manifest(args.manifest)
    sites = filter_sites(site_data, include_nsfw=args.nsfw)
    nsfw = sum(1 for i in site_data.values()
               if isinstance(i, dict) and i.get("isNSFW"))
    print(f"Manifest: {path}")
    print(f"Total sites: {len([k for k in site_data])}  "
          f"(safe: {len(sites)}, nsfw: {nsfw})")
    if args.names:
        for name in sorted(sites, key=str.lower):
            print(f"  {name}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        prog="hunt.py",
        description="Username enumeration across public sites (Sherlock tradecraft, "
                    "dependency-free). Authorized use only.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--manifest", help="Path to a site manifest JSON file.")
        sp.add_argument("--timeout", type=float, default=30,
                        help="Per-request timeout in seconds (default 30).")
        sp.add_argument("--max-workers", type=int, default=20,
                        help="Concurrent requests (default 20).")
        sp.add_argument("--proxy", help="HTTP(S) proxy URL, e.g. http://127.0.0.1:8080")
        sp.add_argument("--insecure", action="store_true",
                        help="Disable TLS certificate verification.")
        sp.add_argument("--nsfw", action="store_true",
                        help="Include sites flagged NSFW (excluded by default).")

    # search
    s = sub.add_parser("search", help="Check usernames across sites.")
    add_common(s)
    s.add_argument("username", nargs="+", help="One or more usernames to check.")
    s.add_argument("--site", action="append", default=[],
                   help="Limit to a named site (repeatable).")
    s.add_argument("--format", choices=list(RENDERERS), default="console",
                   help="Output format (default console). Pick json/csv/md per request.")
    s.add_argument("--out", help="Write output to this file instead of stdout.")
    s.add_argument("--include-all", action="store_true",
                   help="Include not-found/blocked/error sites in output.")
    s.add_argument("--no-color", action="store_true", help="Disable colored console output.")
    s.set_defaults(func=cmd_search)

    # verify
    v = sub.add_parser("verify", help="Self-heal: confirm detection rules still work.")
    add_common(v)
    v.add_argument("--site", action="append", default=[],
                   help="Site name to verify (repeatable).")
    v.add_argument("--all", action="store_true", help="Verify every site (slow).")
    v.add_argument("--format", choices=["console", "json"], default="console")
    v.set_defaults(func=cmd_verify)

    # update
    u = sub.add_parser("update", help="Download the latest community site manifest.")
    u.add_argument("--manifest", help="Where to save (default: bundled data/data.json).")
    u.add_argument("--url", help="Override the upstream manifest URL.")
    u.add_argument("--timeout", type=float, default=60)
    u.set_defaults(func=cmd_update)

    # list
    ls = sub.add_parser("list", help="Show how many sites are loaded.")
    ls.add_argument("--manifest", help="Path to a site manifest JSON file.")
    ls.add_argument("--nsfw", action="store_true", help="Count NSFW sites as included.")
    ls.add_argument("--names", action="store_true", help="Print every site name.")
    ls.set_defaults(func=cmd_list)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "command", None) == "verify" and not args.all and not args.site:
        raise SystemExit("[!] verify needs --site NAME (repeatable) or --all.")
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
