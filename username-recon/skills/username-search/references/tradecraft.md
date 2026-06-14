# Username-enumeration tradecraft & manifest schema

This is the "how it actually works" reference for the username-recon engine.
Read it when adding sites, repairing detection, or explaining the method.

## The core idea

A username-enumeration tool does not "search" anything. It **guesses the profile
URL** for a username on each known site and inspects the response to decide
whether that profile exists. Everything rests on one observation. A site returns
a *different, predictable* response for "this profile exists" vs "this profile
does not exist." The whole craft is encoding that difference per site, then
firing the checks fast and reading them correctly.

There are three reliable signals, and every site uses one (or a combination):

### 1. `status_code`
The site returns `200` for a real profile and a non-2xx (usually `404`) for a
missing one. This is the cheapest signal, since a `HEAD` request is enough, so we never
download the page body. ~⅔ of real-world sites work this way.

- Found  → status is 2xx.
- Not found → status ≥ 300 or < 200, **or** the status is in the site's
  `errorCode` list (some sites answer `200` with a "not found" page but use a
  specific code like `404`/`410` to mark absence).

### 2. `message`
The site returns `200` either way, but the body of a missing profile contains a
tell-tale string ("Page Not Found", "user does not exist", a specific `<title>`).
This needs a `GET` (we must read the body).

- Not found → the `errorMsg` string (or any string in the `errorMsg` list) is
  present in the body.
- Found → none of those strings are present.

Note the inverted logic. We look for the **absence** of the "not found" message.

### 3. `response_url`
The site redirects a missing profile somewhere else (e.g. to the homepage or a
login page). We **disable redirect following** so we can see the original status.

- Found → status is 2xx (the profile page loaded directly).
- Not found → anything else (a 3xx redirect, etc.).

## Why the supporting machinery exists

- **User-Agent spoofing.** Many sites serve bot-detection junk to default
  clients. We send a real Firefox UA so we get the same page a human would.
- **`regexCheck` pre-filter.** Each site has username rules (length, allowed
  characters). If the target username can't be valid there, we skip the request
  entirely. That's faster, and avoids false hits on sites that "helpfully" 200 every
  URL. A skipped site is reported as `illegal`.
- **Concurrency.** Checks are independent, so we fire them across a thread pool
  (default 20 workers). 400 sites finish in seconds instead of minutes.
- **WAF fingerprinting.** Cloudflare / AWS WAF / PerimeterX challenge pages
  return `200` with a challenge body, which naively reads as "found". We match
  known fingerprints and report `waf` (unknown) instead of a false positive.
  This list is the most time-sensitive part of the tool; WAFs change.
- **`urlProbe`.** Sometimes the human-facing profile URL is hard to check but an
  API endpoint gives a clean yes/no. `url` is what we show the user; `urlProbe`
  (if present) is what we actually request.

## Execution tiers (where requests run)

`hunt.py` is a fast **triage** engine, not the final word. Run work on the highest
tier available; the Claude sandbox is the last resort, not the default.

1. **Browser MCP, primary.** A real browser (the browser-mcp extension first,
   playwright-mcp as the fallback) renders the page like a human sees it and is the
   only tier that produces **screenshot evidence**. Use it to confirm and document
   every `found` hit.
2. **Local CLI, secondary.** Run `hunt.py` on the analyst's own machine (e.g. via
   a Desktop Commander MCP or their terminal). Same real IP as their browser, so
   far fewer firewall blocks than the sandbox. Best for fast bulk triage.
3. **Sandbox, last resort.** Run `hunt.py` in the Claude sandbox only when neither
   of the above is available. Its IP is often flagged → more `waf`/blocked results.
   Never present sandbox output as final evidence; re-verify hits in the browser.

