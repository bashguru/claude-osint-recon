# osint-recon (team handoff)

**What it is.** A Claude plugin for OSINT username enumeration with a
**browser-first evidence workflow**. Give it a handle and it triages ~481 public
sites for an account, **verifies the hits in a real browser, screenshots each one**,
and builds a **court-ready HTML evidence report**. Built for OSINT analysts,
including non-technical ones. Authorized/lawful use only, meaning your own footprint,
consented investigations, security research, brand/impersonation monitoring.

## How it runs (execution tiers, sandbox is the last resort)

1. **Browser MCP (primary).** A real browser does the verification and evidence.
   The **Browser MCP extension** comes first (the analyst's own browser, with fewer
   challenges, inline screenshots, and they keep their tabs), `playwright-mcp` as the
   fallback. Only tier that produces screenshots.
2. **Local CLI (secondary).** `hunt.py` on the analyst's own machine for fast bulk
   triage (real IP → fewer blocks).
3. **Claude sandbox (last resort).** `hunt.py` in-sandbox only when nothing else is
   available.

Bot challenges are **never auto-bypassed**. The per-run policy is **assisted** (the
analyst solves it) or **automated** (screenshot the block as evidence and
continue). Breadth runs on the concurrent triage engine; the browser only verifies
the confirmed hits, one clean tab at a time. Closing a tab never loses progress
(state lives in the case file).

## Seven skills inside

- **preflight** checks all prerequisites (browser MCP, local execution for
  triage, Python) and helps a non-technical analyst set up anything missing. Runs
  first.
- **username-search** runs triage → browser-verify → capture evidence → interpret.
- **email-search** does the same by email address against ~98 public
  signup/validation/login-check endpoints (loud and NSFW sites off by default).
- **recon** orchestrates username + email together, plus an optional Hudson Rock
  infostealer-leak check, into one evidence report (no detection logic of its own).
- **evidence-report** is the capture protocol plus the builder for the self-contained HTML report.
- **site-healing** tests detection with known-good/known-bad handles and repairs
  sites when they change.
- **add-site** assesses a new site's candidacy and derives + verifies a detection rule
  (logged-out, using a throwaway account as the oracle).

## Run it (three ways)

- **Cowork (easiest).** Open `osint-recon.plugin` in Claude and install it (or
  Settings → Capabilities). Then ask in plain language, such as *"find the username johndoe
  and capture evidence"* or *"build me the report"*. **You can ask for outputs at the
  end**, whether an HTML report, CSV/JSON, or a Word/PDF write-up.
- **Command line (triage only, no Claude needed).** Python 3.8+. From
  `skills/username-search/scripts/`, run `python3 hunt.py search johndoe --format json`,
  `python3 hunt.py update`, `python3 hunt.py verify --all`, `python3 hunt.py list`.
- **Claude Code.** Add the `osint-recon` folder as a plugin, then ask as above.

## The evidence report

`skills/evidence-report/scripts/build_report.py` turns a case file (findings +
screenshots) into **one** self-contained HTML file with embedded screenshots, full
URLs, UTC capture times, and a **SHA-256** per screenshot (re-verified in-browser).
It's also interactive. Tick the **relevant** evidence and **export the subset** as
CSV or as a JSON in the plugin's own case-file schema (a **"Copy for Claude"**
button round-trips it straight back for a summary or a tighter report). Prints /
exports to PDF cleanly.

## What's in this folder

| Path | What it is |
| --- | --- |
| `.claude-plugin/plugin.json` | Plugin manifest (name, version, author). |
| `README.md` | Full overview and usage. |
| `HANDOFF.md` | This file. |
| `NOTICE` | Attribution + licensing (site list derives from the MIT-licensed Sherlock project). |
| `skills/preflight/` | Prerequisite check (browser, local execution, Python) + plain-language setup (`references/setup.md`). |
| `skills/username-search/` | Search workflow; engine `scripts/hunt.py`; manifest `data/data.json`; `references/tradecraft.md`. |
| `skills/evidence-report/` | Capture + report; generator `scripts/build_report.py`; `references/evidence-protocol.md`. |
| `skills/site-healing/` | Diagnose & repair detection rules. |
| `skills/add-site/` | Onboard a new site and derive its rule. |

## Notes

- Public pages only. Never logs in to detect, never bypasses authentication or bot
  challenges. A `found` result is a lead, not proof of identity.
- Detection rules are always built to work **logged out** (that's how the engine
  probes).
- NSFW sites are excluded by default (pass `--nsfw`).
- The bundled site list is a snapshot; run `hunt.py update` for the latest.
- **add-site** uses throwaway/dedicated test accounts as detection oracles and can
  store their credentials in a local `oracle-credentials.json` (outside the plugin,
  `chmod 600`, auto-`.gitignore`d) so Claude can re-verify/self-heal later without
  re-asking. Never store personal or reused passwords; credentials never appear in
  the report, exports, or chat.
