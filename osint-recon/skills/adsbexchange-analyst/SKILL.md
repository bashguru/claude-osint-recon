---
name: adsbexchange-analyst
description: >
  This skill should be used when the user wants historical flight records or live
  tracking for a specific aircraft from ADS-B Exchange, court-ready snapshot
  evidence of a flight, a KML 3D flight-path file, or a scheduled monitor that
  alerts on a condition. Trigger on phrases like "track this aircraft", "where did
  this plane go", "flight history for", "what did tail N76528 do after leaving
  Austin", "show me UAL2177 departing KAUS on a date", "did this jet take off",
  "download the flight path", "give me the KML", "watch this aircraft and tell me
  when it's within 100 miles of an airport", "monitor a tail number", "is this
  plane near X right now", or any ADS-B Exchange or flight-tracking OSINT request.
  Routes to the free globe map for historical pulls, the live API for tracking and
  monitoring, and an opt-in trace archive for older or bulk data.
metadata:
  version: "0.1.0"
  author: "Claude OSINT Investigator"
---

# ADS-B Exchange analyst (flight history, evidence, KML, monitoring)

Pull the flight history for a specific aircraft, capture court-ready snapshot
evidence, download the 3D flight-path file, or set up an alert that watches an
aircraft, all from ADS-B Exchange, all in plain language.

**Who this is for.** The analyst may be non-technical and may not know the
difference between a flight number, a tail number, and a hex code, or what UTC or a
KML file is. Lead them one step at a time, explain each term in a few words the
first time it comes up, never make them guess, and never dump jargon. Be the
knowledgeable colleague walking them through it.

A flight track is a **lead and a record of a public radio broadcast, not proof of
who was on board.** Say that plainly when it matters.

## Authorized-use gate (check first)

Run this only for lawful, authorized work: tracking an asset you own or are
contracted to monitor, a consented investigation, journalism, security research, or
compliance and impersonation monitoring. Decline if the intent is to stalk, harass,
ambush, or surveil a private individual's movements, and do not pair a track with a
person's home address or other locating data. Aircraft that hide their identity
(the "PIA" and "LADD" privacy programs, which anonymize or suppress the broadcast
id) get extra care and the same gate. If the intent is unclear, ask one brief
question before proceeding.

A note on the source's terms, in plain words: ADS-B Exchange data is licensed for
personal or non-profit research, education, or internal evaluation. Commercial use
needs their written permission, and publications must cite "ADSBexchange,
http://www.ADSBexchange.com". Keep use within that frame.

## Step 0. Preflight

Run the **preflight** skill first (it self-skips when already confirmed this
session, so the analyst does not wait). For this skill you need the **Playwright
browser** (the required browser, run visible) for the globe and for evidence
screenshots. Local execution and Python matter for the monitor script and the
credential store. Tell the analyst in one line what is ready, then continue.

## Step 1. Lead the analyst (guided intent router)

Do not wait for a perfectly formed request. Unless the analyst already said exactly
what they want, open with a short, plain-language menu of what this can do:

- **See where a flight went in the past** (a specific aircraft leaving a specific
  airport on a date). Free, no account needed.
- **See where an aircraft is right now** (its live position).
- **Watch an aircraft and get an alert** (for example, tell me when it gets within
  100 miles of an airport).
- **Get the 3D flight-path file** (a KML, a file you open in Google Earth to fly
  along the route).

Then gather what you need, one easy question at a time, and **raise the leading
questions up front so nothing is a surprise later:**