The efficient pattern (the hard default) is to **triage** the full list with `hunt.py`
(Tier 2 on the analyst's machine, else Tier 3), then **browser-verify only the
`found` hits**. Decide existence from the final URL + title (don't parse the whole
DOM), and screenshot for evidence. Never hand-browse the catalog for breadth.

### Page hygiene

In the browser, work **one page at a time**: open → confirm → screenshot → record
metadata → **close the tab** → next. Never leave a captured page lingering or let
tabs accumulate. With the browser-mcp extension, reuse the single controlled tab
and navigate it onward; with the Playwright fallback, close the tab
(`browser_tabs`/`browser_close`).

## Bot detection & challenges

`waf` fingerprinting (above) catches firewall **interstitials** during triage and
reports "unknown" instead of a false positive. A **human-verification challenge**
(Cloudflare "checking your browser", "Press & Hold", hCaptcha/reCAPTCHA, "verify
you are human") is different. It must be handled in the browser, by the analyst.

The rule is **never auto-bypass**. Pick a policy at run start (see the
**username-search** skill). **Assisted** means you pause and let the analyst solve the
challenge in their own browser (if they close the tab, record `waf` + "tab closed,
not verified"). **Automated** means you screenshot the block page as evidence, record
`waf` + "bot challenge, blocked, could not verify", and continue. Claude never
solves or evades the challenge itself. A human solving their own challenge is fine,
defeating it programmatically is not. See the **evidence-report** skill's
`evidence-protocol.md` for the capture mechanics.

## Manifest schema (`data/data.json`)

The manifest is a JSON object: `{ "Site Name": { ...fields... }, ... }`. Fields:

| Field             | Required | Meaning |
| ----------------- | -------- | ------- |
| `url`             | yes      | Profile URL with `{}` where the username goes. Shown to the user. |
| `urlMain`         | yes      | Site homepage (for reference/reporting). |
| `errorType`       | yes      | `"status_code"`, `"message"`, or `"response_url"` (or a list combining them). |
| `errorMsg`        | for `message` | String or list of strings that appear when a profile is missing. |
| `errorCode`       | optional (`status_code`) | Int or list of status codes that mean "not found" even if 200-ish. |
| `urlProbe`        | optional | Alternate URL to request instead of `url` (e.g. an API). Also `{}`-interpolated. |
| `regexCheck`      | optional | Regex the username must match for the site to be checked. |
| `request_method`  | optional | `GET`/`HEAD`/`POST`/`PUT`. Defaults to `HEAD` for pure `status_code`, else `GET`. |
| `request_payload` | optional | JSON body (for `POST`), `{}`-interpolated. Used by GraphQL/API sites. |
| `headers`         | optional | Extra request headers to merge in. |
| `isNSFW`          | optional | `true` marks an adult site; excluded unless `--nsfw`. |
| `username_claimed`| yes (by convention) | A username that **does** exist on the site. This is the oracle the site-healing skill uses to test detection. |

### Minimal examples

`status_code` site:
```json
"About.me": {
  "errorType": "status_code",
  "url": "https://about.me/{}",
  "urlMain": "https://about.me/",
  "username_claimed": "blue"
}
```

`message` site with multiple tells and a format rule:
```json
"AllMyLinks": {
  "errorType": "message",
  "errorMsg": ["Page not found"],
  "regexCheck": "^[a-z0-9][a-z0-9-]{2,32}$",
  "url": "https://allmylinks.com/{}",
  "urlMain": "https://allmylinks.com/",
  "username_claimed": "blue"
}
```

`POST`/API site using a separate probe URL:
```json
"Anilist": {
  "errorType": "status_code",
  "request_method": "POST",
  "request_payload": {"query":"query($name:String){User(name:$name){id}}","variables":{"name":"{}"}},
  "url": "https://anilist.co/user/{}/",
  "urlProbe": "https://graphql.anilist.co/",
  "username_claimed": "Josh"
}
```

## Adding a new site

1. Open the target site and view a **known-existing** profile and a **definitely
   missing** one (e.g. a long random string).
2. Compare the two responses:
   - Different HTTP status? → `status_code` (note any odd code in `errorCode`).
   - Same status but different body? → `message`; copy a stable substring unique
     to the "missing" page into `errorMsg` (prefer something in a `<title>` or
     error container, not boilerplate that could change).
   - Missing profile redirects away? → `response_url`.
3. Fill in `url`, `urlMain`, `errorType`, the detection field, and a real
   `username_claimed`. Add `regexCheck` if the site restricts usernames.
4. Verify with the site-healing skill (`hunt.py verify --site "New Site"`): a
   correct entry returns `healthy` (known→found, random→not_found).

## When detection breaks (self-heal playbook)

Sites change. Symptoms and fixes:

- **false_negative** (known account reads as not-found): the "not found" message
  changed, the success status changed, or the URL path moved. Re-inspect a known
  profile and update `errorMsg` / `errorCode` / `url`.
- **false_positive** (random username reads as found): the site now returns 200
  for everything (switch to `message` detection), or the `errorMsg` string moved
  (update it), or it started redirecting (switch to `response_url`).
- **waf_blocked**: a firewall is intercepting probes. Sometimes a different
  `urlProbe`, extra `headers`, or a `--proxy` gets a clean response; otherwise
  the site is best left flagged.
- **error**: transient network/TLS. Re-run with a longer `--timeout`.

The site-healing skill automates the diagnosis using `username_claimed`; this
section is the manual model behind it.

## Etiquette & limits

- Public pages only; this never logs in or bypasses authentication.
- Keep `--max-workers` reasonable and don't loop aggressively against one site,
  because that's how you trip WAFs and rate limits.
- A `found` hit is a **lead**, not identity proof. The same handle on two sites
  may be two different people. Corroborate before drawing conclusions.
