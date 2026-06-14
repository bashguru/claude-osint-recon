---
name: site-healing
description: >
  This skill should be used when username-search results look wrong for a site,
  or when the user wants to keep the OSINT engine accurate. Trigger on phrases
  like "verify the sites", "this result looks wrong", "fix the username checker",
  "why is X always showing found/not found", "self-heal the sites", "the manifest
  is stale", "update detection for site Y", or after adding a new site. Diagnoses
  false positives/negatives by probing known-good vs known-bad usernames, then
  repairs the site's detection rule in the manifest.
metadata:
  version: "0.3.0"
  author: "Claude OSINT Investigator"
---

# Site healing (keep detection accurate)

Websites change how they respond, which silently breaks username detection,
producing false positives (every name "found") or false negatives (real accounts
"missed"). This skill diagnoses and repairs those rules so the username-search
engine stays trustworthy. This is the "self-healing" half of the plugin.

## Where to run it (execution tiers)

`verify` uses the same `hunt.py` engine as search, so run it on the highest tier
available. Prefer the **analyst's own machine** (local CLI) over the **Claude
sandbox** (a last resort, since its flagged IP causes spurious `waf_blocked` verdicts
that look like broken sites). When you need to *eyeball* a profile to repair a
rule, use the **browser MCP** (the browser-mcp extension first, playwright-mcp as
the fallback). If a human-verification challenge appears, do not auto-bypass
it. Apply the run's bot policy (assisted = the analyst solves it; automated =
screenshot the block as evidence and continue). See the username-search
`tradecraft.md` for the full tier model.

## How verification works

Every site in the manifest carries a `username_claimed` value, a username that is
known to exist there. That is the oracle. The engine probes each site twice:

- with `username_claimed` → a healthy site answers **found**.
- with a random username → a healthy site answers **not_found**.

Any other combination means the detection rule is stale or blocked.

## Diagnose

Run the verifier (same engine as search, so a "healthy" verdict means real
searches are accurate too):

```bash
# One or more specific sites:
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" verify --site "GitHub" --site "Reddit"

# Everything (slower, hundreds of live requests):
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" verify --all

# Machine-readable, for triage at scale:
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" verify --all --format json

# Email sites use the same verifier with --email (against data/email_data.json):
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" verify --email --site "GitHub"
```

Email verification needs a known-registered email in the entry's
`username_claimed`; the engine compares it against a random non-existent email,
exactly as it does for usernames.

After a real search returns surprising results, verify the specific sites in
question first. It's fast and tells you whether the problem is the site or the
username.

## Read the verdict

- `healthy`. Known→found, random→not_found. Nothing to do.
- `false_negative`. Known account read as not-found. The "not found" message,
  success status code, or profile URL changed. Repair toward detecting existence.
- `false_positive`. Random username read as found. The rule is too loose; the
  site likely returns 200 for everything now, or its error string moved.
- `waf_blocked`. A firewall intercepted the probe. Detection can't be trusted;
  try a different probe/headers/proxy or leave the site flagged.
- `error`. Transient network/TLS issue. Re-run with a longer `--timeout`.
- `no_oracle`. The entry has no `username_claimed`; add one, then re-verify.
- `inconclusive`. Mixed signals; inspect the site manually.

## Repair

1. Open the suspect site in the **browser MCP** (preferred) or fetch it, then view a
   **known-existing** profile and a **random missing** one. Compare status codes
   and bodies. (If a bot challenge appears, hand off to the analyst and don't bypass.)
2. Decide the correct detection method and edit the site's entry in
   `${CLAUDE_PLUGIN_ROOT}/skills/username-search/data/data.json` (or
   `data/email_data.json` for an email site):
   - Status differs (e.g. 200 vs 404) → `errorType: "status_code"` (add the
     missing code to `errorCode` if it answers 200-with-a-404-page).
   - Same status, different body → `errorType: "message"` and set `errorMsg` to a
     stable substring unique to the missing page (prefer a `<title>` or error
     container; avoid generic boilerplate).
   - **Site now 200s everything** → add a positive marker `existsMsg` (a substring
     present only on a real profile, often the handle, `{}`-interpolated). This is
     usually the right fix for a `false_positive`.
   - Missing profile redirects away → `errorType: "response_url"`, and set
     `errorUrl` to the missing-user destination so the final URL is compared.
   - Update `url`/`urlProbe` if the path moved; add `headers`/`urlProbe` if a WAF
     is the problem. Note that 401/403/406/429/503 now report `waf` (unknown), so a
     block no longer masquerades as a false negative.
   See `${CLAUDE_PLUGIN_ROOT}/skills/username-search/references/tradecraft.md` for
   the full field schema and worked examples.
3. Re-verify the single site until it reports `healthy`
   (`... hunt.py verify --site "Repaired Site"`, add `--email` for an email site).
4. Confirm the JSON still parses (a healthy `verify`/`list` run proves this).

## Refresh from upstream

Before hand-repairing many sites, try refreshing the whole list, since the community
may have already fixed it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/username-search/scripts/hunt.py" update
```

This overwrites the bundled `data/data.json` with the latest community manifest.
Re-run `verify --all` afterward to confirm.

## Automating health checks

This pairs well with a scheduled task. Run `verify --all --format json` on a
cadence (e.g. weekly), then summarize any `false_positive`/`false_negative`
sites so they can be repaired before they affect real searches.