- **Which flight or aircraft?** Tell them they can give any one of: a **flight
  number** (like UAL2177, the airline-and-number for a scheduled flight), a **tail
  number** (like N76528, the registration painted on the aircraft), or a **hex
  code** (like A4400F, the aircraft's unique radio id). One is enough.
- **Which airport, and which date?** Remind them gently that the site keeps time in
  **UTC** (a single world clock, also shown as "Z"), and that you will handle the
  conversion, so they can just give a normal local date.
- **For a past flight, ask now what they want as output:** the **evidence photos**
  (a court-ready picture of exactly what was on screen), the **KML 3D track file**
  (opens the route in Google Earth), or **both**. You will confirm again right
  before saving, but ask up front so the run is set up correctly.
- **Free vs. paid, only if it comes up.** Default to the free map without making
  them think about tiers. Only if they need older or bulk history than the free map
  shows, explain in plain words that there is a paid add-on for the deep archive
  (going back years) and offer to set it up. Otherwise do not mention it.

If the request already names everything, skip the menu and proceed.

Routing, in plain terms:

- **Past flight** uses the **free globe map** by default (Step 2).
- **Live position / monitor** uses the **live data service** (the API), which needs
  a key (Steps 5 and 6).
- **Older or bulk archive** uses the opt-in **trace archive** (Step 2, note at end).

## Step 2. Historical departure search (free globe map, the default)

Accept requests like "show me UAL2177 leaving KAUS on 2026-06-15" or "what did tail
N76528 do after departing Austin last Tuesday." Pull out the aircraft id
(registration, hex, or callsign), the airport, and the date or range. **Convert any
local date to UTC and tell the analyst plainly that you did** (for example, "10pm
Austin time on the 14th is the 15th in UTC, so I am looking at the 15th").

Drive the globe in the browser (Step 3). Use the deep-link URL parameters and the
controls recorded in
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/data/adsbx_map.json` and
explained in `${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/references/adsbx-capabilities.md`.
The flow:

1. Optionally **Jump** to the departure airport (the "Jump to Airport" box) to
   frame the view.
2. **Search** the aircraft (the "Search:" box takes a callsign, registration, or
   hex). The aircraft panel opens on the left.
3. Click **History**, then set the **"UTC day"** to the target date (or step it
   with previous/next). The day's track draws on the map. A quick deep-link is to
   open `https://globe.adsbexchange.com/?icao=<hex>&showTrace=YYYY-MM-DD`.
4. Step **Legs** (previous/next) to the specific leg that departs the airport in
   question. A "leg" is one takeoff-to-landing segment of the day.
5. Show what you found and **confirm the target with the analyst before capturing.**

If only an airport and a time window are given with no specific aircraft, use the
replay toolbar or a heatmap window to surface departures, then let the analyst pick
which aircraft to pursue, in plain language. Keep it interactive.

If a requested date returns no track, say so plainly (history depends on how long
ADS-B Exchange keeps data). For older or bulk data, offer the trace archive upgrade.

**Older or bulk archive (opt-in only).** If the analyst needs data older or larger
than the free map shows, the date-addressable trace archive is the tool. There is a
free public sample for testing and a paid subscription for full access. See the
"Surface 3" section of the capabilities reference. Do not route here unless the
analyst opts in.

## Step 3. Browser navigation (Playwright, visible, human-paced)

Use the Playwright browser (`mcp__playwright__*`), run **visible**, one clean tab at
a time, closing the tab between targets the way **evidence-report** does. Prefer
the deep-link URL parameters to set up a view deterministically, then click only
where the page requires it: Search, Jump, the UTC-day previous/next, the Legs
previous/next, the trace line to start playback, `K` to show trackpoints, and the
KML button. Take an accessibility snapshot before acting on a control so the
self-heal loop has something to compare against.

Two real-world notes from the live site:

- A **marketing newsletter popup** sometimes covers the page and blocks clicks.
  That is an ad overlay, not a security check, so dismiss it (its close button) and
  continue.
- The page is protected by **reCAPTCHA** (a Google check that quietly watches for
  robot-like behavior and only shows a puzzle if it sees it). Human-paced clicking
  keeps it quiet. See the anti-bot section below.

## Step 4. Snapshot evidence (reuse evidence-report; do not reinvent)

Capture snapshots through the existing **evidence-report** machinery. Do not write a
second report generator. For each confirmed view, one clean tab at a time:

1. Navigate to the exact globe URL (include the aircraft and the `showTrace=` date
   so the link reproduces the view).
2. Screenshot into `evidence/<case-id>/` inside the analyst's working folder.
3. Record a finding entry with the standard fields (full URL, UTC capture time,
   method, page title) **plus aircraft-specific fields**: registration, ICAO hex,
   callsign, departure airport, and the observed date in UTC. Put the aircraft
   details into the finding's notes so they render.
4. Also record the **Copy Link** permalink from the aircraft panel.
5. Build the report with the existing generator:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py" \
       evidence/case.json --out "Evidence_<aircraft>.html"
   ```

The generator computes a SHA-256 (a digital fingerprint that proves the image was
not altered) for each screenshot and embeds everything in one self-contained HTML
file. Full capture protocol and the metadata schema are in the **evidence-report**
skill.

## Step 5. KML download (confirm before saving)

The output choices were already raised in Step 1. Once the historical track is on
screen, **confirm in one plain line before producing each artifact**, so a
non-technical analyst is never surprised by a download:

- "Ready to save the evidence photos?"
- "Ready to download the KML 3D flight-path file? It opens the route in Google
  Earth."

Only if they want the KML, click the **"baro + avg" KML button** (the default,
terrain-aligned export; its exact control is `#export_kml_geom_avg` in the map).
Save the KML next to the case evidence as
`evidence/<case-id>/<reg>_<date>.kml`, record its path and a SHA-256 in the case
file alongside the screenshots, and tell the analyst plainly that it opens in
Google Earth. **Never auto-download without a yes.**

## Step 6. Monitor an aircraft and alert (live API + a scheduled task)

For requests like "watch N76528 and when it gets within 100 miles of KAUS, check
every 5 minutes and tell me." The data comes from the **live data service** (the
API), and the schedule is a **Claude Desktop scheduled task**. Full detail is in
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/references/monitor-setup.md`.

1. Parse the rule in plain language: the target aircraft, the trigger (within N
   miles of an airport, on the ground at an airport, a departure, or an altitude or
   speed threshold), and how often to check.
2. The monitor is a **single-shot check**, not a program that runs forever. Each
   time the schedule fires, run one check:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/scripts/monitor.py" check \
       --registration N76528 --airport KAUS --within-mi 100 \
       --state ./monitors/N76528_KAUS.json --interval-min 5
   ```

   It makes one live call, measures the distance, updates a small **state file**,
   and **alerts only on the run where the condition first becomes true** (one alert
   per change, not every run). For an airport the script does not know, pass
   `--ref-lat` and `--ref-lon`.
3. **Set up the schedule in Claude Desktop.** Guide the analyst to create a
   scheduled task that runs this check on their cadence (for everyday use, the
   Cowork scheduled tasks, no code). Five-minute and other off-grid intervals are
   not in the picker, so have them say it in plain words, like "run my N76528
   monitor every 5 minutes." The alert is the task's output; Claude Desktop shows
   it. Do not add any email or webhook.
4. **State the limits plainly.** A local scheduled task only runs while the computer
   is awake and Claude Desktop is open, and a missed run is skipped until then. If
   they need always-on monitoring (even when the computer is off), explain the
   remote routine that runs in Anthropic's cloud, and its one catch: a cloud run
   cannot read the key from the local keychain, so the key must be made available to
   that remote context.
5. **Watch the budget.** The base plan is about 10,000 requests a month, so a
   continuous 5-minute check (about 8,600 a month) is close to the cap for one
   monitor. Warn plainly and suggest a gentler interval if their plan would be
   exceeded. The script prints a warning when `--interval-min` is tight.
6. **Stopping and listing.** A monitor is just a scheduled task. To list active
   monitors, list the scheduled tasks. To stop one, pause or delete that task. Tell
   the analyst the plain steps.

If no key is stored, do not fall back silently. Tell them a key is needed, offer to
walk them through getting one, and offer a one-time globe spot check meanwhile (with
a clear note that continuously checking the website by hand is discouraged).

## Step 7. Credentials and key acquisition

The live API and the paid trace archive need a key (a password-like string that
proves a subscription). Handle it through
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/scripts/creds.py`, never
hard-coded and never echoed. Default store is the analyst's OS keychain; an
environment variable (`ADSBX_API_KEY`) and a gitignored local config also work.
Full detail, including the no-key walk-through and the redaction rules, is in
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/references/credentials.md`.

When a key is missing for what the analyst chose, explain plainly that the live API
is about 10 USD per month via RapidAPI ("API Lite"), with no standard free tier
(feeders may get the fee waived), then offer two paths: walk them to the signup in
the browser and store the key, or proceed now on the free globe where the task
allows. Once they have a key, store it and confirm **without printing it**.

## Anti-bot behavior (reduce friction, never evade)

The goal is to be a **well-behaved, human-paced visitor so challenges never
trigger**, not to defeat any protection. The globe uses Google reCAPTCHA, the
invisible kind that scores behavior in the background and only shows a puzzle if it
looks robotic, so acting like a person keeps it quiet.

- Run Playwright **visible**, reuse a persistent browser profile rather than a fresh
  one each run, use a normal desktop window, and add small human-scale pauses
  between actions (hundreds of milliseconds to a couple of seconds, not zero). Move
  and click rather than firing instant events. Do one aircraft at a time.
- Honor the site: respect `robots.txt` and the terms, throttle, and back off on a
  `403` or `429` (signals that you are going too fast or are blocked). For anything
  repeated or programmatic, use the live API or the trace archive, not the globe.
- If a reCAPTCHA or other bot challenge does appear, **never try to solve or bypass
  it.** Apply the run's bot policy, the same one the sibling skills use, set as a
  parameter of the run:
  - **Assisted** (default for interactive runs): hand off to the analyst to solve it
    in the visible window, in plain words, for example "the site is asking me to
    confirm we're human, please click the checkbox in the window and I'll continue."
  - **Automated** (for unattended runs): screenshot the block as evidence, record
    that the step was blocked, and stop.

The intent here is friction reduction and compliance, not evasion.

## Self-healing (keep the map accurate; mirror site-healing)

When a step that should succeed fails (a control is not found, a URL parameter stops
behaving, the KML button moved, a trace endpoint changed shape), do not give up and
do not silently continue with a wrong result. Run a bounded repair loop, the same
shape as **site-healing**:

1. **Detect** the break precisely (which step, expected vs. actual).
2. **Diagnose**: take a fresh `browser_snapshot`, inspect the page, and compare the
   live structure to the recorded selector or parameter in `data/adsbx_map.json`.
   Try the `reset` and `showerrors` URL parameters where relevant.
3. **Re-derive** the correct selector, parameter, or endpoint.
4. **Retry** the step with the new value. Repeat steps 1 to 4 up to **5 attempts**.
5. **On success, persist the fix**: update `data/adsbx_map.json` (and the
   capabilities reference if a documented behavior changed) so every future run uses
   the corrected value, with a note and today's date. Append a line to a short
   `heal-log.md` in the working folder so repeated breaks are visible over time.
6. **On failure after 5 attempts**, stop and tell the analyst clearly: which step
   broke, what you tried each time, the best guess at why, and what is needed
   (often that ADS-B Exchange changed the page and the recorded map needs a human
   eye). Do not fabricate a result.

## What this skill deliberately does not do

- It does **not** capture screenshots or build the report itself. Snapshot capture,
  SHA-256 hashing, and the self-contained HTML report come from **evidence-report**.
- It does **not** check prerequisites itself. Playwright, local execution, and
  Python readiness come from **preflight** (called at Step 0).
- It does **not** define its own bot-challenge handling or visible-browser rule.
  Those are the plugin's existing policy, applied as a per-run parameter.
- It does **not** scrape the globe at volume or use undocumented endpoints for
  automation. Repeated or programmatic access uses the official API or the trace
  archive.
- It does **not** solve or bypass reCAPTCHA, ever.
- Future selector or endpoint repair lives in **this skill's own self-heal loop**
  against `data/adsbx_map.json`, not in the username/email manifests that
  **site-healing** repairs.
