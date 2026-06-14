# claude-osint-recon

A Claude plugin for **OSINT investigations**. Give Claude a **username or an email
address** and it finds where that identity exists across hundreds of public
websites, **confirms the real accounts in a browser, screenshots them, and builds a
court-ready evidence report**, all from plain-language requests, no coding required.
It can also check whether an identity appears in known infostealer-malware leaks.

The plugin lives in the [`username-recon/`](username-recon/) folder. This page is the
quick-start; the full details are in [`username-recon/README.md`](username-recon/README.md).

> **Use it lawfully.** Public pages only. It never logs in, never submits a
> password, and never bypasses security or "are you human" checks. Use it for your
> own digital footprint, consented investigations, security research, or
> brand/impersonation monitoring, never to stalk, harass, or locate someone. A match
> is a *lead*, not proof of identity.

---

## What you get

1. **Find by username.** Checks a handle against ~481 public sites and returns the
   likely accounts.
2. **Find by email.** Checks whether an email is registered across ~98 sites, using
   their public signup, validation, or login-check endpoints. Sites that could email
   the person ("loud") and adult sites are flagged and off by default.
3. **Verify and screenshot.** Opens each likely hit in a real browser so results
   match what a human sees, and captures a screenshot of every confirmed profile.
4. **Report.** Bundles everything into one self-contained HTML evidence report:
   embedded screenshots, full links, timestamps, and a tamper-check code (SHA-256)
   per image.
5. **Optional extras.** Run a **combined** investigation (username and email in one
   pass), and optionally check an identity against **infostealer-malware logs**
   (Hudson Rock, a third-party service, only with your go-ahead).

---

## The one thing to understand first: the search runs on *your* computer

Claude has its own cloud workspace, but that workspace is **blocked from opening
these websites** (it has no open internet access for the site checks). So the actual
checking has to run on **your** computer, using **your** internet connection. This is
not an extra feature, it is how the tool reaches the sites at all, and it also means
your real connection is far less likely to be blocked than a shared cloud one.

In practice that means one of these does the searching for you:

- **Desktop Commander** (recommended): Claude runs the search on your computer
  automatically, or
- **your Terminal**: Claude hands you a single command to paste, and you paste the
  result back.

Either way it takes seconds. The setup below walks you through it.

---

## Before you start (what you need)

You do not have to set these up by hand. The easiest path is to **install the
plugin, then ask Claude *"set up the tools"***. It checks each item below and walks
you through anything missing, one step at a time.

| What | Why it is needed | Required? |
| --- | --- | --- |
| **Claude with plugin support** (Cowork or Claude Code) | Runs the plugin | Required |
| **A browser connection** (Browser MCP extension *or* Playwright) | Confirms accounts and captures the screenshot evidence | Required for evidence |
| **A way to run the search on your own internet** (Desktop Commander *or* your Terminal) | This is what actually reaches the sites (see the note above) | Required for real results |
| **Python 3.8 or newer** | Powers the search engine and report builder (nothing extra to install) | Required, usually already on your Mac/Linux |

---

## Step 1. Install the plugin

**In Cowork (easiest):**

1. Download or open the plugin file [`username-recon.plugin`](username-recon.plugin).
2. Claude shows a **Save plugin / Install** button. Click it.
3. That is it. You can also manage it under **Settings → Capabilities**.

**In Claude Code:** add the `username-recon/` folder as a plugin, then talk to it the
same way.

After installing, just say **"set up the tools"** and let Claude check the rest.

---

## Step 2. Set up the prerequisites (plain-language walkthrough)

Set these up in any order; Claude re-checks after each. If you would rather just be
guided, say *"set up the tools"* and Claude does this with you, one step at a time.

### 2a. A browser connection (this is what captures evidence)

You only need **one** of these.

- **Browser MCP extension (recommended).** A small extension that lets Claude use
  *your* Chrome or Edge, with your normal logins. Fewer "are you human" checks, and
  screenshots come back cleanly.
  1. Install it from **https://browsermcp.io/install**.
  2. Turn on its connector in **Claude → Settings → Capabilities** (technical name
     `@browsermcp/mcp`).
  3. Click the **Browser MCP** toolbar icon and press **Connect** (it does nothing
     until you click Connect).
  4. Leave that browser window open.
  - *Working when* Claude says *"Browser ready (Browser MCP extension)."*

