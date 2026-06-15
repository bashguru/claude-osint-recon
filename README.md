# claude-osint-recon

A Claude plugin for **OSINT investigations** that anyone can run by typing in plain
English, no coding required. Give Claude a **username** or an **email address** and
it finds where that identity exists across hundreds of public websites, confirms the
real accounts in a web browser, takes a screenshot of each one, and assembles
everything into a single, court-ready evidence report. It can also check, with your
permission, whether an identity shows up in known infostealer-malware leaks.

It also tracks **aircraft**. Give it a flight number or a tail number and it pulls an
aircraft's flight history from ADS-B Exchange (the public flight-tracking service),
captures the same court-ready evidence, exports the 3D flight path, and can even watch
a plane and alert you when it meets a condition.

The plugin itself lives in the [`osint-recon/`](osint-recon/) folder. This page
is the friendly guide. A shorter technical overview is in
[`osint-recon/README.md`](osint-recon/README.md).

> **Use it lawfully.** This tool only looks at pages and signals that are already
> public. It never logs into anyone's account, never uses a real password, and never
> defeats a security or "are you human" check. Use it for your own digital footprint,
> investigations you are authorized to run, security research, or
> brand and impersonation monitoring. Do not use it to stalk, harass, or physically
> locate a person. A match is a **lead, not proof of identity**: the same handle or
> email can belong to different people, or be reused, recycled, or shared. A
> **flight track** is likewise a lead and a record of a public radio broadcast, not
> proof of who was on board.

---

## What it does, in plain terms

1. **Find accounts by username.** Checks a handle (for example `johndoe`) against
   roughly **481 public sites** and returns the ones that look like real accounts.
2. **Find accounts by email.** Checks an email address against roughly **98 sites**
   using their public "is this email already registered" signals. Sites that might
   email the person, and adult sites, are turned off unless you opt in.
3. **Confirm and screenshot.** Opens each likely hit in a real browser so the result
   matches what a human would see, and captures a screenshot of every confirmed page.
4. **Report.** Bundles the findings into one self-contained HTML file with the
   screenshots, the links, the timestamps, and a tamper-check code for each image.
5. **Optional extras.** Investigate a username and an email together in one pass, and
   optionally check an identity against infostealer-malware leak data (a third-party
   service, only when you say yes).
6. **Track aircraft.** Give a tail number, flight number, or hex code and it pulls an
   aircraft's flight history from ADS-B Exchange, captures the same evidence, exports
   the KML 3D flight path, or watches the aircraft and alerts you on a condition (see
   *Tracking aircraft with ADS-B Exchange* below).

### Three ways to search

You investigate from whatever identity you have. Ask for one, the other, or both:

- **Username only**: *"find the username jsmith"*
- **Email only**: *"check where jsmith@example.com is registered"*
- **Both together**: *"run a recon on the username jsmith and the email
  jsmith@example.com"* (cross-references the two and produces a single report)

---

## What it actually checks, and what the answers mean

For a **username**, it asks each site the simple question "does a public profile
exist at this address?" (for example `github.com/johndoe`). For an **email**, it
asks each site's public signup or sign-in page "is this email already in use here?"
It never tries to log in.

Each site comes back with one of these answers:

| Answer | Meaning |
| --- | --- |
| **found** / **registered** | An account appears to exist. This is a lead worth confirming and documenting. |
| **not found** / **not registered** | No account was detected there. |
| **unknown** (shown as `waf`) | A site blocked or challenged the check, so the answer could not be trusted. It is not a "no." A real browser often gets through. |
| **error** | A network or timeout problem. Worth retrying. |
| **illegal / skipped** | The username or email cannot be valid on that site (so it was skipped), or the site was skipped because it could notify the person (see "loud" below). |

The sites span many categories: social networks, developer and code platforms,
forums and communities, gaming, creators, shopping, music, news, and more. The
username list comes from the well-known open-source Sherlock project; the email list
was adapted from the open-source user-scanner project.

---

## The most important setup fact: the search runs on *your* computer

