# username-recon

OSINT **username enumeration** as a Claude plugin — find where a username exists
across hundreds of public websites, **verify each hit in a real browser, and
capture court-ready screenshot evidence** — plus a **self-healing** capability
that keeps the detection accurate as those sites change.

It is a clean-room, dependency-free re-implementation of the
[Sherlock](https://github.com/sherlock-project/sherlock) tradecraft for the fast
triage step, wrapped in a browser-first evidence workflow built for OSINT analysts
(including non-technical ones).

## What it does

1. **Triage** a username across ~481 sites with a dependency-free engine
   (`hunt.py`) to get the short list of likely accounts.
2. **Verify in a real browser** (via an MCP — the Browser MCP extension or
   Playwright), so results reflect what a human actually sees, and **capture a
   screenshot** of each confirmed profile.
3. **Report**: assemble the findings into a single, self-contained, court-ready
   **HTML evidence report** — embedded screenshots, full URLs, UTC capture times,
   and a SHA-256 hash per screenshot.

The Claude sandbox is the **last** resort, not the default (see Execution tiers).

## Execution tiers (browser-first)

| Tier | Tool | Role |
| --- | --- | --- |
| 1 — primary | **Browser MCP**: **browser-mcp extension** first, `playwright-mcp` as fallback | Verify accounts and capture screenshot evidence. Only tier that produces evidence. |
| 2 — secondary | **Local CLI** (`hunt.py` on the analyst's machine) | Fast bulk triage with the analyst's real IP — far fewer firewall blocks. |
| 3 — last resort | **Claude sandbox** (`hunt.py` in-sandbox) | Triage only when no browser/local CLI is available; flagged IP means more blocks. |

**Triage first:** breadth runs on the concurrent `hunt.py` engine; the browser only
verifies and screenshots the handful of confirmed hits (decided from URL + title).
On **bot challenges** the plugin never auto-bypasses — you pick a policy per run:
**assisted** (you solve it in your browser) or **automated** (screenshot the block
as evidence and move on). Pages are worked one at a time and closed after capture;
closing a tab never loses progress (state lives in the case file).

## Components

| Component | Purpose |
| --- | --- |
| Skill: **preflight** | Check all prerequisites (browser MCP, local execution for triage, Python) and walk a non-technical analyst through setting up anything missing. Runs first. |
| Skill: **username-search** | Triage, browser-verify, capture evidence, choose output, interpret results. |
| Skill: **evidence-report** | Capture protocol + build the court-ready HTML report. |
| Skill: **site-healing** | Diagnose false positives/negatives and repair the manifest. |
| Skill: **add-site** | Assess whether a new site is a valid candidate, derive its detection rule (logged-out, using a throwaway account as the oracle), verify it, and store the throwaway oracle credentials locally for reuse. |
| Engine: `hunt.py` | Dependency-free triage CLI: `search`, `verify`, `update`, `list`. |
| Generator: `build_report.py` | Dependency-free: turns findings + screenshots into one self-contained HTML report. |
| Manifest: `data/data.json` | Community-maintained site list (snapshot bundled; `update` fetches latest). |
| References | `tradecraft.md` (method, tiers, schema), `evidence-protocol.md` (capture + case-file schema), `setup.md` (plain-language prerequisites setup). |

## Setup / prerequisites

- **A browser tool (required for verification + evidence).** Either:
  - **Browser MCP extension** (recommended) — drives the analyst's own Chrome/Edge;
    fewer bot challenges, screenshots return inline, and they keep control of their
    tabs. Install from <https://browsermcp.io/install> and click **Connect**; or
  - **Playwright MCP** — a self-contained automated browser, as a fallback.

  Not sure if it's set up? Just ask Claude *"set up the tools"* — the **preflight**
  skill checks every prerequisite and walks you through it. Details:
  `skills/preflight/references/setup.md`.
- **Python 3.8+** — only needed for the triage engine and the report generator.
  Nothing to `pip install`.

To pull the full, current community site list:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/username-search/scripts/hunt.py" update
```

## Usage

Just ask Claude naturally — e.g. "find the username `johndoe` and capture
evidence", "what accounts does this handle have", "build me the OSINT report",
"verify the GitHub detection looks right", "can we add this site to the list".
Claude runs preflight, triages, browser-verifies the hits, captures screenshots,
and offers the report.

**At the end, you can ask for outputs** — Claude will remind you. Options:

- an **HTML evidence report** (the default deliverable);
- **CSV / JSON** of findings to pivot on;
- a **Word (.docx) or PDF** write-up.

Direct CLI (triage only):

```bash
ROOT="$CLAUDE_PLUGIN_ROOT/skills/username-search/scripts/hunt.py"
python3 "$ROOT" search johndoe --format json     # triage to a parseable list
python3 "$ROOT" verify --site GitHub             # self-heal check
python3 "$ROOT" list --names                     # show loaded sites
```

## The evidence report

`build_report.py` produces **one** HTML file with everything embedded — it opens
offline anywhere. Each finding shows the screenshot (click to enlarge), the
clickable URL, the UTC capture time, the method, and a **SHA-256** computed from
the file; the page **re-verifies** those hashes in-browser ("integrity verified").

It's also a triage surface: tick the evidence that's **relevant**, then **export
the subset** as CSV or as a JSON in this plugin's own case-file schema — which
round-trips straight back to Claude (there's a **"Copy for Claude"** button) or
into `build_report.py` to regenerate a tighter report. It prints / exports to PDF
cleanly with only the relevant items.

## Automation ideas

- Schedule `verify --all --format json` weekly and summarize broken sites.
- Monitor a handle: schedule a `search` and alert when it appears on new sites
  (impersonation / brand watch).

## Ethics

Public pages only; the tool never authenticates, bypasses logins, or defeats bot
challenges. Use it for lawful, authorized purposes — your own footprint, consented
investigations, security research, brand/impersonation monitoring. Do not use it
to stalk, harass, or locate private individuals. A `found` result is a lead, not
proof of identity.

When **add-site** onboards a new site, it uses only **throwaway/dedicated test
accounts** as detection oracles. Their credentials are kept in a local
`oracle-credentials.json` (outside the plugin, `chmod 600`, auto-`.gitignore`d) and
are never packaged, exported, or placed in any report. Never store a personal or
reused password there. See `NOTICE` for attribution and licensing.
