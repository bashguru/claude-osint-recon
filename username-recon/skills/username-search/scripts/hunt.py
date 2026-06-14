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
import http.cookiejar
import io
import itertools
import json
import os
import random
import re
import shutil
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import datetime, timezone
from time import monotonic, sleep

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# A current, real browser User-Agent. Sites increasingly serve bot-detection
# junk (or stale markup) to old or generic clients, so we present a modern one.
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

# Optional rotation pool (enabled with --rotate-ua). A small spread of current
# desktop and mobile agents so repeated runs are not trivially fingerprinted by
# a single UA string. Kept short on purpose; this is triage, not evasion.
UA_POOL = [
    DEFAULT_UA,
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
]

# Browser-like default headers. A real browser never sends User-Agent alone;
# many sites branch on Accept / Accept-Language and serve a different (or
# challenge) page when they are missing. Per-site `headers` still override these.
BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
}

# Statuses that mean "we were probably blocked or throttled", not "no account".
# A status_code site that answers one of these (and does not explicitly list it
# in errorCode) is reported as WAF/unknown rather than a misleading not_found.
AMBIGUOUS_STATUS = {401, 403, 406, 429, 503}

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
# Email-mode manifest (see the `email` subcommand and the email-search skill).
DEFAULT_EMAIL_MANIFEST = os.path.normpath(
    os.path.join(HERE, "..", "data", "email_data.json"))

# Email result statuses (parallel to the username ones; emails are about account
# registration rather than a public profile handle).
REGISTERED = "registered"          # an account is registered with this email
NOT_REGISTERED = "not_registered"  # no account for this email
LOUD_SKIPPED = "loud_skipped"      # site may notify the target; skipped unless --allow-loud


# --------------------------------------------------------------------------- #
# Manifest loading
# --------------------------------------------------------------------------- #

def load_manifest(path=None, default=DEFAULT_MANIFEST,
                  env_var="USERNAME_RECON_MANIFEST"):
    """Load a site manifest.

    Resolution order:
      1. Explicit --manifest path argument.
      2. The given environment variable.
      3. The given bundled default (username manifest unless overridden).

    The email path passes the email default and env var so both modes share one
    loader.
    """
    path = path or os.environ.get(env_var) or default
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


