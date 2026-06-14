# Evidence protocol & case-file schema

The detailed reference behind the **evidence-report** skill. It covers how to capture
defensible screenshot evidence in the browser, what metadata to record, where
files go, and the exact case-file format the generator (`build_report.py`)
consumes.

## Principles

- **Public pages only.** Never log in on the subject's behalf, never bypass
  access controls, never defeat a bot challenge. Capture what is publicly visible.
- **Capture the truth of the moment.** A screenshot documents what was visible at
  a specific UTC time at a specific URL, nothing more. An account is a *lead*,
  not proof of identity.
- **Integrity is computed, not asserted.** Each screenshot is hashed (SHA-256)
  from its file bytes so anyone can confirm it wasn't altered after capture.

## Where evidence lives

Save screenshots as files in the **selected project folder**, under a per-case
directory:

```
<project folder>/evidence/<case-id>/<site>.png
<project folder>/evidence/<case-id>/case.json
<project folder>/Evidence_<subject>.html      # the built report
```

Saving real files (not just inline images) matters: the generator hashes the file
bytes, and the report stays portable. If a browser tool returns a screenshot
inline instead of writing a file, save those bytes to the path above before
building.

## Capturing in the browser (per tool)

Capture one page at a time, **only for confirmed triage hits**, with this flow: **navigate →
confirm (from final URL + title; don't parse the whole DOM) → screenshot → record
→ close.** If a tab is closed or drifts, re-navigate. Canonical state lives in the
case file, so a closed tab never loses progress.

### Browser MCP extension (`mcp__browsermcp__*`) (primary)

- `browser_navigate` → the profile URL.
- `browser_snapshot` to confirm the profile exists (correct username; not a "not
  found" page); `browser_screenshot` to capture, then save the returned image to
  `evidence/<case-id>/<site>.png`.
- The extension drives the analyst's own browser and has no close tool, so **reuse
  the single controlled tab** by navigating it onward to the next URL rather than
  opening more. The analyst keeps their other tabs and closes this one when done.

### Playwright (`mcp__playwright__*`) (fallback)

- `browser_navigate` → the profile URL.
- `browser_wait_for` → let it settle; then `browser_snapshot` to confirm the
  profile exists.
- `browser_take_screenshot` → full page. **Note:** Playwright saves into its own
  output directory, which may be a different machine/sandbox than the report
  generator, so make sure the file ends up in `evidence/<case-id>/` where
  `build_report.py` can read it. (This split is exactly why the extension is
  preferred.)
- `browser_tabs` (close) or `browser_close` → **close the tab before the next
  site.** Do not accumulate tabs.

### Bot challenges (policy, never auto-bypass)

Never programmatically solve or bypass a challenge (Cloudflare interstitial, "Press
& Hold", hCaptcha/reCAPTCHA, "verify you are human"). Apply the run's bot policy
(chosen in **username-search**):

- **Assisted.** Surface the challenge in the analyst's own browser and **pause**;
  on their confirmation, re-check and capture. If they **close the tab or skip**,
  record the finding as `waf` with note "tab closed, not verified" and move on.
- **Automated / unattended.** Don't wait. **Screenshot the challenge page itself**
  as the evidence, record the finding as `waf` with note "bot challenge blocked,
  could not verify (captured for later review)", and continue.

A challenged site is `waf` ("could not verify"), never a real negative.

## Timestamps

Record `captured_at` in **UTC, ISO-8601, `Z`-suffixed**, e.g.
`2026-06-14T15:03:21Z`. At capture time you can get it with:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
```

## Case-file schema (what `build_report.py` reads)

A JSON object with a `case` header and a `findings` array.

```json
{
  "schema": "1.0",
  "case": {
    "title": "Username footprint for johndoe",
    "case_id": "CASE-2026-014",
    "investigator": "",
    "subject": "johndoe",
    "authorization": "Self-footprint / consented investigation / authorized research",
    "opened": "2026-06-14T15:00:00Z",
    "notes": "Free-text scope / context shown in the report footer.",
    "methodology": "Optional. Overrides the default methodology paragraph."
  },
  "findings": [
    {
      "site": "GitHub",
      "category": "dev",
      "status": "found",
      "profile_url": "https://github.com/johndoe",
      "captured_url": "https://github.com/johndoe",
      "captured_at": "2026-06-14T15:03:21Z",
      "method": "playwright-mcp",
      "page_title": "johndoe (John Doe) · GitHub",
      "http_status": 200,
      "screenshot": "evidence/CASE-2026-014/github.png",
      "notes": "Public profile, 42 repos, location 'NYC'."
    }
  ]
}
```

### `case` fields

| Field | Required | Meaning |
| --- | --- | --- |
| `title` | recommended | Report heading. Defaults from `subject` if omitted. |
| `case_id` | recommended | Your case/reference identifier. |
| `investigator` | optional | Investigator name shown on the report. Leave blank to omit it. |
| `subject` | recommended | The username/handle investigated. |
| `authorization` | recommended | The lawful basis (self-footprint, consent, authorized research). |
| `opened` | optional | When the case opened (UTC ISO-8601). |
| `notes` | optional | Scope/context; shown in the footer. |
| `methodology` | optional | Replaces the default methodology paragraph. |

### `finding` fields

| Field | Required | Meaning |
| --- | --- | --- |
| `site` | yes | Platform name (card title). |
| `profile_url` | yes | The public profile URL (clickable in the report). |
| `screenshot` | yes* | Path to the screenshot file (relative to the case file, or absolute). *Omit only for a documented `waf`/no-image finding. |
| `captured_at` | recommended | UTC ISO-8601 capture time. |
| `status` | optional | `found` (default), `not_found`, `waf`, `error`. Anything else renders as "review". |
| `category` | optional | `social`, `dev`, `gaming`, `forum`, `professional`, `media`, `commerce`, `crypto`, `other` (default). Drives the filter chips. |
| `captured_url` | optional | The exact URL navigated to, if it differs from `profile_url`. |
| `method` | optional | `browser-mcp` (extension) / `playwright-mcp` / etc. |
| `page_title` | optional | The page `<title>` at capture. |
| `http_status` | optional | HTTP status code, if known. |
| `notes` | optional | What the screenshot shows; observations. |

For each finding with an image, the generator adds the **SHA-256** of the file and the
file size. These are not stored in the case file. They are computed at build time
so they always match the actual bytes.

## Verifying integrity independently

Each card shows the SHA-256 the generator computed. To verify a screenshot
outside the report:

```bash
shasum -a 256 evidence/CASE-2026-014/github.png   # macOS
sha256sum  evidence/CASE-2026-014/github.png       # Linux
```

The value must match the report. The report itself also recomputes each hash
in-browser (Web Crypto) and labels it "integrity verified" when it matches.

## Build & deliver

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py" \
    evidence/<case-id>/case.json --out "Evidence_<subject>.html"
```

Run it wherever Python can see the screenshot files (the analyst's machine, or the
sandbox via the mounted project folder). Save the HTML into the project folder and
present it to the analyst.
