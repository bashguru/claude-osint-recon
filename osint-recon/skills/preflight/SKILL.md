---
name: preflight
description: >
  This skill should be used to verify the plugin's prerequisites are connected
  BEFORE running a username search, evidence capture, or site onboarding, and to
  help a non-technical analyst set up anything missing. Trigger on phrases like
  "check prerequisites", "is everything ready", "set up the tools", "why can't you
  open the page", "the browser isn't working", "connect Playwright", "connect
  Desktop Commander", "run it on my machine", or automatically as step 0 of any
  osint-recon run. Checks three capabilities (the Playwright browser MCP for
  evidence, local execution for fast triage via Desktop Commander or terminal, and
  Python 3.8+) and walks through configuring each.
metadata:
  version: "0.4.0"
  author: "Claude OSINT Investigator"
---

# Preflight (check prerequisites & set up missing tools)

Run this **first**, automatically, at the start of any osint-recon run. It
confirms the plugin can actually do its job on *this* machine, and if something is
missing it explains setup in plain language (written for non-technical analysts).
Never start a search before preflight passes for what that run needs.

## The three capabilities

| # | Capability | What it's for | Provided by |
| - | ---------- | ------------- | ------------------------------ |
| 1 | **Playwright MCP** | Verify hits + capture **screenshot evidence** | **Playwright MCP** (required; run it visible so you can solve human-checks) |
| 2 | **Local execution** | Fast **triage** of hundreds of sites on the analyst's real connection | **Desktop Commander** → the analyst's terminal / Claude Code → (sandbox = degraded) |
| 3 | **Python 3.8+** | Runs `hunt.py` and `build_report.py` (dependency-free) | Already on most macOS/Linux; installable |

Here is why local execution matters. The **Claude sandbox's network egress is allowlisted**,
so triage there is crippled (in testing it reached ~2 of 462 sites). The *same*
triage on the analyst's machine reaches everything in seconds. So breadth must run
locally. Desktop Commander lets Claude drive it directly; otherwise the analyst
runs one command in their terminal.

## Run the checks (do this; don't quiz the analyst)

1. **Browser (Playwright MCP, required).** Try `mcp__playwright__browser_navigate`
   to `about:blank`. If it responds → ready ("Playwright ready"). If it does not
   respond → Playwright is **missing**; this plugin requires it for verification and
   screenshots, so walk the analyst through setup before any capture.
2. **Local execution.** Try a harmless Desktop Commander call, e.g.
   `start_process("echo ok")`. If it runs → ready ("can run triage on your
   machine"). If Desktop Commander isn't connected → **missing** (the analyst can
   still run `hunt.py` in their own terminal; the sandbox is a last-resort,
   crippled fallback).
3. **Python.** If local execution is available, run `python3 --version` there and
   confirm **≥ 3.8**. (macOS/Linux usually ship it.)

## Report a readiness summary

Give the analyst a short, honest summary of what's ready, what each missing piece
blocks, and how to fix it. For example:

> Playwright ✅ · Desktop Commander ✅ · Python 3.9 ✅. All set.

or

> Browser ✅ · Local execution ❌ (triage will be limited until Desktop Commander
> is connected or you run one command in Terminal) · Python ✅.

For **anything missing or disabled**, walk the analyst through setup one step at a
time, using
`${CLAUDE_PLUGIN_ROOT}/skills/preflight/references/setup.md`, then **re-run the
check** to confirm. Don't assume.

## Degraded modes (be explicit about the trade-off)

- **No Playwright** → you can still triage and report *findings + URLs*, but you
  **cannot capture screenshot evidence**. Offer to set up Playwright (it is required
  for verification and evidence).
- **No local execution** → triage falls back to the sandbox, which is
  **egress-limited and will miss most sites**. Say so plainly and offer Desktop
  Commander or a one-line terminal run before relying on those results.
- **No Python** → the engine and report generator can't run; help install it.

## After preflight

Tell the analyst which tools are ready in one line, then hand back to the calling
skill, whether **username-search**, **evidence-report**, or **add-site**. If they only
asked to "check" or "set up" prerequisites, confirm the result and let them know
they can now start a search or build a report.
