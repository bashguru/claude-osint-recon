---
name: username-search
description: >
  This skill should be used when the user wants to find where a username exists
  across public websites and social networks (i.e. OSINT username enumeration).
  Trigger when the user says things like "find this username", "username search",
  "check if the username X is taken", "what accounts does X have", "map this
  person's digital footprint", "OSINT a username", "run something like Sherlock",
  "enumerate social media accounts", or asks to check a handle across many sites.
  Covers the browser-first workflow, capturing screenshot evidence, handling bot
  protection, choosing output, and interpreting results.
metadata:
  version: "0.4.0"
  author: "Claude OSINT Investigator"
---

# Username search (OSINT enumeration)

Find which public websites have an account for a given username, **and capture
court-ready screenshot evidence as you go**. This skill prefers a real browser
(driven by an MCP) over the Claude sandbox, so results reflect what a human
actually sees and every hit can be documented with a screenshot.

## Authorized-use gate (check first)

This tool only views publicly accessible pages, the same thing a person could
open in a browser. It is for legitimate purposes like checking your own footprint,
consented investigations, security research, brand/impersonation monitoring, and
similar lawful work.

Before running, make sure the request fits that frame. If the intent looks like
stalking, harassment, or locating a private individual against their interest,
decline and explain why. Do not pair these results with home addresses or other
data used to physically locate a person. When intent is unclear, ask one brief
clarifying question. Otherwise proceed. Username enumeration over public pages
is standard, lawful OSINT.

## Step 0. Preflight (always)

Before anything else, run the **preflight** skill to confirm prerequisites. You
need a browser MCP (extension first, then Playwright), a way to run triage on the
analyst's machine (Desktop Commander or their terminal, since the sandbox is
egress-limited), and Python 3.8+. It guides setup for anything missing. Tell the
analyst what's ready, then start.

## Step 0.5 (ask for an optional investigator name)

Right after preflight and before any searching, ask the analyst one short question.
Ask whether they want to record an investigator name for this case. Make clear that
this is optional. Do not assume who the investigator is and do not guess a name.

If they give a name, carry it into the case file `investigator` field so it appears
on the evidence report. If they decline or leave it blank, proceed normally and the
report simply shows "Not provided" in that field. Never block the investigation on
this answer.

The Claude sandbox is the **last** resort, not the default. Prefer, in order:

1. **Browser MCP, primary (do checking *and* evidence here).**
   Use the **browser-mcp extension** first. It's the analyst's own browser, so bot
   challenges are rarer, evidence matches what they see, screenshots come back
   inline, and they keep control of their tabs. Fall back to **playwright-mcp**
   only when the extension isn't connected. This is the only tier that produces
   screenshot evidence.
2. **Local CLI, secondary (fast triage, if accessible).** Run the bundled
   `hunt.py` engine on the **analyst's own machine** (e.g. via a Desktop Commander
   MCP or their terminal). Same real IP as their browser, so far fewer firewall
   blocks than the sandbox. Use it to *triage* hundreds of sites quickly.
3. **Claude sandbox, last resort.** Run `hunt.py` inside the sandbox only when
   no browser MCP and no local CLI are available. Its IP is often flagged, so
   expect more `waf`/blocked results. Never present sandbox results as final
   evidence. Re-verify hits in the browser before reporting.

### Triage-first is the hard default (don't browser-search for breadth)

You cannot, and must not, open a browser tab for all ~481 sites. Breadth always
runs on the concurrent triage engine; the browser only ever touches confirmed hits:

1. **Triage** the full list with `hunt.py` to get the short list of likely
   **`found`** sites, fast and concurrent. Prefer **Tier 2 (the analyst's
   machine)** for speed and a real IP; Tier 3 (sandbox) is a last resort and is
   often network-crippled.
2. **Browser-verify only the `found` hits** (plus any sites the analyst named),
   typically a handful. Confirm and capture evidence there.
3. Skip every not-found site. No browser tab, no evidence.

If triage isn't available (no local CLI, sandbox blocked), **say so and help the
analyst run `hunt.py` locally**. Do not fall back to slowly browsing hundreds of
pages by hand. Hand-browsing the catalog is the slow path and is not an acceptable
default.

## The per-site browser loop (lean + hygienic)

Only **confirmed triage hits** reach the browser. For each, one clean tab at a
time:

1. **Open** the profile URL (`mcp__browsermcp__browser_navigate` or
   `mcp__playwright__browser_navigate`).
2. **Decide existence from the lightest signal first**, the final URL and page
   **title** (plus, only if needed, one targeted "not found" text check). **Do not
   read or parse the whole page / accessibility tree**, that is the main time and
   context cost. Examples: a redirect to login/home or a "user not found" title →
   not-found; the real username in the title/heading → found.
3. **Screenshot only to capture evidence** for a confirmed hit (not to decide).
   Save to `evidence/<case-id>/<site>.png`; record the full URL, UTC time, tool,
   and title. (See the **evidence-report** skill for the metadata.)
4. **Close / navigate the single tab onward** before the next hit. Never leave
   tabs open or linger.
   - Browser-mcp extension: reuse the one controlled tab and navigate it onward.
   - Playwright (fallback): close the tab (`mcp__playwright__browser_tabs` /
     `browser_close`).

## Bot protection (pick a policy, never auto-bypass)