Claude has its own cloud workspace, but that workspace is **blocked from opening
these websites**. It has no open internet access for the site checks. So the actual
checking has to run on **your** computer, over **your** internet connection. This is
not an optional nicety, it is how the tool reaches the sites at all. A nice side
effect is that your real connection is far less likely to be blocked than a shared
cloud one.

In practice, one of these does the searching for you:

- **Desktop Commander** (recommended): Claude runs the search on your machine for you.
- **Your Terminal**: Claude hands you a single command to paste, and you paste the
  result back.

Either way it takes seconds. If you skip this step, Claude can only try from its
blocked cloud workspace and will find almost nothing. That is expected, not a bug.

---

## What you need

You do not have to set these up by hand. The easy path is to install the plugin and
then ask Claude **"set up the tools"**. It checks each item and walks you through
anything missing, one step at a time.

| What | Why it is needed | Required? |
| --- | --- | --- |
| **Claude with plugin support** (Cowork or Claude Code) | Runs the plugin | Required |
| **Playwright MCP** (a self-contained browser Claude drives) | Confirms accounts and captures the screenshots | Required to capture evidence |
| **A way to run the search on your own internet** (Desktop Commander *or* your Terminal) | Actually reaches the sites (see the note above) | Required for real results |
| **Python 3.8 or newer** | Runs the search engine and report builder (nothing extra to install) | Required, usually already on Mac/Linux |

---

## Setup, step by step

### Step 1. Install the plugin

**In Cowork (easiest):** open the [`osint-recon.plugin`](osint-recon.plugin)
file in Claude and click **Save plugin / Install**. You can also manage it under
**Settings → Capabilities**.

**In Claude Code:** add the `osint-recon/` folder as a plugin.

Then just say **"set up the tools"** and let Claude check the rest.

### Step 2. Playwright (the browser that captures evidence)

This plugin uses **Playwright MCP**, a self-contained browser that Claude drives
itself. It is required and is the only browser path (it has proven the most
consistent for screenshots).

- Add **Playwright MCP** in **Settings → Capabilities** (technical name
  `@playwright/mcp`, needs Node.js 18+).
- Run it **visible** so you can watch the pages and solve any "are you human" check.

### Step 3. A way to run on your own internet (reaches the sites)

- **Desktop Commander (recommended).** Enable it in **Settings → Capabilities**
  (`@wonderwhy-er/desktop-commander`) and approve access. This gives Claude terminal
  access to your computer; you stay in control and approve each action.
- **Your Terminal.** Prefer not to connect anything? Claude gives you one command to
  paste and you paste the result back.

### Step 4. Python 3.8+ (usually already there)

Check with `python3 --version` in a terminal. On Mac it is usually preinstalled; if
not, install from https://www.python.org/downloads/ or with `brew install python`.
On Linux use your package manager. There is nothing to `pip install`.

---

## The skills, and how to ask for each

A "skill" is just a capability the plugin knows how to do. You never call them by
name; you ask in plain language and Claude picks the right one. There are eight.

| Skill | What it is for | Say something like |
| --- | --- | --- |
| **preflight** | Checks and helps set up the prerequisites. Runs first, automatically. | *"set up the tools"*, *"is everything ready?"* |
| **username-search** | Finds where a username has accounts and confirms the real ones. | *"find the username johndoe"*, *"what accounts does this handle have?"* |
| **email-search** | Finds where an email is registered. | *"where is jane@example.com registered?"* |
| **recon** | Runs username and email together, plus an optional leak check, into one report. | *"run a full recon on this username and email"* |
| **evidence-report** | Captures the screenshots and builds the court-ready HTML report. | *"build me the evidence report"*, *"I'd like the output now"* |
| **site-healing** | Checks that detection for a site is still accurate, and fixes it if a site changed. | *"does the GitHub detection still look right?"*, *"this result looks wrong"* |
| **add-site** | Teaches the tool a brand-new site to check. | *"can we add this site to the list?"* |
| **adsbexchange-analyst** | Pulls an aircraft's flight history from ADS-B Exchange, captures evidence, exports the KML flight path, and can watch a plane and alert you. | *"where did tail N76528 go after leaving Austin?"*, *"watch this plane and tell me when it's within 100 miles of KAUS"* |