def _is_transient(exc):
    """True for errors worth a quick retry (timeout / reset / refused / DNS blip)."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, (TimeoutError, ConnectionError)):
            return True
        return any(s in str(reason).lower() for s in
                   ("timed out", "timeout", "reset", "refused",
                    "temporarily", "connection aborted"))
    return False


def http_request(url, method="GET", headers=None, timeout=30,
                 allow_redirects=True, payload=None, proxy=None, verify=True,
                 retries=1, cookie_jar=None, form=None):
    """Perform an HTTP request with the standard library.

    Returns a dict: {status, final_url, body, elapsed, error}.
    `status` is None when a transport error occurred (see `error`).
    Transient transport errors are retried up to `retries` times; a real HTTP
    response (any status, including 4xx/5xx) is never retried.

    `payload` sends a JSON body; `form` sends an application/x-www-form-urlencoded
    body. `cookie_jar` (an http.cookiejar.CookieJar) carries cookies across calls,
    which the multi-step email checks need (fetch a page for a token/cookie, then
    POST). These are unused by the username path and leave it unchanged.
    """
    headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")

    handlers = []
    if not allow_redirects:
        handlers.append(_NoRedirect)
    if cookie_jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookie_jar))
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)

    req = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    attempts = max(1, retries + 1)
    for attempt in range(attempts):
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
            # 3xx (redirects disabled) and 4xx/5xx land here. A real HTTP
            # response: we have a status code and often a body. Never retry it.
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
            # Retry only transient transport errors, and only if attempts remain.
            if attempt + 1 < attempts and _is_transient(e):
                continue
            return {
                "status": None,
                "final_url": url,
                "body": "",
                "elapsed": round(monotonic() - start, 3),
                "error": f"{type(e).__name__}: {e}",
            }


# --------------------------------------------------------------------------- #
# Proxy rotation (optional; --proxy-file)
# --------------------------------------------------------------------------- #

class ProxyRotator:
    """Thread-safe round-robin over a list of proxy URLs (from a file).

    A single shared proxy (``--proxy``) is still supported separately; this adds
    rotation across many proxies for attribution management and rate-limit
    avoidance on public pages.
    """

    def __init__(self, proxies):
        self._proxies = list(proxies)
        self._i = 0
        self._lock = threading.Lock()

    def __bool__(self):
        return bool(self._proxies)

    def count(self):
        return len(self._proxies)

    def next(self):
        if not self._proxies:
            return None
        with self._lock:
            proxy = self._proxies[self._i]
            self._i = (self._i + 1) % len(self._proxies)
            return proxy


def load_proxies(path):
    """Read proxies from a file (one per line, '#' comments allowed).

    Explicit schemes are kept; a missing scheme defaults to http://.
    """
    proxies = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "://" not in line:
                line = "http://" + line
            proxies.append(line)
    return proxies


def validate_proxies(proxies, timeout=8, test_url="https://www.google.com",
                     max_workers=20):
    """Return only the proxies that can fetch ``test_url`` (concurrently)."""
    good = []

    def test(p):
        r = http_request(test_url, method="HEAD",
                         headers={"User-Agent": DEFAULT_UA},
                         timeout=timeout, proxy=p, retries=0)
        return p if (r["status"] and 200 <= r["status"] < 400) else None

    workers = max(1, min(max_workers, len(proxies) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(test, proxies):
            if res:
                good.append(res)
    return good


def build_proxy_rotator(args):
    """Build a ProxyRotator from --proxy-file (optionally validated), or None."""
    path = getattr(args, "proxy_file", None)
    if not path:
        return None
    proxies = load_proxies(path)
    if not proxies:
        raise SystemExit(f"[!] No proxies found in {path}")
    if getattr(args, "validate_proxies", False):
        print(f"[*] Validating {len(proxies)} proxies...", file=sys.stderr)
        good = validate_proxies(proxies)
        if not good:
            raise SystemExit("[!] No working proxies after validation.")
        out = os.path.join(os.getcwd(), "validated_proxies.txt")
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("\n".join(good) + "\n")
            print(f"[*] {len(good)}/{len(proxies)} proxies OK; saved to {out}",
                  file=sys.stderr)
        except OSError:
            print(f"[*] {len(good)}/{len(proxies)} proxies OK", file=sys.stderr)
        proxies = good
    rot = ProxyRotator(proxies)
    print(f"[*] Proxy rotation enabled ({rot.count()} proxies, round-robin).",
          file=sys.stderr)
    return rot


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


def _url_matches(a, b):
    """Loose URL equality for response_url detection.

    Ignores scheme, a trailing slash, and host case so that, for example,
    'https://site.com/' and 'http://site.com' compare equal. Comparison is
    exact otherwise (no prefix matching), so a real profile URL is never
    mistaken for the site's 'missing user' URL.
    """
    def norm(u):
        u = (u or "").strip()
        u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
        return u.rstrip("/").lower()
    return norm(a) == norm(b)


def classify(site_info, resp, username=None):
    """Apply the site's detection rule(s) to a response dict.

    Mirrors Sherlock's logic for the three error types, with three additions
    that improve correctness without changing behavior for entries that do not
    use the new optional fields:

      * ``existsMsg`` -- a positive marker (string or list) that must be PRESENT
        for "found". This is stronger than only checking that the "not found"
        ``errorMsg`` is absent, because a site that returns 200 for every URL
        will still only embed the real handle on a real profile. ``{}`` in a
        marker is interpolated with the username.
      * Ambiguous statuses (see ``AMBIGUOUS_STATUS``: 401/403/406/429/503) report
        ``waf`` (unknown), not ``not_found`` -- unless the site explicitly lists
        the code in ``errorCode``. A block is not a real negative.
      * ``errorUrl`` -- for ``response_url`` sites, the post-redirect URL is
        compared against the site's known "missing user" URL.

    A site may list more than one error type; they are combined the same way
    Sherlock combines them. ``username`` is the raw (un-encoded) handle, used to
    interpolate ``existsMsg`` / ``errorUrl``.
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

    # --- message: existence from body markers --------------------------------
    if "message" in error_type:
        errors = site_info.get("errorMsg")
        if isinstance(errors, str):
            errors = [errors]
        errors = errors or []
        error_present = any(msg in body for msg in errors)

        exists_markers = site_info.get("existsMsg")
        if isinstance(exists_markers, str):
            exists_markers = [exists_markers]
        exists_markers = [interpolate(m, username) if username is not None else m
                          for m in (exists_markers or [])]

        if exists_markers:
            exists_present = any(m in body for m in exists_markers)
            if errors:
                # Both markers defined: the positive marker means found, the
                # negative means not-found, and if NEITHER is present the response
                # is unexpected (blocked or the site changed), so report unknown
                # rather than guess. A present errorMsg wins over a present
                # existsMsg (conservative).
                if error_present:
                    result = NOT_FOUND
                elif exists_present:
                    result = FOUND
                else:
                    result = WAF
            else:
                # Positive-only detection: a real profile carries the marker
                # (often the handle itself); absence means not found.
                result = FOUND if exists_present else NOT_FOUND
        else:
            result = NOT_FOUND if error_present else FOUND

    # --- status_code: account exists if status is 2xx ------------------------
    if "status_code" in error_type and result != NOT_FOUND:
        error_codes = site_info.get("errorCode")
        if isinstance(error_codes, int):
            error_codes = [error_codes]
        if status is None:
            result = NOT_FOUND
        elif error_codes and status in error_codes:
            result = NOT_FOUND
        elif status in AMBIGUOUS_STATUS:
            result = WAF
        elif 200 <= status < 300:
            result = FOUND
        else:
            result = NOT_FOUND

    # --- response_url: existence is decided by where we land ----------------
    if "response_url" in error_type and result != NOT_FOUND:
        final = resp.get("final_url") or ""
        exists_url = site_info.get("existsUrl")
        err_url = site_info.get("errorUrl")
        if exists_url is not None and username is not None:
            exists_url = interpolate(exists_url, username)
        if err_url and username is not None:
            err_url = interpolate(err_url, username)
        if exists_url:
            # Inverse case: landing at/redirecting to existsUrl means the account
            # EXISTS (substring match, e.g. a redirect to '/login?email=...').
            result = FOUND if exists_url in final else NOT_FOUND
        elif err_url and final:
            # Redirects were followed: a missing user lands on errorUrl.
            if _url_matches(final, err_url):
                result = NOT_FOUND
            elif status is not None and 200 <= status < 300:
                result = FOUND
            else:
                result = NOT_FOUND
        else:
            # No URL to compare: redirects were disabled, so a 2xx means the
            # profile loaded directly (original behavior).
            if status is not None and 200 <= status < 300:
                result = FOUND
            else:
                result = NOT_FOUND

    return result


