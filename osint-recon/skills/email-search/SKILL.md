---
name: email-search
description: >
  This skill should be used when the user wants to find which public websites
  have an account registered to an email address (email OSINT enumeration).
  Trigger on phrases like "check this email", "where is this email registered",
  "what accounts use this email", "email OSINT", "is this email on X", or when an
  investigation has an email and wants its account footprint. Mirrors the
  username-search workflow (preflight, triage, verify, evidence) and reuses the
  same engine and report. Checks public, logged-out signup/validation endpoints
  only; never logs in or submits credentials.
metadata:
  version: "0.1.0"
  author: "Claude OSINT Investigator"
---

# Email search (OSINT registration enumeration)

Find which public websites have an account **registered to an email address**,
then capture evidence the same way username-search does. This is the email
companion to **username-search**. It uses the **same engine** (`hunt.py`), the
same request strategy, the same execution tiers, and the same evidence and report
flow. It only asks a different question: "is an account registered with this
email?" instead of "does this handle exist?"

## How it decides (and what it never does)

Many sites expose a public, unauthenticated **signup or validation endpoint** that
answers whether an email is already in use (so the signup form can say "this email
is taken"). The engine reads that public signal, logged out, and **never completes
a login or uses real credentials.**

Some sites only reveal registration through their **login** form. For those, the
engine submits the email with a **blank or deliberately invalid password** purely to
read the public difference between "no account with this email" and "wrong
password." It never attempts real authentication and never accesses an account.
These **login-probe** sites are a little more intrusive than a signup check: a
failed attempt can count toward rate limits or lockouts, and on some sites the
account owner may be notified. They are marked in the manifest, and any that notify
the target are flagged `loud` and skipped unless the analyst opts in.

The common request pattern is one or two steps: optionally fetch a page to pick up a
CSRF token or cookie, then send the email to the endpoint and read the answer. The
engine handles both cases (see `prefetch`/`request_form`/`request_payload` in the
schema).

## Authorized-use gate (check first, stricter than usernames)

Email is more identifying than a handle, and several sites treat a registration
probe as sensitive. Only run this for lawful, authorized purposes: checking your
own footprint, a consented investigation, security research, or
brand/impersonation work. If the intent looks like stalking, harassment, locating
a private person, or credential-stuffing groundwork, decline. Do not pair results
with home addresses or other locating data. When intent is unclear, ask one brief
question. Otherwise proceed.

## Loud sites are excluded by default (do not tip off the target)

Some sites, when you probe an email, send the address a real notification (a
"reset your password" or "finish signing up" mail). Probing those is **loud**: the
target can see it. The engine flags such sites `loud` and **skips them unless the
analyst explicitly opts in** with `--allow-loud`. Default runs stay quiet. Only
pass `--allow-loud` when the analyst understands the target may be notified and has
a lawful reason.

## Adult sites (ask at the start)

The manifest includes adult/NSFW email sites, flagged `isNSFW` and **excluded by
default**. At the start of an email run, ask the analyst whether to include them,
and only pass `--nsfw` if they say yes.

## Step 0. Preflight (always)

Run the **preflight** skill first (Playwright, local execution for triage, Python
3.8+). It self-skips when already verified, so it will not make the analyst wait.
Email triage, like username triage, must run on the **analyst's machine**
(Desktop Commander or their terminal). The Claude sandbox is egress-limited and
will reach almost nothing, so never rely on in-sandbox results.

## Run the triage

The engine is the same `hunt.py`, with an `email` subcommand and its own manifest
(`data/email_data.json`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" \
    email someone@example.com --format json
```

Useful flags (same common set as `search`): `--site NAME` (repeatable),
`--include-all`, `--allow-loud` (include loud sites, off by default),
`--rotate-ua`, `--retries`, `--delay`, `--proxy-file`, `--timeout`,
`--max-workers`. Multiple emails: `... email a@x.com b@y.com`.

## Interpreting results

Each site resolves to one status: `registered` (an account exists for this email,
the hits to document), `not_registered` (no account), `waf` (a firewall or block
intercepted the probe, so the answer is unknown, say "could not verify"), `error`
(network/timeout, retry), `illegal` (not a valid email for that site), or
`loud_skipped` (a notifying site skipped because `--allow-loud` was not set).

Lead with `registered` sites. Treat a single hit as a **lead, not proof**: shared
or recycled emails happen, and a "taken" answer confirms registration, not who
controls the account.

### Harvested profile details

Where a registration endpoint also returns public profile data (for example a
display name, a public username, a join date, or an avatar), the engine collects
it into an `extra` field on the finding. Use this to corroborate and to pivot (a
harvested public username can feed a **username-search** run). Keep handling of any
personal data within the authorized-use scope above, and put only what the case
needs into the report.

## Producing evidence and outputs

Email findings are trickier to screenshot than username profiles, because the
"evidence" is often an API response rather than a public profile page. Capture
what is defensible:

- If the email maps to a **public profile** (for example a harvested public
  username, or a site that shows a profile by email), open and screenshot that
  page with the **evidence-report** skill, exactly as for usernames.
- Otherwise, record the finding (site, endpoint, UTC time, the registered/not
  answer, and the raw response if useful) in the case file. The evidence-report
  builder will include it as a documented finding even without an image.

Then offer outputs the same way: the **HTML evidence report** (default), a
**CSV/JSON** of findings, or a **Word/PDF** write-up. Let the analyst choose.

## Coverage, accuracy, and growing the list

The bundled email manifest covers roughly **98 sites across 18 categories**, ported
from the open-source user-scanner reference (a few bespoke ones that need runtime
crypto or HTML scraping were intentionally left out). Email endpoints drift faster
than profile pages (tokens, app keys, and markers change), and these ports have not
all been confirmed live, so **verify before relying**, ideally with a throwaway
email you control as the oracle:

```bash
# set username_claimed to a known-registered (throwaway) email first, then:
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" \
    verify --email --site "GitHub"
```

- To **add** an email site, use **add-site** in email mode (it derives the
  detection rule and, where needed, the prefetch/token step).
- When a site's result looks wrong, use **site-healing** in email mode to diagnose
  and repair the rule.

Both reuse the shared detection schema in
`${CLAUDE_PLUGIN_ROOT}/skills/username-search/references/tradecraft.md`. Bot
challenges follow the same never-auto-bypass policy as username-search.

## Combining with usernames

To investigate a subject across **both** a username and an email in one pass (plus
an optional infostealer check), use the **recon** skill, which orchestrates this
skill and username-search and routes the hits into one evidence report.