The optional **infostealer leak check** (Hudson Rock) is requested the same way:
*"has this email shown up in any malware leaks?"* Claude shows a privacy notice and
asks before sending anything to that third-party service.

---

## Tracking aircraft with ADS-B Exchange

The newest skill, **adsbexchange-analyst**, brings the same plain-language,
evidence-first approach to aircraft. You can give Claude any one of these, and it will
explain which is which if you are not sure:

- a **flight number** (like UAL2177, the airline and number for a scheduled flight),
- a **tail number** (like N76528, the registration painted on the aircraft), or
- a **hex code** (like A4400F, the aircraft's unique radio id).

It does four things, and it asks one easy question at a time so you are never left
guessing:

- **See where a flight went in the past.** *"Where did tail N76528 go after leaving
  Austin on the 14th?"* You can give **any specific historical date** (a normal local
  date is fine, Claude converts it to UTC, a single world clock, for you). Claude pulls
  that day's track on the free public map, steps to the leg that departed the airport,
  and shows you what it found, with no account needed. How far back the free map
  reaches depends on ADS-B Exchange's data retention; for older history there is an
  opt-in archive Claude can set up.
- **See where an aircraft is right now.** *"Where is N76528 right now?"* This uses the
  live data service (see the cost note below).
- **Get the 3D flight path.** Ask for the **KML** file, a file you open in Google
  Earth to fly along the route, and Claude saves it next to your evidence.
- **Watch an aircraft and get an alert.** *"Watch N76528 and tell me when it gets
  within 100 miles of KAUS, check every 5 minutes."* Claude sets up a scheduled check
  that alerts you the first time the condition is met.

**Evidence works the same way.** For a past flight, Claude captures a court-ready
screenshot of exactly what was on screen, with the full link, the UTC time, and a
tamper-check code, in the same HTML report as the rest of the plugin. It always
confirms with you before saving photos or downloading a file, so nothing happens by
surprise.

**Free vs. paid, in plain terms.** Looking at past flights on the map is **free**.
Live position and the watch-and-alert monitor use ADS-B Exchange's paid data service
(about 10 US dollars a month via RapidAPI, with no free tier). If you ask for
something that needs it and no key is set up, Claude tells you plainly, offers to walk
you through getting one, and stores it securely on your own machine (never shown on
screen or written into a report). For history older or larger than the free map
shows, there is also an opt-in paid archive Claude can set up.

**A note on alerts.** A watch-and-alert runs as a scheduled task, so it only fires
while your computer is awake and Claude is open. Claude explains this, mentions the
always-on cloud alternative, and warns you if checking too often would run past the
monthly request limit. To stop a monitor, you pause or delete that scheduled task.

---

## Common use cases

- **Check your own footprint.** "Find my handle `janedoe` and show me everywhere it
  has an account." Useful before a job search, or just to know what is public.
- **Brand or impersonation monitoring.** "Search the username `acme-support` and flag
  any accounts pretending to be us," then save the report as a record.
- **A consented or authorized investigation.** With proper authorization, run a
  combined recon on a subject's username and email and produce a documented,
  timestamped evidence file.
- **Security research.** Map the public footprint tied to an identifier, including an
  optional check for whether it appears in infostealer leak data.
- **Track an aircraft's movements.** With authorization, pull the flight history for a
  **specific historical date** (the day a tail number left a given airport), capture
  the evidence and the KML flight path, or set an alert for when the aircraft
  approaches a destination.

In every case the deliverable is the same: confirmed findings, with screenshots and a
report you can keep.

---

## How a typical run goes

1. You ask, for example, *"find the username johndoe and capture evidence."*
2. Claude runs **preflight** to confirm your browser and local execution are ready.
3. It triages all the sites quickly **on your machine** and shows you the short list
   of likely accounts.
4. For each likely hit, it opens the page in your browser, confirms it is real, and
   screenshots it. If a site shows a CAPTCHA, it pauses and asks you to solve it; it
   never tries to bypass one.
5. It offers you the report. You can also ask for other formats.

---

## Reading the output, and where it is saved