def check_site(name, site_info, username, timeout=30, proxy=None, verify=True,
               retries=1, rotate_ua=False, delay=0):
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

    et = site_info["errorType"]
    et = et if isinstance(et, list) else [et]

    # Choose HTTP method. HEAD is enough for pure status_code detection (no body
    # needed); everything else needs the body or the final URL.
    method = site_info.get("request_method")
    if method is None:
        method = "HEAD" if et == ["status_code"] else "GET"

    payload = site_info.get("request_payload")
    if payload is not None:
        payload = interpolate(payload, username)

    # response_url detection: follow redirects only when we have an errorUrl to
    # compare the final URL against; otherwise keep redirects disabled so a 2xx
    # means the profile loaded directly (the original behavior is preserved).
    if "response_url" in et:
        allow_redirects = bool(site_info.get("errorUrl") or site_info.get("existsUrl"))
    else:
        allow_redirects = True

    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = random.choice(UA_POOL) if rotate_ua else DEFAULT_UA
    if "headers" in site_info:
        headers.update(site_info["headers"])

    if delay:
        sleep(delay)

    resp = http_request(
        url_probe, method=method, headers=headers, timeout=timeout,
        allow_redirects=allow_redirects, payload=payload, proxy=proxy,
        verify=verify, retries=retries,
    )
    record["http_status"] = resp["status"]
    record["elapsed"] = resp["elapsed"]
    if resp["error"]:
        record["status"] = ERROR
        record["error"] = resp["error"]
        return record

    record["status"] = classify(site_info, resp, username)
    return record


