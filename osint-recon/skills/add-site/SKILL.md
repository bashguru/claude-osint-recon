---
name: add-site
description: >
  This skill should be used to evaluate whether a website can be added to the
  osint-recon site list and, if so, to derive its detection rule. Trigger on
  phrases like "add this site to the list", "can we add X to osint-recon", "is
  this page a good candidate", "onboard a site", "create a detection rule for
  this site", "teach the tool a new site", or when an analyst wants to grow
  coverage from a page they found. Determines candidacy (public per-username
  profiles), uses a throwaway registered account as the known-good oracle, and
  derives + verifies the rule, all detection done logged OUT.
metadata:
  version: "0.3.0"
  author: "Claude OSINT Investigator"
---

# Add a site (onboard new coverage)

Grow the manifest the right way. Decide whether a site can be enumerated, then
learn its found/not-found "tell" and write a verified rule. This is the build-time
companion to **site-healing** (which *repairs* existing rules). Read the method in
`${CLAUDE_PLUGIN_ROOT}/skills/username-search/references/tradecraft.md`
("Adding a new site") alongside this skill.

## The one rule that shapes everything (detection runs logged OUT)

`hunt.py` probes every site as an **anonymous visitor**. So the indicator you build
must be visible **without logging in**. A registered account is only the *oracle*,
a username you *know* exists, so you can compare it against a known-missing one.
The comparison itself is always done logged out. Never build a rule that depends on
being authenticated; it would not work in production and would violate the plugin's
public-pages-only ethic.

## Step 1. Preflight & assess candidacy

1. Run **preflight** so prerequisites (browser + local execution) are ready.
2. Open the site and find whether it has **public, per-username profile URLs**,
   a stable pattern like `site.com/{user}`, `site.com/u/{user}`, `site.com/@{user}`,
   or `site.com/users/{user}`. View a real profile **logged out**.
3. Decide:
   - **Good candidate.** A logged-out visitor can load a specific user's page at a
     predictable URL, and a missing user looks different (404, an error message, or
     a redirect).
   - **Not a candidate.** Profiles are only visible to logged-in users, there's no
     per-user public page (search-only), every URL returns the same page, or the
     site is purely a login wall. Say so plainly and stop. Don't force a rule that
     can't work anonymously.

State your candidacy verdict and the URL pattern before going further.

## Step 2. Get the oracle (a known-existing username)

You need one username that definitely exists on the site.

- **Default (the analyst registers it).** Ask the analyst to create a **throwaway
  test account** (not a personal one) and give you just the **username/handle**.
  Most sites gate signup behind CAPTCHA/email and automated signup usually breaks
  their ToS, so registration is the analyst's job, not Claude's.
- Confirm the new profile is **public**: visit its URL **logged out** and check the
  real profile renders (not a login wall). If the analyst needs to flip a "make my
  profile public" setting, have them do it, then re-check.

### Login & storing the oracle (store once, reuse forever)

The throwaway account is a long-lived **oracle**, so capture its credentials once
and let Claude reuse them for future re-verification and self-healing, without
re-asking the analyst. This is what lets Claude do most of the lifting over time.

- **Register (one-time).** The analyst creates a **dedicated throwaway account**
  (never a personal one). Most signups need a human (CAPTCHA/email), so this stays
  the analyst's step; Claude assists where a site allows it.
- **Store it.** Save the credentials to the local oracle store with
  `oracle_store.py`. Pass the password on **stdin** so it never lands in shell
  history, and point `--store` at the analyst's project folder (outside the plugin):

  ```bash
  printf 'THE_PASSWORD\n' | python3 \
    "${CLAUDE_PLUGIN_ROOT}/skills/add-site/scripts/oracle_store.py" \
    add --site "Example" --username throwaway_oracle \
    --email me+ex@example.org --url "https://example.com/{}" \
    --password-stdin --store "<project-folder>/oracle-credentials.json"
  ```

- **Reuse it later.** On future runs (confirm the oracle still exists, re-derive
  indicators after a redesign, site-healing) read it back with
  `oracle_store.py get --site "Example"` and log in as needed, no need to re-ask.
- **Log in only when needed.** Routine detection is logged OUT. Log in only to
  confirm the account is alive or to compare authenticated vs anonymous views, then
  log out before deriving the final rule.

**Credential safety (always):**
- Throwaway/dedicated test accounts ONLY, never a personal or reused password.
- The store lives in the **project folder, outside the plugin tree** (so it is
  never packaged or shared), is written `chmod 600`, and is auto-`.gitignore`d by
  the script. Set `$USERNAME_RECON_ORACLE_STORE` to fix its path once if you like.
- The **manifest stores only the username** (`username_claimed`); the password
  lives **only** in the oracle store.
- Never put a password in the evidence report, a CSV/JSON export, "Copy for Claude",
  chat, or conversational memory. `oracle_store.py` masks passwords unless you pass
  `--reveal`. Keep it that way. See
  `${CLAUDE_PLUGIN_ROOT}/skills/add-site/references/credential-store.md`.