The default deliverable is **one HTML evidence report**. It opens offline in any
browser and contains, for each confirmed finding: the screenshot (click to enlarge),
the exact link, the date and time in UTC, how it was captured, and a **SHA-256
tamper-check code** computed from the image. When you open it, the page re-checks
those codes and shows "integrity verified," and it prints or exports to PDF cleanly.

The report is also interactive: each finding has a "relevant, include in export"
checkbox so you can keep the signal and drop the noise, then export just the subset
as CSV or as a JSON case file (a "Copy for Claude" button lets you paste it back for
a written summary).

Files are saved into the project folder you are working in, under
`evidence/<case-id>/` for the screenshots and `Evidence_<subject>.html` for the
report. At the end of a run you can also ask for **CSV or JSON** of the findings, or a
**Word (.docx) or PDF** write-up.

---

## Adding your own sites, and keeping checks accurate

The site lists are not fixed. Two skills keep coverage growing and trustworthy, and
both are designed so a non-expert can use them.

**To add a site you care about**, say *"can we add example.com to the checks?"* The
**add-site** skill will check whether the site even works for this (it needs a public
per-user page, or a public "is this email registered" signal that is visible without
logging in), then learn the difference between a real account and a missing one, write
a detection rule, and verify it. For sites that need a throwaway test account as a
reference, Claude asks you to create one and keeps it safely on your own machine,
never in the plugin or any report.

**To keep checks accurate over time**, say *"verify the sites"* or, if a result looks
off, *"this GitHub result looks wrong."* Websites change how they respond, which can
quietly cause false positives ("found everywhere") or false negatives ("missed a real
account"). The **site-healing** skill tests a site with a known-existing and a
known-missing identifier and repairs the rule when it has drifted. This is the
"self-healing" half of the plugin, and it pairs well with a weekly scheduled check.

---

## Limitations and caveats (please read)

- **A match is a lead, not proof.** Confirm before drawing conclusions, and do not
  pair results with someone's home address or other locating data.
- **"Unknown" is not "no."** A blocked or challenged site means the check could not be
  trusted there, not that nothing exists.
- **Email checks are newer and need confirming.** The email site rules were adapted
  from another project and have not all been tested live, because the checks have to
  run on your machine. Treat email results as provisional until confirmed, and use
  site-healing to fix any that look wrong. A handful of sites are intentionally not
  included because they cannot be checked safely without bespoke code.
- **Coverage is a snapshot.** Sites come and go and change. Use add-site and
  site-healing to keep the lists current.
- **Some checks could be noticed.** A few email sites would email the person if
  probed; these are labeled "loud" and are off unless you opt in. Adult sites are
  off unless you opt in.

---

## Troubleshooting

- **"It found almost nothing."** The search ran in Claude's blocked cloud workspace
  instead of on your machine. Connect Desktop Commander, or run the one command in
  your Terminal, and try again.
- **"A site says it cannot verify."** That site challenged the check. Let Claude open
  it in your browser, solve the human-check if one appears, and it will confirm.
- **"The browser will not connect."** Make sure **Playwright MCP** is enabled in
  Settings → Capabilities and running visible, then ask Claude to try again.
- **Anything unclear?** Just ask Claude *"set up the tools"* and it will re-check
  everything and tell you what is missing in plain language.

---

## What's in this repository

| Path | What it is |
| --- | --- |
| [`osint-recon/`](osint-recon/) | The plugin (skills, engine, site lists, docs). |
| [`osint-recon/README.md`](osint-recon/README.md) | Technical overview. |
| [`osint-recon/HANDOFF.md`](osint-recon/HANDOFF.md) | Quick reference for teammates. |
| `osint-recon.plugin` | The installable plugin bundle. |
| `data.json` | The username site list (snapshot). |
| `NOTICE` | Attribution and licensing. |

---

## License and attribution

MIT. The username site list derives from the MIT-licensed
[Sherlock](https://github.com/sherlock-project/sherlock) project; the email and
infostealer detection is informed by the MIT-licensed
[user-scanner](https://github.com/kaifcodec/user-scanner) project, and the leak check
is powered by [Hudson Rock](https://www.hudsonrock.com). See
[`osint-recon/NOTICE`](osint-recon/NOTICE) for details.