def run_checks(site_data, username, max_workers=20, timeout=30,
               proxy=None, verify=True, progress=False,
               retries=1, rotate_ua=False, delay=0, proxy_rotator=None):
    """Check `username` across all sites in `site_data`, concurrently."""
    results = []
    workers = max(1, min(max_workers, len(site_data) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(check_site, name, info, username, timeout,
                      (proxy_rotator.next() if proxy_rotator else proxy),
                      verify, retries, rotate_ua, delay): name
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
# Username permutations (opt-in: --permute; off by default)
# --------------------------------------------------------------------------- #
#
# A small pattern language to generate handle variations to check, inspired by
# kaifcodec/user-scanner core/patterns.py. Off unless the analyst asks for it, and
# always capped (--permute-limit) so a pattern cannot blow up into a huge run.
#   [abc]        a character set
#   [a-z] / [0-9] a range
#   [a-z]{1-2}   with a length range (default length 1)
#   \[ \] \\     escaped literals
# Example: "alice[0-9]{0-2}" -> alice, alice0 ... alice99.

def _parse_pattern(pattern):
    blocks, i, n, lit = [], 0, len(pattern), ""
    while i < n:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            lit += pattern[i + 1]
            i += 2
            continue
        if ch == "[":
            if lit:
                blocks.append(lit)
                lit = ""
            i += 1
            chars = []
            while i < n and pattern[i] != "]":
                if pattern[i] == "\\" and i + 1 < n:
                    chars.append(pattern[i + 1])
                    i += 2
                    continue
                if i + 2 < n and pattern[i + 1] == "-" and pattern[i + 2] != "]":
                    for cp in range(ord(pattern[i]), ord(pattern[i + 2]) + 1):
                        chars.append(chr(cp))
                    i += 3
                    continue
                chars.append(pattern[i])
                i += 1
            if i >= n or pattern[i] != "]":
                raise ValueError("unclosed '[' in pattern")
            i += 1
            lo = hi = 1
            if i < n and pattern[i] == "{":
                j = pattern.find("}", i)
                if j < 0:
                    raise ValueError("unclosed '{' in pattern")
                spec = pattern[i + 1:j]
                i = j + 1
                if "-" in spec:
                    a, b = spec.split("-", 1)
                    lo, hi = int(a), int(b)
                else:
                    lo = hi = int(spec)
            blocks.append((sorted(set(chars)), lo, hi))
        elif ch == "]":
            raise ValueError("unescaped ']' in pattern")
        else:
            lit += ch
            i += 1
    if lit:
        blocks.append(lit)
    return blocks


def _block_options(block):
    if isinstance(block, str):
        yield block
        return
    chars, lo, hi = block
    for length in range(lo, hi + 1):
        if length == 0:
            yield ""
            continue
        for combo in itertools.product(chars, repeat=length):
            yield "".join(combo)


def expand_permutations(pattern, limit=500):
    """Expand a pattern into up to `limit` candidate usernames."""
    blocks = _parse_pattern(pattern)
    out = []

    def rec(idx, acc):
        if len(out) >= limit:
            return
        if idx == len(blocks):
            out.append(acc)
            return
        for opt in _block_options(blocks[idx]):
            if len(out) >= limit:
                return
            rec(idx + 1, acc + opt)

    rec(0, "")
    return out


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
    rotator = build_proxy_rotator(args)

    usernames = list(args.username)
    if getattr(args, "permute", None):
        expanded = expand_permutations(args.permute, args.permute_limit)
        print(f"[*] Expanded {len(expanded)} candidate(s) from pattern "
              f"(capped at {args.permute_limit})", file=sys.stderr)
        usernames += expanded
    if not usernames:
        raise SystemExit("[!] Provide at least one username, or a --permute pattern.")

    for username in usernames:
        results = run_checks(
            site_data, username,
            max_workers=args.max_workers, timeout=args.timeout,
            proxy=args.proxy, verify=not args.insecure,
            progress=(args.format == "console" and not args.out),
            retries=args.retries, rotate_ua=args.rotate_ua, delay=args.delay,
            proxy_rotator=rotator,
        )
        if args.format == "console":
            text = render_console(username, results, include_all=args.include_all,
                                  use_color=not args.no_color)
        else:
            text = RENDERERS[args.format](username, results,
                                          include_all=args.include_all)

        if args.out:
            out_path = args.out
            if len(usernames) > 1:
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
    import string
    return "".join(random.choice(string.ascii_lowercase + string.digits)
                   for _ in range(length))


def random_email(length=12):
    import string
    local = "".join(random.choice(string.ascii_lowercase + string.digits)
                    for _ in range(length))
    return f"{local}@example-{random.randint(10000, 99999)}.com"


def verify_site(name, site_info, timeout=30, proxy=None, verify=True, retries=1,
                email_mode=False, allow_loud=True):
    """Probe a single site twice to confirm its detection rule still works.

    Uses the manifest's own `username_claimed` (a known-existing account/email)
    and a random identifier that should NOT exist. A healthy site returns
    found/registered for the known one and not-found/not-registered for the
    random one. Email results are normalized to the shared found/not-found
    vocabulary so the verdict logic is identical for both modes.
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
        diag["note"] = ("Manifest has no username_claimed (a known-existing "
                        "account/email); cannot auto-verify.")
        return diag

    if email_mode:
        rnd = random_email()
        diag["random_username"] = rnd
        r_known = check_email(name, site_info, known, timeout, proxy, verify,
                              retries, allow_loud=allow_loud)
        r_rnd = check_email(name, site_info, rnd, timeout, proxy, verify,
                            retries, allow_loud=allow_loud)
    else:
        # Make sure the random username is legal for the site.
        rnd = random_username()
        for _ in range(5):
            if username_allowed(site_info, rnd):
                break
            rnd = random_username()
        diag["random_username"] = rnd
        r_known = check_site(name, site_info, known, timeout, proxy, verify, retries)
        r_rnd = check_site(name, site_info, rnd, timeout, proxy, verify, retries)

    # Normalize email verdicts into the shared found/not-found vocabulary.
    norm = {REGISTERED: FOUND, NOT_REGISTERED: NOT_FOUND}
    ks = norm.get(r_known["status"], r_known["status"])
    rs = norm.get(r_rnd["status"], r_rnd["status"])
    diag["known_result"] = ks
    diag["known_http"] = r_known["http_status"]
    diag["random_result"] = rs
    diag["random_http"] = r_rnd["http_status"]

    # Interpret the two probes.
    if ks == ERROR or rs == ERROR:
        diag["verdict"] = "error"
        diag["note"] = r_known.get("error") or r_rnd.get("error")
    elif ks == WAF or rs == WAF:
        diag["verdict"] = "waf_blocked"
        diag["note"] = "A WAF intercepted the probe; detection cannot be trusted."
    elif ks == FOUND and rs == NOT_FOUND:
        diag["verdict"] = "healthy"
    elif ks == NOT_FOUND and rs == NOT_FOUND:
        diag["verdict"] = "false_negative"
        diag["note"] = ("Known account read as NOT found. Detection rule is likely "
                        "stale (site changed its 'not found' message, status code, "
                        "or URL).")
    elif ks == FOUND and rs == FOUND:
        diag["verdict"] = "false_positive"
        diag["note"] = ("Random identifier read as FOUND. Rule is too loose (site "
                        "now matches everything, or the marker moved).")
    else:
        diag["verdict"] = "inconclusive"
        diag["note"] = f"known={ks} random={rs}"
    return diag


def cmd_verify(args):
    email_mode = getattr(args, "email", False)
    if email_mode:
        site_data, path = load_manifest(
            args.manifest, default=DEFAULT_EMAIL_MANIFEST,
            env_var="USERNAME_RECON_EMAIL_MANIFEST")
    else:
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

    print(f"[*] Verifying {len(targets)} {'email ' if email_mode else ''}site(s)...",
          file=sys.stderr)
    rotator = build_proxy_rotator(args)
    allow_loud = getattr(args, "allow_loud", True)
    diags = []
    workers = max(1, min(args.max_workers, len(targets)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(verify_site, n, i, args.timeout,
                          (rotator.next() if rotator else args.proxy),
                          not args.insecure, args.retries, email_mode, allow_loud): n
                for n, i in targets.items()}
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
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = DEFAULT_UA
    resp = http_request(url, method="GET", headers=headers,
                        timeout=args.timeout, retries=2)
    if resp["error"] or not resp["body"]:
        raise SystemExit(f"[!] Download failed: {resp['error']}")
    try:
        data = json.loads(resp["body"])
    except json.JSONDecodeError as e:
        raise SystemExit(f"[!] Downloaded content is not valid JSON: {e}")

    # Protect local work. The old behavior overwrote data.json wholesale, which
    # silently destroyed any site added by add-site or rule repaired by
    # site-healing. Now we back up the current manifest first, then carry
    # forward any site that exists locally but not upstream.
    preserved = []
    if os.path.exists(dest) and not args.no_preserve:
        try:
            with open(dest, "r", encoding="utf-8") as fh:
                current = json.load(fh)
        except (OSError, json.JSONDecodeError):
            current = {}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = f"{dest}.bak-{stamp}"
        try:
            with open(backup, "w", encoding="utf-8") as bf:
                json.dump(current, bf, indent=2, ensure_ascii=False)
            print(f"[*] Backed up current manifest to {backup}", file=sys.stderr)
        except OSError as e:
            print(f"[!] Could not write backup ({e}); continuing.", file=sys.stderr)
        for name, info in current.items():
            if name == "$schema":
                continue
            if name not in data:
                data[name] = info
                preserved.append(name)

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    n = len([k for k in data if k != "$schema"])
    print(f"[*] Saved {n} sites to {dest}")
    if preserved:
        print(f"[*] Preserved {len(preserved)} locally added site(s): "
              f"{', '.join(sorted(preserved))}", file=sys.stderr)
        print("    Repairs to sites that also exist upstream were reset to the "
              "upstream version; recover them from the backup if needed.",
              file=sys.stderr)


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
# Email mode: registration checks (reuses the same request + classify layer)
# --------------------------------------------------------------------------- #
#
# Email checks ask a different question ("is an account registered with this
# email?") and the common real-world pattern is multi-step: fetch a signup or
# validation page to pick up a CSRF token / cookie, then POST the email and read
# the response. To keep ONE request strategy and ONE classifier, email mode reuses
# http_request() and classify(); it only adds (a) an optional prefetch that
# captures a token/cookie, (b) form/JSON bodies with {} = email and {token}
# placeholders, (c) optional profile-data harvest, and (d) loud-site gating.
#
# Manifest entry shape (data/email_data.json), all detection fields are the SAME
# as the username schema (errorType / errorMsg / existsMsg / errorCode ...):
#   "GitHub": {
#     "category": "dev",
#     "url": "https://github.com", "urlMain": "https://github.com",
#     "errorType": "message",
#     "existsMsg": ["already associated with an account"],
#     "errorMsg":  ["Email is available"],
#     "loud": false,
#     "prefetch": {"url": "https://github.com/signup", "method": "GET",
#                  "capture": {"token": {"regex": "data-csrf=\"true\" value=\"([^\"]+)\""}}},
#     "request_method": "POST",
#     "urlProbe": "https://github.com/email_validity_checks",
#     "request_form": {"authenticity_token": "{token}", "value": "{}"},
#     "extra": {"login": {"json": "login_name"}}
#   }


def _fill(s, email, captures):
    """Substitute {} (the email) and {capture_name} placeholders in a string."""
    s = s.replace("{}", email)
    for k, v in captures.items():
        s = s.replace("{" + k + "}", v)
    return s


def _fill_obj(obj, email, captures):
    """Recursively _fill() every string in a JSON-ish structure."""
    if isinstance(obj, str):
        return _fill(obj, email, captures)
    if isinstance(obj, dict):
        return {k: _fill_obj(v, email, captures) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill_obj(v, email, captures) for v in obj]
    return obj


def deep_get(obj, dotted):
    """Fetch a nested value by dotted path (supports list indices)."""
    cur = obj
    for part in str(dotted).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def harvest_extra(resp, spec, email):
    """Pull profile fields per a harvest spec. Each value is {"json": path} or
    {"regex": pattern}. Returns a flat {label: value} dict."""
    out = {}
    body = resp.get("body") or ""
    try:
        data = json.loads(body)
    except Exception:
        data = None
    for label, rule in (spec or {}).items():
        val = None
        if isinstance(rule, dict):
            if "json" in rule and data is not None:
                val = deep_get(data, rule["json"])
            elif "regex" in rule:
                m = re.search(rule["regex"], body)
                if m:
                    val = m.group(1) if m.groups() else m.group(0)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        out[label] = val if isinstance(val, (bool, int)) else str(val)
    return out


def check_email(name, site_info, email, timeout=30, proxy=None, verify=True,
                retries=1, rotate_ua=False, delay=0, allow_loud=False):
    """Check whether an account is registered with `email` on one site."""
    record = {
        "site": name,
        "category": site_info.get("category"),
        "url_main": site_info.get("urlMain") or site_info.get("url"),
        "url_user": site_info.get("url"),
        "status": UNKNOWN,
        "http_status": None,
        "elapsed": None,
        "error": None,
        "extra": {},
    }

    # An email format gate (regexCheck), and loud-site gating.
    if not username_allowed(site_info, email):
        record["status"] = ILLEGAL
        return record
    if site_info.get("loud") and not allow_loud:
        record["status"] = LOUD_SKIPPED
        return record

    if delay:
        sleep(delay)

    ua = random.choice(UA_POOL) if rotate_ua else DEFAULT_UA
    jar = http.cookiejar.CookieJar()
    captures = {}

    # Optional prefetch: collect cookies and/or capture a token via regex.
    pf = site_info.get("prefetch")
    if pf:
        pf_headers = dict(BASE_HEADERS)
        pf_headers["User-Agent"] = ua
        pf_headers.update(pf.get("headers", {}))
        pf_resp = http_request(
            _fill(pf["url"], email, {}), method=pf.get("method", "GET"),
            headers=pf_headers, timeout=timeout, allow_redirects=True,
            proxy=proxy, verify=verify, retries=retries, cookie_jar=jar,
        )
        if pf_resp["error"]:
            record["status"] = ERROR
            record["error"] = f"prefetch: {pf_resp['error']}"
            return record
        for key, spec in (pf.get("capture") or {}).items():
            # Capture from a cookie set during the prefetch...
            if isinstance(spec, dict) and spec.get("cookie"):
                val = next((c.value for c in jar if c.name == spec["cookie"]), None)
                if val is not None:
                    if spec.get("decode") == "url":
                        val = urllib.parse.unquote(val)
                    captures[key] = val
                continue
            # ...or via a regex on the prefetch body.
            rgx = spec.get("regex") if isinstance(spec, dict) else spec
            m = re.search(rgx, pf_resp["body"]) if rgx else None
            if m:
                captures[key] = m.group(1) if m.groups() else m.group(0)
        missing = [k for k in (pf.get("capture") or {}) if k not in captures]
        if missing:
            record["status"] = ERROR
            record["error"] = f"could not capture {', '.join(missing)} (site changed?)"
            return record

    # Build the probe request.
    probe_url = _fill(site_info.get("urlProbe") or site_info["url"], email, captures)
    method = site_info.get("request_method", "GET")
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = ua
    headers.update({k: _fill(str(v), email, captures)
                    for k, v in (site_info.get("headers") or {}).items()})

    payload = site_info.get("request_payload")
    if payload is not None:
        payload = _fill_obj(payload, email, captures)
    form = site_info.get("request_form")
    if form is not None:
        form = {k: _fill(str(v), email, captures) for k, v in form.items()}

    resp = http_request(
        probe_url, method=method, headers=headers, timeout=timeout,
        allow_redirects=True, payload=payload, form=form, proxy=proxy,
        verify=verify, retries=retries, cookie_jar=jar,
    )
    record["http_status"] = resp["status"]
    record["elapsed"] = resp["elapsed"]
    if resp["error"]:
        record["status"] = ERROR
        record["error"] = resp["error"]
        return record

    # Reuse the username classifier, then relabel for email semantics.
    verdict = classify(site_info, resp, email)
    record["status"] = {FOUND: REGISTERED, NOT_FOUND: NOT_REGISTERED}.get(verdict, verdict)

    if record["status"] == REGISTERED and site_info.get("extra"):
        record["extra"] = harvest_extra(resp, site_info["extra"], email)
    return record


def run_email_checks(site_data, email, max_workers=20, timeout=30, proxy=None,
                     verify=True, progress=False, retries=1, rotate_ua=False,
                     delay=0, allow_loud=False, proxy_rotator=None):
    """Check `email` across all sites in `site_data`, concurrently."""
    results = []
    workers = max(1, min(max_workers, len(site_data) or 1))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(check_email, name, info, email, timeout,
                      (proxy_rotator.next() if proxy_rotator else proxy),
                      verify, retries, rotate_ua, delay, allow_loud): name
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


def render_email_console(email, results, include_all=False, use_color=True):
    hits = [r for r in results if r["status"] == REGISTERED]

    def c(code, text):
        return f"\033[{code}m{text}\033[0m" if use_color else text

    lines = [f"\nEmail results for '{email}'  "
             f"({len(hits)} registered / {len(results)} checked)"]
    lines.append("-" * 60)
    for r in hits:
        lines.append(f"[{c('92', '+')}] {r['site']:<22} {r['url_main']}")
        for k, v in (r.get("extra") or {}).items():
            lines.append(f"        - {k}: {v}")
    if include_all:
        for r in results:
            if r["status"] == REGISTERED:
                continue
            tag = {NOT_REGISTERED: c("90", "-"), WAF: c("93", "waf"),
                   ERROR: c("91", "err"), ILLEGAL: c("90", "n/a"),
                   LOUD_SKIPPED: c("94", "loud")}.get(r["status"], "?")
            extra = f"  ({r['error']})" if r.get("error") else ""
            lines.append(f"[{tag}] {r['site']:<22} {r['status']}{extra}")
    if not hits and not include_all:
        lines.append("(no registrations found; use --include-all to see every site)")
    return "\n".join(lines)


def render_email_json(email, results, include_all=False):
    rows = results if include_all else [r for r in results if r["status"] == REGISTERED]
    return json.dumps(
        {
            "email": email,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_checked": len(results),
            "total_registered": sum(1 for r in results if r["status"] == REGISTERED),
            "results": rows,
        },
        indent=2,
    )


def render_email_csv(email, results, include_all=False):
    rows = results if include_all else [r for r in results if r["status"] == REGISTERED]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "site", "category", "url", "status", "http_status",
                "extra", "error"])
    for r in rows:
        extra = "; ".join(f"{k}: {v}" for k, v in (r.get("extra") or {}).items())
        w.writerow([email, r["site"], r.get("category") or "", r.get("url_main") or "",
                    r["status"], r["http_status"], extra, r.get("error") or ""])
    return buf.getvalue()


def render_email_markdown(email, results, include_all=False):
    hits = [r for r in results if r["status"] == REGISTERED]
    out = [f"# Email recon report: `{email}`", ""]
    out.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    out.append(f"- Sites checked: {len(results)}")
    out.append(f"- Accounts registered: {len(hits)}")
    out.append("")
    out.append("## Registered")
    out.append("")
    if hits:
        out.append("| Site | URL | Details |")
        out.append("| --- | --- | --- |")
        for r in hits:
            extra = "; ".join(f"{k}: {v}" for k, v in (r.get("extra") or {}).items())
            out.append(f"| {r['site']} | {r['url_main']} | {extra} |")
    else:
        out.append("_No registrations found._")
    out.append("")
    return "\n".join(out)


EMAIL_RENDERERS = {
    "console": render_email_console,
    "json": render_email_json,
    "csv": render_email_csv,
    "md": render_email_markdown,
}


def cmd_email(args):
    site_data, path = load_manifest(
        args.manifest, default=DEFAULT_EMAIL_MANIFEST,
        env_var="USERNAME_RECON_EMAIL_MANIFEST")
    site_data = filter_sites(site_data, only=args.site or None,
                             include_nsfw=args.nsfw)
    if not site_data:
        raise SystemExit("[!] No email sites to check after filtering.")

    print(f"[*] Loaded {len(site_data)} email sites from {path}", file=sys.stderr)
    rotator = build_proxy_rotator(args)

    for email in args.email:
        results = run_email_checks(
            site_data, email,
            max_workers=args.max_workers, timeout=args.timeout,
            proxy=args.proxy, verify=not args.insecure,
            progress=(args.format == "console" and not args.out),
            retries=args.retries, rotate_ua=args.rotate_ua, delay=args.delay,
            allow_loud=args.allow_loud, proxy_rotator=rotator,
        )
        if args.format == "console":
            text = render_email_console(email, results,
                                        include_all=args.include_all,
                                        use_color=not args.no_color)
        else:
            text = EMAIL_RENDERERS[args.format](email, results,
                                                include_all=args.include_all)
        if args.out:
            out_path = args.out
            if len(args.email) > 1:
                base, ext = os.path.splitext(args.out)
                out_path = f"{base}_{email}{ext}"
            with open(out_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"[*] Wrote {out_path}", file=sys.stderr)
        else:
            print(text)


# --------------------------------------------------------------------------- #
# Infostealer intelligence (Hudson Rock OSINT API) -- enrichment, not enumeration
# --------------------------------------------------------------------------- #
#
# Hudson Rock exposes a free OSINT endpoint that says whether a username or email
# appears in infostealer-malware logs. This is a THIRD-PARTY lookup: the identifier
# leaves the machine and is sent to Hudson Rock, who may log the query. So it is
# gated behind explicit consent (--confirm) and always prints a privacy notice and
# attribution. It reuses the same stdlib HTTP layer. Source/credit: Hudson Rock
# (https://www.hudsonrock.com); pattern from kaifcodec/user-scanner core/hudson.py.

HUDSON_BASE = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/"
HUDSON_NOTICE = (
    "PRIVACY NOTICE: Hudson Rock is a third-party intelligence service. The "
    "identifier you query is sent to their API and they may log it. Use only for "
    "authorized work. Attribution: data by Hudson Rock (https://www.hudsonrock.com)."
)


def hudson_lookup(target, is_email=False, timeout=10, proxy=None, verify=True,
                  retries=1):
    """Query Hudson Rock for infostealer infections tied to a username or email.

    Returns a dict: {target, type, queried_at, status, stealers, error, source}.
    status is one of: infections_found / clean / no_data / error.
    """
    endpoint = "search-by-email" if is_email else "search-by-username"
    param = "email" if is_email else "username"
    url = f"{HUDSON_BASE}{endpoint}?{urllib.parse.urlencode({param: target})}"
    out = {
        "target": target,
        "type": param,
        "queried_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": None,
        "stealers": [],
        "error": None,
        "source": "Hudson Rock (https://www.hudsonrock.com)",
    }
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = DEFAULT_UA
    headers["Accept"] = "application/json"
    resp = http_request(url, method="GET", headers=headers, timeout=timeout,
                        proxy=proxy, verify=verify, retries=retries)
    if resp["error"]:
        out["status"] = "error"
        out["error"] = resp["error"]
        return out
    if resp["status"] == 404:
        out["status"] = "no_data"
        return out
    if resp["status"] != 200:
        out["status"] = "error"
        out["error"] = f"HTTP {resp['status']}"
        return out
    try:
        data = json.loads(resp["body"])
    except Exception:
        out["status"] = "error"
        out["error"] = "non-JSON response"
        return out
    stealers = data.get("stealers") or []
    out["stealers"] = stealers
    out["status"] = "infections_found" if stealers else "clean"
    return out


def render_infostealer_console(results, use_color=True):
    def c(code, text):
        return f"\033[{code}m{text}\033[0m" if use_color else text

    lines = ["\n== HUDSON ROCK INFOSTEALER INTELLIGENCE =="]
    lines.append(c("96", "Attribution: data by Hudson Rock (https://www.hudsonrock.com)"))
    for r in results:
        head = f"\n[{r['type']}] {r['target']}: "
        if r["status"] == "infections_found":
            n = len(r["stealers"])
            lines.append(head + c("91", f"{n} infostealer infection(s) found"))
            for i, s in enumerate(r["stealers"], 1):
                lines.append(f"  Infection #{i}:")
                lines.append(f"    - Stealer family: {s.get('stealer_family', 'Unknown')}")
                lines.append(f"    - Date compromised: {s.get('date_compromised', 'Unknown')}")
                lines.append(f"    - Operating system: {s.get('operating_system', 'Unknown')}")
                lines.append(f"    - Computer name: {s.get('computer_name', 'Unknown')}")
                tl = s.get("top_logins") or []
                if tl:
                    lines.append(f"    - Sample logins: {', '.join(tl[:3])}...")
            lines.append(c("93", "  Note: credentials on infected machines should be treated as at risk."))
        elif r["status"] == "clean":
            lines.append(head + c("92", "no infections found"))
        elif r["status"] == "no_data":
            lines.append(head + c("90", "no data in Hudson Rock"))
        else:
            lines.append(head + c("93", f"could not query ({r.get('error')})"))
    return "\n".join(lines)


def cmd_infostealer(args):
    print(HUDSON_NOTICE, file=sys.stderr)
    if not args.confirm:
        raise SystemExit(
            "[!] Refusing to send identifiers to a third party without consent.\n"
            "    Re-run with --confirm once the analyst has agreed.")
    results = [hudson_lookup(t, is_email=args.email, timeout=args.timeout,
                             proxy=args.proxy, verify=not args.insecure,
                             retries=args.retries)
               for t in args.target]
    if args.format == "json":
        print(json.dumps({"checked": len(results), "results": results}, indent=2))
    else:
        print(render_infostealer_console(results, use_color=not args.no_color))


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
        sp.add_argument("--proxy", help="A single HTTP(S) proxy URL, e.g. http://127.0.0.1:8080")
        sp.add_argument("--proxy-file",
                        help="File of proxies (one per line) to rotate round-robin.")
        sp.add_argument("--validate-proxies", action="store_true",
                        help="Test each proxy first and use only the working ones "
                             "(writes validated_proxies.txt).")
        sp.add_argument("--insecure", action="store_true",
                        help="Disable TLS certificate verification.")
        sp.add_argument("--nsfw", action="store_true",
                        help="Include sites flagged NSFW (excluded by default).")
        sp.add_argument("--retries", type=int, default=1,
                        help="Retries on transient transport errors, e.g. timeouts "
                             "(default 1; real HTTP responses are never retried).")
        sp.add_argument("--rotate-ua", action="store_true",
                        help="Rotate the User-Agent from a small modern pool per request.")
        sp.add_argument("--delay", type=float, default=0,
                        help="Seconds to pause before each request (politeness/rate "
                             "control; default 0).")

    # search
    s = sub.add_parser("search", help="Check usernames across sites.")
    add_common(s)
    s.add_argument("username", nargs="*", help="One or more usernames to check.")
    s.add_argument("--site", action="append", default=[],
                   help="Limit to a named site (repeatable).")
    s.add_argument("--permute", help="Opt-in: expand a pattern into candidate "
                   "usernames, e.g. 'alice[0-9]{0-2}'. Off by default.")
    s.add_argument("--permute-limit", type=int, default=500,
                   help="Max candidates generated by --permute (default 500).")
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
    v.add_argument("--email", action="store_true",
                   help="Verify the EMAIL manifest (email_data.json) instead of usernames.")
    v.add_argument("--allow-loud", action="store_true", default=True,
                   help="Include loud email sites when verifying (default on for verify).")
    v.set_defaults(func=cmd_verify)

    # email
    e = sub.add_parser("email", help="Check which sites have an account for an email.")
    add_common(e)
    e.add_argument("email", nargs="+", help="One or more emails to check.")
    e.add_argument("--site", action="append", default=[],
                   help="Limit to a named site (repeatable).")
    e.add_argument("--format", choices=list(EMAIL_RENDERERS), default="console",
                   help="Output format (default console). Pick json/csv/md per request.")
    e.add_argument("--out", help="Write output to this file instead of stdout.")
    e.add_argument("--include-all", action="store_true",
                   help="Include not-registered/blocked/error/loud-skipped sites.")
    e.add_argument("--no-color", action="store_true", help="Disable colored console output.")
    e.add_argument("--allow-loud", action="store_true",
                   help="Include sites whose probe may notify the target (off by default).")
    e.set_defaults(func=cmd_email)

    # infostealer
    i = sub.add_parser(
        "infostealer",
        help="Hudson Rock infostealer-log lookup (third-party; requires --confirm).")
    i.add_argument("target", nargs="+", help="Username(s) or email(s) to look up.")
    i.add_argument("--email", action="store_true", help="Treat the targets as emails.")
    i.add_argument("--confirm", action="store_true",
                   help="Required consent: send the identifier to Hudson Rock's API.")
    i.add_argument("--format", choices=["console", "json"], default="console")
    i.add_argument("--no-color", action="store_true",
                   help="Disable colored console output.")
    i.add_argument("--timeout", type=float, default=10)
    i.add_argument("--retries", type=int, default=1,
                   help="Retries on transient transport errors (default 1).")
    i.add_argument("--proxy", help="HTTP(S) proxy URL.")
    i.add_argument("--insecure", action="store_true",
                   help="Disable TLS certificate verification.")
    i.set_defaults(func=cmd_infostealer)

    # update
    u = sub.add_parser("update", help="Download the latest community site manifest.")
    u.add_argument("--manifest", help="Where to save (default: bundled data/data.json).")
    u.add_argument("--url", help="Override the upstream manifest URL.")
    u.add_argument("--timeout", type=float, default=60)
    u.add_argument("--no-preserve", action="store_true",
                   help="Overwrite wholesale without keeping locally added sites "
                        "(not recommended; a backup is still written).")
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