Claude does **not** programmatically solve or bypass CAPTCHAs or bot-detection;
defeating those protections is off-limits and unreliable. Instead, **ask the
analyst once at the start of a run** how challenges should be handled, then apply
it consistently:

- **Assisted (default for interactive runs).** When a challenge appears, surface
  it in the analyst's own browser and **pause** for them to solve it; on their
  confirmation, re-check and capture. **If they close the tab or skip**, record the
  finding as `waf` with the note "tab closed, not verified" and move on.
- **Automated / unattended (default for scheduled runs).** Don't wait.
  **Screenshot the challenge page** as evidence, record the finding as `waf` with
  the note "bot challenge, blocked, could not verify (captured for later review)",
  and continue. This keeps an unattended run moving and preserves the page so the
  analyst can revisit it.

Ask plainly, e.g. *"If a site throws a CAPTCHA/bot check, should I pause for you to
solve it, or skip it and just capture the block as evidence?"* Either way, a
challenged site is **never** a real negative. It is "could not verify."

## Resilience (closed tabs & lost pages)

The canonical run state (the candidate list and each site's status) lives in the
**case file**, not in the browser, so a closed or changed tab never loses
progress. After any pause or handoff:

- **Re-confirm the active tab is the URL you intended** (check the final URL/title)
  before trusting a capture.
- If the tab was **closed or drifted**, simply re-navigate to the intended URL.
- If it can't be recovered, mark the finding `waf` ("could not verify", with the
  reason) and continue. Never block the whole run on one site.

## Triage CLI reference (Tiers 2 to 3)

The engine lives at
`${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py` (run with
`python3`). Prefer running it on the analyst's machine (Tier 2); use the sandbox
(Tier 3) only as a last resort.

```bash
# Fast triage to a parseable list of candidates:
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" search johndoe --format json
```

Useful flags (run `hunt.py search --help` for all):

- `--format {console,json,csv,md}` for triage prefer `json` and parse it.
- `--site NAME` limits to one site (repeatable); great for targeted checks.
- `--include-all` also reports not-found/blocked/errored sites.
- `--nsfw` includes adult sites (excluded by default).
- `--timeout SECONDS` (default 30), `--max-workers N` (default 20),
  `--proxy URL`.
- Multiple usernames: `... search alice bob carol`.

**Speed (no agents needed):** `hunt.py` already checks sites concurrently
(`--max-workers`, default 20, raise to ~40 to 50 on a solid connection). That thread
pool is the right parallelism; the bottleneck is the network, already parallelized,
so a *team of Claude agents would be slower and costlier, not faster*. For very
large jobs (many usernames, or several proxies/regions at once) shard into parallel
`hunt.py` processes via Desktop Commander.

## Proxies, VPN & attribution (optional)

For attribution management, rate-limit avoidance, or geo-checks, route triage
through a proxy or VPN. **Ask the analyst whether they want this** for sensitive
work, and which endpoint:

- **HTTP/HTTPS or residential proxy:** pass `--proxy` to `hunt.py`, e.g.
  `--proxy "http://user:pass@host:port"`, and all checks route through it (residential
  endpoints are usually HTTP, so this works directly).
- **VPN:** system-level. If the analyst is on a VPN, triage on their machine and
  the browser already use it automatically; nothing to configure.
- **SOCKS5:** not supported by the dependency-free stdlib engine out of the box.
  Run behind a VPN/system route, use a local HTTP→SOCKS bridge, or ask to enable
  optional `pysocks` support.
- **Browser tier:** the browser-mcp extension follows the analyst's system/VPN and
  browser proxy settings; Playwright can be launched with a proxy.

Responsible use: proxies/VPNs are for legitimate attribution management and
geo/rate-limit handling on **public** pages, not for evading bans to abuse a
service. Respect each site's ToS and rate limits.

## Interpreting results

Each site resolves to one status: `found` (account exists, the hits to verify
and screenshot), `not_found` (no account; skip), `waf` (a firewall blocked the
probe, so the answer is unknown; say "could not verify", and a real browser often
gets through), `error` (network/timeout; retry), or `illegal` (the username
can't be valid there; skipped).

Lead with `found` accounts and their URLs. Treat a single `found` as a **lead, not
proof of identity**, since the same username can belong to different people on
different sites.

## Producing evidence and outputs

Once you've captured screenshots, use the **evidence-report** skill to assemble a
single, self-contained, court-ready **HTML evidence report** (findings + URLs +
embedded screenshots + SHA-256 hashes + capture timestamps).

**Be efficient and interactive.** Don't silently grind through 481 sites. Share
candidates early, confirm the high-value ones, and keep the analyst in the loop.
**At the end, tell the analyst they can ask for outputs**, for example:

- an **HTML evidence report** (the default deliverable; see evidence-report);
- a **CSV/JSON** of findings to pivot on;
- a **Word or PDF** report (feed the findings to the docx/pdf skills).

Let them choose; don't assume the format.

## Keeping coverage current and accurate

- The bundled manifest is a snapshot. To pull the latest community site list, run
  `hunt.py update` (prefer Tier 2 / the analyst's machine).
- Sites change how they respond, causing false positives/negatives. When results
  look wrong for a specific site, use the **site-healing** skill to diagnose and
  repair that site's detection rule.

## Deeper reference

For the full tradecraft, the execution tiers, the bot-detection notes, and the
manifest schema (needed when adding or repairing sites), read
`${CLAUDE_PLUGIN_ROOT}/skills/username-search/references/tradecraft.md`.
