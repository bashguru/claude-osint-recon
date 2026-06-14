# Setup guide (getting the prerequisites ready, plain-language)

The plugin needs a few capabilities to work well. You don't have to memorize any of
this. Tell Claude *"set up the tools"* and it will walk you through, one step at a
time, and check that each worked.

## What you need

| Capability | Why | Easiest option |
| --- | --- | --- |
| **Browser MCP** | Verify accounts and capture **screenshot evidence** | Browser MCP **extension** (your own browser) |
| **Local execution** | Run the **triage** engine fast on your real connection | **Desktop Commander** (Claude drives it) or your **Terminal** |
| **Python 3.8+** | Runs the engine + report builder (no extra libraries) | Usually already installed on Mac/Linux |

You can set these up in any order. Claude re-checks after each.

---

## 1. Browser MCP

You only need **one** of these connected.

### Option A. Browser MCP extension (recommended)

A small extension that lets Claude drive **your** Chrome/Edge, your real browser,
with your logins. Sites challenge it less, screenshots come back cleanly, and you
keep control of your tabs.

1. Go to **https://browsermcp.io/install** and add the extension to Chrome/Edge.
2. Make sure the matching connector is enabled in **Claude's settings → Connectors
   / Capabilities** (technical name `@browsermcp/mcp`).
3. Click the **Browser MCP** toolbar icon and press **Connect** (people forget this;
   it does nothing until you connect the tab).
4. Leave that window open.

*Worked when:* Claude says *"Browser ready (Browser MCP extension)."* If it says
"not connected," click the icon and **Connect** again on a normal web page.

### Option B. Playwright (fallback, self-contained browser)

A browser Claude runs by itself. Use it if you can't install the extension. It's
added in **Claude's settings → Connectors / Capabilities**; the technical detail:
official Microsoft package **`@playwright/mcp`** (`npx @playwright/mcp@latest`),
needs **Node.js 18+**, and should run **headed (visible)** so you can solve any
human-check. Official page: https://github.com/microsoft/playwright-mcp

---

## 2. Local execution (for fast triage)

The triage engine checks hundreds of sites at once. It must run on **your**
connection; Claude's sandbox is network-limited and will miss most sites. Two ways:

### Option A. Desktop Commander (recommended; Claude runs it for you)

Desktop Commander lets Claude run commands on your computer (like the triage
engine) using your real internet, so a full search finishes in seconds.

1. In **Claude's settings → Connectors / Capabilities**, enable / install
   **Desktop Commander**. (Technical: it's the `@wonderwhy-er/desktop-commander`
   MCP server, which can also be added with `npx @wonderwhy-er/desktop-commander setup`,
   then restart Claude.)
2. Approve access when Claude asks.

*Worked when:* Claude says *"I can run triage on your machine."*

*Note:* Desktop Commander gives Claude terminal access to your computer. Only enable
it if you're comfortable with that; it asks for approval and you stay in control.
Official page: https://github.com/wonderwhy-er/DesktopCommanderMCP

### Option B. Your Terminal (no extra tools)

If you'd rather not connect Desktop Commander, Claude will hand you a **single
command** to paste into Terminal, e.g.:

```bash
python3 "<plugin>/skills/username-search/scripts/hunt.py" search USERNAME --format json
```

Run it, then paste the output back to Claude (or save it into your project folder).
Same result, you just run the one command yourself.

---

## 3. Python 3.8+

The engine and report builder are plain Python (**no `pip install` needed**).

- **Check:** `python3 --version` → needs **3.8 or newer**.
- **macOS:** usually already there (ships with 3.9+). If missing, install from
  <https://www.python.org/downloads/> or `brew install python`.
- **Linux:** `sudo apt install python3` (or your distro's package).

*Worked when:* `python3 --version` prints 3.8+.

---

## A note on human-checks (CAPTCHAs / "are you human")

Whichever browser you use, it must be **visible** so you can solve these. Claude
will **not** try to bypass them. By default it pauses, brings the window to the
front, and asks you to click through; once you confirm, it captures the evidence
and moves on. (For an unattended run you can instead have it just screenshot the
block as evidence and continue.) This keeps the work lawful and reliable.

## Sources

- Browser MCP. https://browsermcp.io/install
- Playwright MCP. https://github.com/microsoft/playwright-mcp
- Desktop Commander. https://github.com/wonderwhy-er/DesktopCommanderMCP
