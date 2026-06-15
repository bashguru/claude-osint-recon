# osint-recon

OSINT **investigation** as a Claude plugin. Find where a **username or an email**
exists across hundreds of public websites, **trace stolen or suspicious Bitcoin to a
cash-out point**, and pull **historical flight records** for an aircraft, then
**verify hits in a real browser and capture court-ready screenshot evidence**, with a
**self-healing** capability that keeps detection accurate as sites change and an
optional **infostealer-leak** check. Every workflow feeds one self-contained HTML
evidence report.

It is a clean-room, dependency-free re-implementation of the
[Sherlock](https://github.com/sherlock-project/sherlock) username tradecraft,
extended with email and infostealer tradecraft informed by the
[user-scanner](https://github.com/kaifcodec/user-scanner) project, **Bitcoin
attribution and tracing** on the public
[WalletExplorer](https://www.walletexplorer.com/) API, and ADS-B Exchange flight
OSINT, all wrapped in a browser-first evidence workflow built for OSINT analysts
(including non-technical ones).

## What it does

1. **Triage by username** across ~481 sites with a dependency-free engine
   (`hunt.py`) to get the short list of likely accounts.
2. **Triage by email** across public signup/validation endpoints to find where an
   email is registered (logged out, no password ever submitted).
3. **Trace Bitcoin** with a dependency-free engine (`wxtrace.py`): attribute an
   address or transaction to a known service, follow the funds forward through
   intermediary wallets to a **cash-out point** (an exchange where a KYC subpoena can
   unmask identity), and flag mixers and peel chains along the way.
4. **Verify in a real browser** (Playwright MCP, the required browser), so results
   reflect what a human actually sees, and **capture a screenshot** of each
   confirmed profile or attributed wallet page.
5. **Report.** Assemble the findings into a single, self-contained, court-ready
   **HTML evidence report** with embedded screenshots, full URLs, UTC capture times,
   and a SHA-256 hash per screenshot.
6. **Combined recon and infostealer (optional).** Investigate a username and email
   together in one pass, and optionally check either against Hudson Rock's
   infostealer-log API (third-party, only with your consent).

Triage and Bitcoin tracing run on the **analyst's machine**; the Claude sandbox
cannot reach the sites or the WalletExplorer API (its network egress is blocked), so
the sandbox is a degraded last resort only (see Execution tiers).

## Execution tiers (browser-first)

| Tier | Tool | Role |
| --- | --- | --- |
| 1 (primary) | **Playwright MCP** (required; run it visible) | Verify accounts and capture screenshot evidence. Only tier that produces evidence. |
| 2 (secondary) | **Local CLI** (`hunt.py` on the analyst's machine) | Fast bulk triage with the analyst's real IP (far fewer firewall blocks). |
| 3 (last resort) | **Claude sandbox** (`hunt.py` in-sandbox) | Triage only when no browser/local CLI is available; flagged IP means more blocks. |

**Triage first.** Breadth runs on the concurrent `hunt.py` engine; the browser only
verifies and screenshots the handful of confirmed hits (decided from URL + title).
On **bot challenges** the plugin never auto-bypasses. You pick a policy per run,
either **assisted** (you solve it in your browser) or **automated** (screenshot the
block as evidence and move on). Pages are worked one at a time and closed after
capture; closing a tab never loses progress (state lives in the case file).

## Components

| Component | Purpose |
| --- | --- |
| Skill: **preflight** | Check all prerequisites (Playwright, local execution for triage, Python) and walk a non-technical analyst through setting up anything missing. Runs first. |
| Skill: **username-search** | Triage by username, browser-verify, capture evidence, choose output, interpret results. |
| Skill: **email-search** | Triage by email against public signup/validation endpoints (logged out); same verify + evidence flow. Loud (notifying) sites skipped by default. |
| Skill: **recon** | Combined investigation: runs username-search and email-search together, cross-references them, optional infostealer, one report. Orchestration only. |
| Skill: **crypto-trace** | Bitcoin only. Attribute an address or transaction, forward-trace the flow of funds to a cash-out, detect peel chains and mixers, and feed the findings into the evidence report. The on-chain to off-chain bridge: an address found by username/email search seeds a trace, and the cash-out exchange is the KYC subpoena target. |
| Skill: **evidence-report** | Capture protocol + build the court-ready HTML report. |
| Skill: **site-healing** | Diagnose false positives/negatives and repair the manifest (username or email). |
| Skill: **add-site** | Assess whether a new site is a valid candidate, derive its detection rule (logged-out, using a throwaway account/email as the oracle), verify it, and store the throwaway oracle credentials locally for reuse. |
| Skill: **adsbexchange-analyst** | Pull historical flight records for a specific aircraft from ADS-B Exchange (free globe map by default), capture court-ready snapshot evidence, export the KML 3D flight path, and stand up a scheduled monitor that alerts on a condition (live API). Self-heals its own selector and endpoint map. |
| Engine: `hunt.py` | Dependency-free CLI: `search`, `email`, `infostealer`, `verify` (`--email`), `update`, `list`. Shared request strategy (modern UA + headers, retries, optional `--rotate-ua`/`--delay`/`--proxy-file`) and one classifier. |
| Engine: `wxtrace.py` | Dependency-free Bitcoin CLI on the WalletExplorer API: `lookup`, `tx`, `address`, `wallet`, `wallet-addresses`, `trace`. Polite single-host client (serial, fixed `--delay`, exponential backoff on 429/5xx, global `--max-requests` cap). Forward trace with depth/node/dust guards, peel-chain and mixer detection, and `--graph` (mermaid/dot). |
| Generator: `build_report.py` | Dependency-free: turns findings + screenshots into one self-contained HTML report. Crypto findings map straight into its case-file schema. |
| Manifest: `data/data.json` | Community-maintained username site list (snapshot bundled; `update` fetches latest, preserving locally added sites). |
| Manifest: `data/email_data.json` | ~98 email sites across 18 categories (ported from the MIT-licensed user-scanner; loud and NSFW sites flagged and off by default; grow with add-site). |
| References | `username-search/.../tradecraft.md` (method, tiers, schema), `crypto-trace/.../tradecraft.md` (WalletExplorer API, category map, trace tuning, evidence recipe), `evidence-protocol.md` (capture + case-file schema), `setup.md` (plain-language prerequisites setup). |

## Setup / prerequisites

- **Playwright MCP (required for verification + evidence).** A self-contained
  automated browser Claude drives itself, and the only browser path. Add it in
  **Settings → Capabilities** (`@playwright/mcp`, needs Node.js 18+) and run it
  visible so you can solve any human-check.

  Not sure if it's set up? Just ask Claude *"set up the tools"*. The **preflight**
  skill checks every prerequisite and walks you through it. See
  `skills/preflight/references/setup.md`.
- **Python 3.8+** is only needed for the triage engine and the report generator.
  Nothing to `pip install`.

To pull the full, current community site list:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/skills/username-search/scripts/hunt.py" update
```

## Usage

Just ask Claude naturally, e.g. "find the username `johndoe` and capture
evidence", "where is `jane@example.com` registered", "trace this bitcoin address",
"where did these funds go", "whose wallet is this", "run a full recon on this
username and email", "has this email shown up in malware leaks", "build me the OSINT
report", "verify the GitHub detection looks right", "can we add this site to the
list". Claude runs preflight, triages on your machine, browser-verifies the hits,
captures screenshots, and offers the report.

**At the end, you can ask for outputs** and Claude will remind you. Options:

- an **HTML evidence report** (the default deliverable);
- **CSV / JSON** of findings to pivot on;
- a **Word (.docx) or PDF** write-up.

Direct CLI (triage only; run on your machine):

```bash
ROOT="$CLAUDE_PLUGIN_ROOT/skills/username-search/scripts/hunt.py"
python3 "$ROOT" search johndoe --format json            # username triage
python3 "$ROOT" email jane@example.com --format json    # email triage (loud sites off)
python3 "$ROOT" infostealer johndoe --confirm           # third-party leak check (asks consent)
python3 "$ROOT" verify --site GitHub                    # self-heal check (add --email for email sites)
python3 "$ROOT" search alice --permute "alice[0-9]{0-2}" # opt-in handle variations
python3 "$ROOT" list --names                            # show loaded sites
```

Bitcoin tracing (also triage only; run on your machine):

```bash
WX="$CLAUDE_PLUGIN_ROOT/skills/crypto-trace/scripts/wxtrace.py"
python3 "$WX" lookup 16SbwNa22nBwhLtg6HzWVYFQiUxtNzAUpt        # attribute an address
python3 "$WX" tx 99fd988b...3ba7 --format json                # read one transaction
python3 "$WX" trace --txid 99fd988b...3ba7 --graph mermaid    # follow the money forward
python3 "$WX" trace --address 1KT9...Z5L --max-depth 12       # trace from an address
python3 "$WX" wallet Bitstamp.net --count 100                 # a cluster's transactions
```

## Bitcoin tracing (crypto-trace)

Start from a known address or transaction and follow the funds **forward** to a
cash-out. The engine attributes every hop against WalletExplorer's wallet
clustering, classifies each service (exchange, mixer, market, gambling, pool,
service), and stops at the first known service by default, because past an exchange
the coins commingle and the chain is no longer clean. It flags **peel chains** and
**mixer hops**, and every node and endpoint carries its WalletExplorer URL so the
evidence step can screenshot it.

This is the **on-chain to off-chain bridge**. A Bitcoin address surfaced by
username or email search (in a forum post, a profile, or breach data) seeds a
trace; the cash-out **exchange** the trace reaches is the off-chain pivot, a KYC
subpoena target that can tie the chain back to a person. Crypto findings map
straight into the evidence-report case-file schema, so the deliverable is the same
court-ready HTML.

It is Bitcoin only (WalletExplorer is a BTC explorer) and a free first pass, the
baseline an analyst runs before paying for a commercial platform. **Attribution is
a lead with a stated confidence, not proof of who controls a wallet.** Identity
comes from lawful off-chain data. The deep reference (API schema, category map,
trace tuning, the evidence recipe) is in
`skills/crypto-trace/references/tradecraft.md`.

## The evidence report

`build_report.py` produces **one** HTML file with everything embedded, and it opens
offline anywhere. Each finding shows the screenshot (click to enlarge), the
clickable URL, the UTC capture time, the method, and a **SHA-256** computed from
the file; the page **re-verifies** those hashes in-browser ("integrity verified").

It's also a triage surface. Tick the evidence that's **relevant**, then **export
the subset** as CSV or as a JSON in this plugin's own case-file schema, which
round-trips straight back to Claude (there's a **"Copy for Claude"** button) or
into `build_report.py` to regenerate a tighter report. It prints / exports to PDF
cleanly with only the relevant items.

## Automation ideas

- Schedule `verify --all --format json` weekly and summarize broken sites.
- Monitor a handle: schedule a `search` and alert when it appears on new sites
  (impersonation / brand watch).
- Re-trace a known ransom or theft address on a schedule and alert when funds move
  to a new exchange (a fresh cash-out / subpoena target).

## Ethics

Public pages only; the tool never authenticates, bypasses logins, or defeats bot
challenges. Crypto tracing reads the **public ledger**, the same data anyone sees on
a block explorer, through a polite single-host client that respects rate limits. Use
the plugin for lawful, authorized purposes such as your own footprint, consented
investigations, security research, brand/impersonation monitoring, and tracing stolen
or defrauded funds, ransomware and incident response, or sanctions and compliance
screening. Do not use it to stalk, harass, dox, or locate private individuals. A
`found` account is a lead, not proof of identity, and an on-chain **attribution is a
lead with a stated confidence, not proof** of who controls a wallet; identity comes
from lawful off-chain data such as a KYC subpoena.

When **add-site** onboards a new site, it uses only **throwaway/dedicated test
accounts** as detection oracles. Their credentials are kept in a local
`oracle-credentials.json` (outside the plugin, `chmod 600`, auto-`.gitignore`d) and
are never packaged, exported, or placed in any report. Never store a personal or
reused password there. See `NOTICE` for attribution and licensing.