## Step 3. Derive the rule (logged out)

With the known username `K` and a **random non-existent** username `R` (a long
random string), as an anonymous visitor, compare the two profile URLs:

- **Different HTTP status** (e.g. 200 vs 404) → `errorType: "status_code"`. Note
  any odd "200-with-a-404-page" code in `errorCode`.
- **Same status, different body** → `errorType: "message"`. Choose a **stable
  substring** unique to the *missing* page for `errorMsg`. Prefer something in a
  `<title>` or an error container; avoid boilerplate that appears on every page.
- **Missing user redirects away** (to home/login) → `errorType: "response_url"`,
  and record the missing-user destination in `errorUrl` so detection compares the
  final URL (more reliable than status alone).

Two stronger signals are available (see the schema in `tradecraft.md`):

- **Positive marker (`existsMsg`).** When the real and missing pages share a
  status and look similar, set `existsMsg` to a substring that appears **only on a
  real profile**, often the handle itself (`{}`-interpolated, e.g.
  `profile:username" content="{}"`). This beats a negative-only rule on sites that
  return 200 for everything.
- **Ambiguous statuses** (401/403/406/429/503) are reported as `waf` (unknown), not
  not-found, so you do not need to encode them as negatives. If a site genuinely
  uses one to mark absence, list it in `errorCode`.

Watch for traps: a site that 200s every URL (prefer `existsMsg`, or `message`),
soft-404s, WAF challenge pages (handled as `waf`, not a real negative), and
username format rules (set `regexCheck`). Capture a screenshot of both the real and
missing pages as backup evidence.

## Step 4. Propose the manifest entry

Assemble the entry and **show it to the analyst for approval before writing** (default):

```json
"Example": {
  "errorType": "status_code",
  "url": "https://example.com/{}",
  "urlMain": "https://example.com/",
  "username_claimed": "the_throwaway_handle",
  "regexCheck": "^[A-Za-z0-9_]{3,30}$"
}
```

Use the real fields you derived (add `errorMsg`/`errorCode`/`urlProbe`/`headers`
as needed; see the schema in `tradecraft.md`). `username_claimed` is the throwaway
handle (the oracle site-healing will reuse). On approval, add it to
`${CLAUDE_PLUGIN_ROOT}/skills/username-search/data/data.json`. (If the analyst
prefers, you can write automatically once Step 5 reports healthy.)

## Step 5. Verify until healthy

Confirm the JSON parses and the rule works using the same engine real searches use:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" list --names | grep -i "Example"
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" verify --site "Example"
```

A correct entry reports **`healthy`** (known → found, random → not_found). If it
reports `false_positive`/`false_negative`/`waf_blocked`, hand to **site-healing**
to tune the rule, then re-verify. Prefer running `verify` on the analyst's machine
(Tier 2) over the sandbox.

## Bot challenges & page hygiene

If a human-verification challenge appears, **never auto-bypass it**. Apply the
run's bot policy (assisted = the analyst solves it in the visible Playwright window; automated
= screenshot the block as evidence and continue). Work one page at a time and
**close each tab after you've captured what you need**; if a tab is closed, just
re-navigate (state isn't kept in the tab).

## Onboarding an email site (email mode)

The same method onboards a site for the **email-search** path. The differences:

1. **Candidacy** is a public, unauthenticated **signup or validation endpoint**
   that reveals whether an email is already in use (so a signup form can say "email
   taken"). No login, never submit a password. If the only way to tell is by
   completing a signup or triggering a reset email, it is **loud**, mark it
   `"loud": true` so it is skipped unless the analyst opts in.
2. **Oracle** is a throwaway **email** you control that is registered on the site
   (store it the same way; set it as `username_claimed`). The random comparison
   uses a random non-existent email.
3. **Derive** the rule logged out: capture a known-registered vs a random email
   response and pick `existsMsg`/`errorMsg` substrings (these endpoints usually
   return JSON, so a substring like `"email_is_taken"` or `null` works). If the
   endpoint needs a CSRF token or cookie first, add a `prefetch` block with a
   `capture` regex, and reference it as `{token}` in `request_form`/`headers`.
   Many email rules also harvest profile fields into `extra` (see `tradecraft.md`
   and the seed entries in `data/email_data.json` for the exact shape).
4. **Write** the entry to `${CLAUDE_PLUGIN_ROOT}/skills/username-search/data/email_data.json`
   (not the username manifest).
5. **Verify** with the email mode of the same engine:
   `hunt.py verify --email --site "Example"` (set `username_claimed` to your known
   email first). A correct entry reports `healthy`.

Everything else (preflight, candidacy discipline, the throwaway-oracle and
credential-safety rules, bot-challenge policy) is identical. The detection schema
is the same one in `tradecraft.md`; do not invent a second format.

## When done

Tell the analyst the site is added and verified, note the detection method you
chose (and whether it is a username or email site), and remind them they can re-run
a search (now covering the new site) or build an evidence report.
