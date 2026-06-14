---
name: evidence-report
description: >
  This skill should be used to capture screenshot evidence of OSINT findings and
  assemble them into a single, self-contained, court-ready HTML report. Trigger
  when the user says things like "capture evidence", "screenshot the accounts",
  "build an evidence report", "document these profiles", "make the OSINT report",
  "I'd like the output now", or after a username-search turns up accounts worth
  documenting. Produces one HTML file with embedded screenshots, full URLs, UTC
  capture times, and a SHA-256 hash per screenshot for integrity.
metadata:
  version: "0.3.0"
  author: "Claude OSINT Investigator"
---

# Evidence report (capture + court-ready HTML)

Turn confirmed findings into a defensible deliverable. It is a **single HTML file** that
embeds every screenshot, with the full URL, the UTC capture time, the capture
method, and a **SHA-256 hash** of each image. It opens offline anywhere and can be
archived or attached as one artifact. This is the standard output of the plugin.

Use this together with **username-search** (which finds and verifies the accounts)
and **preflight** (which confirms prerequisites are ready).

## When to use

- The analyst asks for "evidence", "a report", "the output", screenshots, or
  documentation of what was found.
- A search has produced `found` accounts worth preserving.
- Always offer it at the end of a search. The analyst may not know it exists.

## Capture protocol (court-ready)

Capture happens in **Playwright** (the required browser, driven with
`mcp__playwright__*`, run visible), and **only for confirmed triage hits**, not the
whole catalog.
For **each** confirmed account, one clean tab at a time:

1. **Navigate** to the profile URL.
2. **Confirm existence from the lightest signal**, final URL + page title (and one
   targeted text check only if needed). Don't parse the whole DOM.
3. **Screenshot** the page into the case evidence folder
   (`evidence/<case-id>/<site>.png` inside the selected project folder).
4. **Record** a finding entry (see the metadata schema in the reference): site,
   category, status, full URL, UTC capture time, method, page title, HTTP status
   if known, the screenshot path, and notes.
5. **Close the tab** (`browser_close`) before the next site. Never linger or
   accumulate tabs. If a tab was closed or drifted, re-navigate. Canonical state
   lives in the case file, so progress is never lost.

On a **bot challenge**, never auto-bypass it. Apply the run's bot policy (set in
**username-search**). Under **Assisted**, pause for the analyst to solve it in the
visible Playwright window (if they close the tab, record `waf` + "tab closed, not verified"). Under
**Automated**, screenshot the block page as evidence, record `waf` + "bot
challenge blocked, could not verify", and continue. Full detail in
`${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/references/evidence-protocol.md`.

## Build the report

The generator is dependency-free Python (no `pip install`):
`${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py`.

1. **Scaffold a case file** (optional, since you can also write the JSON directly):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py" \
       --init evidence/case.json --case-id CASE-2026-014 --subject johndoe \
       --investigator "Investigator Name"
   ```

   The `--investigator` flag is optional. Leave it off when no investigator name
   was provided, and the report shows "Not provided" in that field.

2. **Fill in `findings`**, one entry per captured account, with the screenshot
   path relative to the case file (or absolute). Set the `case` header fields
   (title, case_id, investigator, subject, authorization basis, opened).

3. **Build the HTML:**

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py" \
       evidence/case.json --out "Evidence_<subject>.html"
   ```

The generator computes each screenshot's SHA-256 from the file, embeds the image
as base64, and renders the report. Save the `.html` into the selected project
folder so the analyst keeps it.

### What the report contains

A case header (case id, investigator, subject, authorization basis, dates), summary
counts, and a searchable/filterable card per finding showing the screenshot
(click to enlarge), the clickable URL, the UTC capture time, the method, and the
SHA-256. When opened in a modern browser it **re-verifies** each hash from the
embedded bytes and shows "integrity verified". It also prints/export-to-PDFs
cleanly with every screenshot expanded.

## Triage & export inside the report (interactive, no tools needed)

The report is also a triage surface. Every card has a **"Relevant, include in
export"** checkbox (all on by default). The analyst can keep the signal and drop
the noise, then export just the relevant subset, entirely in the browser, offline:

- **Select all / None / Only "found" / Show relevant only** gives quick selection and
  a focused view. Deselected cards dim, and are hidden when printed/exported to PDF.
- **Export CSV** writes the selected findings as a spreadsheet (includes the SHA-256).
- **Export JSON (case file)** writes the selected findings in *this plugin's own
  case-file schema*. This round-trips. Feed it straight back to
  `build_report.py` to regenerate a tighter report, or hand it to Claude.
- **Copy for Claude** copies that JSON to the clipboard **with a ready
  instruction**, so the analyst can paste it into a chat and say nothing else.

Point this out to non-technical analysts: *"tick the ones that matter, then click
Copy for Claude and paste it back to me, and I'll write the summary."* When they do,
you receive a valid case file (findings + URLs + hashes) and can build an evidence
summary, a Word/PDF write-up, or a new focused report from it.

## Share it

After building, present the HTML file to the analyst with `present_files` and give
a one-line summary (e.g. "Evidence report, 7 accounts, screenshots embedded").
Don't paste the report contents into chat.

## Let the analyst choose the output

The HTML report is the default, but **tell them they can ask for other formats**:

- **CSV / JSON** of the findings to pivot on (the username-search engine emits
  these directly, or export from the case file).
- **Word (.docx) or PDF**, by feeding the findings (and, if wanted, the screenshots)
  to the **docx** or **pdf** skills for a formal document.

Offer; don't assume. Keep it interactive.
