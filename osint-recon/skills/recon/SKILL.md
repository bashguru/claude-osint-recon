---
name: recon
description: >
  This skill should be used to investigate a subject across BOTH a username and an
  email in one pass, with an optional infostealer check, and assemble everything
  into a single evidence report. Trigger on phrases like "OSINT this person", "run
  a full footprint", "investigate this subject", "I have a username and an email",
  "check the handle and the email", "run everything on X", or "do a complete recon".
  It orchestrates the username-search and email-search skills plus the infostealer
  lookup; it does not do any detection itself.
metadata:
  version: "0.2.0"
  author: "Claude OSINT Investigator"
---

# Recon (combined username + email + infostealer)

One workflow for a whole subject. Given a **username and/or an email** (and,
optionally, an infostealer check), this skill runs the existing pieces together
and produces **one** evidence report. It is an orchestrator: all detection lives in
the engine (`hunt.py`), all capture lives in **evidence-report**, prerequisites
live in **preflight**. This skill only sequences them and cross-references the
results, so there is no duplicated logic.

## Authorized-use gate (check first)

Same standard as the other skills, and a little stricter because this combines
identifiers. Run only for lawful, authorized work: your own footprint, a consented
investigation, security research, or brand/impersonation monitoring. Decline if the
intent is to stalk, harass, locate, or build a dossier on a private individual. Do
not combine results with home addresses or other locating data. A match is a
**lead, not proof of identity**. If intent is unclear, ask one brief question.

## Step 0. Preflight, load the methods, and parse identifiers

1. Run **preflight** (Playwright, local execution for triage, Python 3.8+). It
   self-skips when already verified, so it will not make the analyst wait.
   Triage runs on the **analyst's machine**, not the sandbox.
2. **Load the real method.** This skill orchestrates the others, but only this
   file is in context when `/recon` runs, so the other skills' instructions are
   not loaded automatically. Read both
   `${CLAUDE_PLUGIN_ROOT}/skills/username-search/SKILL.md` and
   `${CLAUDE_PLUGIN_ROOT}/skills/email-search/SKILL.md` now, and follow each for
   its branch. Do not work from memory of what they probably say.
3. **Parse every identifier the analyst already gave, do not re-ask for it.**
   Pull out **all** usernames and **all** emails from the request, then restate
   them back so nothing is lost, for example "username jeevacation; emails
   jeevacation@yahoo.com and jeevacation@gmail.com, running all three." Each email
   is its own target. Only ask which identifiers to use when none were given or the
   intent is unclear, and never silently drop one that was provided.
4. Confirm the rest, briefly and without guessing:
   - an optional investigator name for the case file,
   - the **bot-challenge policy** (assisted or automated; never auto-bypass),
   - whether to include the **infostealer** lookup (third-party, see Step 3),
   - whether to include **loud** email sites (off by default),
   - whether to include adult/NSFW email sites (off by default).

## Step 1. Triage every identifier, on the analyst's machine

Run a triage for **every** identifier parsed in Step 0, on the analyst's machine
via Desktop Commander or their terminal. This is a checklist, not a menu, so do
not stop after the username.

```bash
HUNT="${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py"

# Username(s): run if any username was given. The engine accepts one or more.
python3 "$HUNT" search USERNAME1 [USERNAME2 ...] --format json

# Emails: run ONE call that passes EVERY email at once (the engine accepts one or
# more). Do not run the username and skip this.
python3 "$HUNT" email EMAIL1 [EMAIL2 ...] --format json
```

So for a username plus two emails you run exactly two triage commands, one
`search` and one `email` covering both addresses, for example
`... email jeevacation@yahoo.com jeevacation@gmail.com --format json`.

Use the same flags the individual skills document (`--rotate-ua`, `--retries`,
`--delay`, `--proxy-file`, `--timeout`, `--max-workers`, plus `--allow-loud` and
`--nsfw` for email only when the analyst opted in). Follow the full method you
loaded in Step 0; this skill just runs each branch.

**Completeness gate (before moving on).** Confirm you have a triage result for the
username branch **and** for every email provided. If any email was not run, run it
now. A recon run that only triaged the username is incomplete, so restate the
missing identifiers and finish them before Step 2.

## Step 2. Cross-reference (the payoff of doing both at once)

- If an **email** result harvested a **public username** (the `extra` field), feed
  that handle into a `search` run. People reuse handles.
- If a **username** profile exposed an associated email, you may run that email
  through `email` (apply the authorized-use and loud rules).
- Keep a single candidate list for the subject so the same account is not captured
  twice.

## Step 3. Optional infostealer lookup (third-party, consent required)

Only if the analyst agreed in Step 0. This sends the identifier to Hudson Rock, a
third party that may log the query, so confirm consent, then:

```bash
python3 "$HUNT" infostealer THE_USERNAME --confirm --format json
python3 "$HUNT" infostealer THE_EMAIL --email --confirm --format json
```

Report infections as an enrichment finding (stealer family, date, sample logins),
with Hudson Rock attribution. Treat any exposed credentials as sensitive and
out of scope to act on.

## Step 4. Verify and capture into ONE report

Take the union of `found` username accounts and `registered` email sites (plus any
cross-referenced hits), then hand them to **evidence-report**: browser-verify each
public profile, screenshot it, and record the finding. Put username accounts, email
registrations, and the infostealer summary into **one** case file so the report
tells the whole story. Email findings without a public page are recorded as
documented findings (endpoint, time, the registered answer) per the email-search
guidance.

## Step 5. Deliver

Offer the standard outputs, the **HTML evidence report** (default), **CSV/JSON** of
all findings, or a **Word/PDF** write-up. Keep it interactive, share candidates
early, and confirm the high-value ones before capturing.

The delivered report must account for **every** identifier searched, a section or
clearly labeled findings for the username and for each email. If an email turned up
nothing, say so explicitly (for example "jeevacation@gmail.com, no registrations
found across the email manifest") rather than omitting it, so a quiet branch is
never mistaken for a skipped one.

## What this skill deliberately does not do

It does not implement any detection, request handling, rule derivation, or capture
logic. Those belong to the engine, **add-site**/**site-healing**, and
**evidence-report** respectively. If a site is wrong or missing, use those skills,
the fix flows back to every workflow at once.
