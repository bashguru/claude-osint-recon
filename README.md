# claude-osint-recon

A Claude plugin for **OSINT username investigations**. Give Claude a username and it
finds where that handle exists across hundreds of public websites, **confirms each
real account in a browser, screenshots it, and builds a court-ready evidence
report** — all from plain-language requests, no coding required.

The plugin lives in the [`username-recon/`](username-recon/) folder. This page is the
quick-start; the full details are in [`username-recon/README.md`](username-recon/README.md).

> **Use it lawfully.** Public pages only. It never logs in, never bypasses security
> or "are you human" checks. Use it for your own digital footprint, consented
> investigations, security research, or brand/impersonation monitoring — never to
> stalk or harass. A match is a *lead*, not proof of identity.

---

## What you get

1. **Find** — checks a username against ~481 public sites and returns the likely accounts.
2. **Verify & screenshot** — opens each likely hit in a real browser so results match
   what a human sees, and captures a screenshot of each confirmed profile.
3. **Report** — bundles everything into a single self-contained HTML evidence report:
   embedded screenshots, full links, timestamps, and a tamper-check code (SHA-256) per image.

---

## Before you start — what you need

You don't have to set these up by hand. The easiest path is to **install the plugin,
then ask Claude *"set up the tools"*** — it checks each item below and walks you
through anything missing, one step at a time.

| What | Why it's needed | Required? |
| --- | --- | --- |
| **Claude with plugin support** (Cowork or Claude Code) | Runs the plugin | Required |
| **A browser connection** (Browser MCP extension *or* Playwright) | Confirms accounts and captures the screenshot evidence | Required |
| **A way to run the search on your own internet** (Desktop Commander *or* your Terminal) | Makes the search fast and accurate — your real connection isn't blocked like a shared one | Strongly recommended |
| **Python 3.8 or newer** | Powers the search engine and report builder (nothing extra to install) | Required, usually already on your Mac/Linux |

---

## Step 1 — Install the plugin

**In Cowork (easiest):**

1. Download or open the plugin file [`username-recon.plugin`](username-recon.plugin).
2. Claude shows a **Save plugin / Install** button — click it.
3. That's it. You can also manage it under **Settings → Capabilities**.

**In Claude Code:** add the `username-recon/` folder as a plugin, then talk to it the
same way.

After installing, just say: **"set up the tools"** — and let Claude check the rest.

---

## Step 2 — Configure the prerequisites

Set these up in any order; Claude re-checks after each. If you'd rather just be guided,
say *"set up the tools"* and skip ahead.

### A browser connection (required — this is what captures evidence)

You only need **one** of these.

- **Browser MCP extension — recommended.** A small extension that lets Claude use
  *your* Chrome or Edge (with your normal logins). Fewer "are you human" checks, and
  screenshots come back cleanly.
  1. Install it from **https://browsermcp.io/install**.
  2. Turn on its connector in **Claude → Settings → Capabilities** (technical name `@browsermcp/mcp`).
  3. Click the **Browser MCP** toolbar icon and press **Connect** — it does nothing until you click Connect.
  4. Leave that browser window open.
  - *Working when:* Claude says *"Browser ready (Browser MCP extension)."*

- **Playwright — fallback.** A self-contained browser Claude runs on its own. Add it
  in **Settings → Capabilities** (package `@playwright/mcp`; needs Node.js 18+). Run it
  *visible* so you can solve any human-checks. Details: https://github.com/microsoft/playwright-mcp

### A way to run the search on your own internet (strongly recommended)

The search checks hundreds of sites at once and works best on **your** connection.

- **Desktop Commander — recommended.** Lets Claude run the search on your computer for
  you, finishing in seconds. Enable **Desktop Commander** in **Settings → Capabilities**
  (package `@wonderwhy-er/desktop-commander`) and approve access when asked.
  *This gives Claude terminal access to your computer — only enable it if you're
  comfortable with that; you stay in control and approve each action.*
- **Your Terminal — no extra tools.** Prefer not to connect anything? Claude hands you
  **one command** to paste into Terminal, then you paste the result back. Same outcome.

### Python 3.8+ (required — likely already installed)

The engine and report builder are plain Python with **nothing to `pip install`**.

- **Check it:** open Terminal and run `python3 --version` — you want **3.8 or newer**.
- **Mac:** usually already there. If not: https://www.python.org/downloads/ or `brew install python`.
- **Linux:** `sudo apt install python3` (or your distro's equivalent).

---

## Step 3 — Use it

Just ask Claude in plain language. For example:

- *"Find the username `johndoe` and capture evidence."*
- *"What accounts does this handle have?"*
- *"Build me the OSINT report."*
- *"Does the GitHub detection still look right?"* (self-check)
- *"Can we add this site to the list?"*

Claude runs the prerequisite check, does the search, confirms the hits in the browser,
screenshots them, and offers you a report.

**At the end, ask for the output you want:**

- an **HTML evidence report** (the default — opens offline anywhere),
- **CSV / JSON** of the findings, or
- a **Word (.docx) or PDF** write-up.

### A note on "are you human" checks (CAPTCHAs)

Your browser stays visible so you can solve these yourself. Claude will **never** try
to bypass them — it pauses, brings the window forward, and asks you to click through;
once you confirm, it captures the evidence and continues. This keeps everything lawful
and reliable.

---

## What's in this repository

| Path | What it is |
| --- | --- |
| [`username-recon/`](username-recon/) | The plugin itself (skills, engine, site list, docs). |
| [`username-recon/README.md`](username-recon/README.md) | Full overview and usage. |
| [`username-recon/HANDOFF.md`](username-recon/HANDOFF.md) | Team handoff / quick reference. |
| `username-recon.plugin` | The installable plugin bundle. |
| `data.json` | The community-maintained site list (snapshot). |
| `NOTICE` | Attribution and licensing. |

---

## License

MIT. The site list derives from the MIT-licensed
[Sherlock](https://github.com/sherlock-project/sherlock) project — see
[`username-recon/NOTICE`](username-recon/NOTICE) for attribution.
