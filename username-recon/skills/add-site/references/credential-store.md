# Oracle credential store

A small, local store of **throwaway oracle accounts** — the disposable test
accounts whose only job is to be a "known-existing username" so the engine and the
site-healing skill can keep a site's detection accurate over time. Managed by
`${CLAUDE_PLUGIN_ROOT}/skills/add-site/scripts/oracle_store.py` (dependency-free).

## Why store credentials at all (detection is logged out)

Routine username detection never needs a login — it reads public pages anonymously.
The oracle credentials are for **maintenance**, so Claude can do the lifting later
without re-asking the analyst:

- Re-confirm the oracle account still exists/active (suspended or deleted accounts
  silently break `username_claimed` and the `verify` health check).
- Re-derive indicators after a site redesign, or compare authenticated vs anonymous
  views when a rule breaks.

The manifest holds only the **username** (`username_claimed`); the **password**
lives only here.

## Safety model

- **Throwaway / dedicated accounts only.** Never a personal or reused password.
  Plaintext-at-rest is acceptable for disposable accounts and *only* those.
- **Lives outside the plugin tree.** Default `./oracle-credentials.json` in the
  analyst's project folder (or `$USERNAME_RECON_ORACLE_STORE`). The script refuses
  to write inside the plugin, so it is never packaged into `username-recon.plugin`
  or shared.
- **Locked + ignored.** Written `chmod 600`; a sibling `.gitignore` is created
  automatically so it is never committed.
- **Never leaks into deliverables.** Keep passwords out of the evidence report,
  CSV/JSON exports, "Copy for Claude", chat, and conversational memory. `list`/`get`
  mask the password unless you pass `--reveal`.

## Store location (resolution order)

1. `--store PATH`
2. `$USERNAME_RECON_ORACLE_STORE`
3. `./oracle-credentials.json` (current working directory)

## File shape

```json
{
  "_warning": "Throwaway OSINT oracle accounts only — never personal credentials. …",
  "sites": {
    "Example": {
      "site": "Example",
      "username": "throwaway_oracle",
      "password": "…",
      "email": "me+ex@example.org",
      "url": "https://example.com/{}",
      "notes": "Created for detection only.",
      "throwaway": true,
      "created": "2026-06-14T15:00:00Z",
      "updated": "2026-06-14T15:00:00Z"
    }
  }
}
```

## Commands

```bash
ORC="${CLAUDE_PLUGIN_ROOT}/skills/add-site/scripts/oracle_store.py"
STORE="<project-folder>/oracle-credentials.json"

# Add/update (password via stdin so it isn't in shell history or process args):
printf 'THE_PASSWORD\n' | python3 "$ORC" add --site "Example" \
    --username throwaway_oracle --email me+ex@example.org \
    --url "https://example.com/{}" --password-stdin --store "$STORE"

python3 "$ORC" list --store "$STORE"                       # passwords masked
python3 "$ORC" get  --site "Example" --store "$STORE"      # masked
python3 "$ORC" get  --site "Example" --field password --reveal --store "$STORE"
python3 "$ORC" remove --site "Example" --store "$STORE"
```

## Typical lifecycle

1. **add-site** derives a rule using a throwaway account → store it here.
2. Months later, `verify` flags the site (oracle deleted, or a redesign). Claude
   reads the stored account, logs in to confirm/inspect, re-derives the indicator,
   and updates the manifest — no analyst round-trip.
3. Rotate or `remove` the entry if the throwaway account is abandoned.