- **Playwright (fallback).** A self-contained browser Claude runs on its own. Add it
  in **Settings → Capabilities** (package `@playwright/mcp`; needs Node.js 18+). Run
  it *visible* so you can solve any human-checks. See
  https://github.com/microsoft/playwright-mcp

### 2b. A way to run the search on your own internet (this is what reaches the sites)

As explained above, the checking must run on your computer. Pick one:

- **Desktop Commander (recommended).** Lets Claude run the search on your computer
  for you, finishing in seconds. Enable **Desktop Commander** in **Settings →
  Capabilities** (package `@wonderwhy-er/desktop-commander`) and approve access when
  asked.
  *This gives Claude terminal access to your computer. Only enable it if you are
  comfortable with that; you stay in control and approve each action.*
- **Your Terminal (no extra tools).** Prefer not to connect anything? Claude hands
  you **one command** to paste into Terminal, then you paste the result back. Same
  outcome, you just run the one line yourself.

> If you skip this step, Claude can only try the search from its own cloud
> workspace, which is blocked from the internet and will find almost nothing. That
> is expected, it is not the tool failing. Connect Desktop Commander or run the one
> command locally and it works normally.

### 2c. Python 3.8+ (likely already installed)

The engine and report builder are plain Python with **nothing to `pip install`**.

- **Check it.** Open Terminal and run `python3 --version`; you want **3.8 or newer**.
- **Mac.** Usually already there. If not, see https://www.python.org/downloads/ or
  `brew install python`.
- **Linux.** Run `sudo apt install python3` (or your distro's equivalent).

---

## Step 3. Use it

Just ask Claude in plain language. For example:

- *"Find the username `johndoe` and capture evidence."*
- *"Where is the email `someone@example.com` registered?"*
- *"Run a full recon on this username and email."* (combined)
- *"Has this email shown up in any malware leaks?"* (infostealer, asks you first)
- *"Build me the OSINT report."*
- *"Does the GitHub detection still look right?"* (self-check)
- *"Can we add this site to the list?"*

Claude runs the prerequisite check, does the search on your machine, confirms the
hits in the browser, screenshots them, and offers you a report.

**At the end, ask for the output you want:**

- an **HTML evidence report** (the default, opens offline anywhere),
- **CSV / JSON** of the findings, or
- a **Word (.docx) or PDF** write-up.

### A note on email checks

Email checks read public "is this email already registered" signals on signup pages.
Some sites would **email the person** if probed (a reset or finish-signup message).
Those are treated as **loud** and are **skipped by default** so the subject is not
tipped off; you can opt in if you have a lawful reason.

### A note on the infostealer check

The infostealer lookup sends the identifier to **Hudson Rock**, a third-party
service that may log the query. Claude always **asks first** and shows a privacy
notice before doing it. It is off unless you ask for it.

### A note on "are you human" checks (CAPTCHAs)

Your browser stays visible so you can solve these yourself. Claude will **never** try
to bypass them. It pauses, brings the window forward, and asks you to click through;
once you confirm, it captures the evidence and continues. This keeps everything
lawful and reliable.

---

## What's in this repository

| Path | What it is |
| --- | --- |
| [`username-recon/`](username-recon/) | The plugin itself (skills, engine, site lists, docs). |
| [`username-recon/README.md`](username-recon/README.md) | Full overview and usage. |
| [`username-recon/HANDOFF.md`](username-recon/HANDOFF.md) | Team handoff / quick reference. |
| `username-recon.plugin` | The installable plugin bundle. |
| `data.json` | The community-maintained username site list (snapshot). |
| `NOTICE` | Attribution and licensing. |

### The skills inside

**preflight** (check/set up prerequisites), **username-search** (find accounts by
handle), **email-search** (find accounts by email), **recon** (both at once, plus
optional infostealer), **evidence-report** (capture + build the HTML report),
**site-healing** (keep detection accurate), and **add-site** (teach it a new site).

---

## License

MIT. The username site list derives from the MIT-licensed
[Sherlock](https://github.com/sherlock-project/sherlock) project; the email and
infostealer tradecraft is informed by the MIT-licensed
[user-scanner](https://github.com/kaifcodec/user-scanner) project. See
[`username-recon/NOTICE`](username-recon/NOTICE) for attribution.
