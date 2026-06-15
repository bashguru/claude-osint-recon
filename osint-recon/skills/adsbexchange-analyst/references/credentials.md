# ADS-B Exchange API key store

The live API and the paid trace archive both need a key. This skill keeps that key
in a small, pluggable credential store and **never** hard-codes it, prints it, or
writes it into any output. Managed by
`${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/scripts/creds.py`
(dependency-free Python).

This is separate from the **oracle credential store** used by `add-site` (which
holds throwaway account passwords). This store holds one secret: the ADS-B Exchange
API key.

## What the key is, in plain words

The "API key" is a password-like string from RapidAPI that proves your monthly
subscription so the live data service answers your requests. It matters because the
monitor and any live-position check cannot run without it, and because, like any
password, it must never be shown on screen or saved into a report.

## Store options (resolution order)

The skill reads the key from the first source that has it:

1. `--key-command` output, if the analyst configured a custom manager.
2. **OS keychain** (default on the analyst's machine). On macOS this is the login
   keychain via the `security` CLI.
3. Environment variable **`ADSBX_API_KEY`**.
4. A gitignored local config file `./.adsbx-credentials.json` in the working folder
   (or `$ADSBX_CREDENTIALS_FILE`).

The store choice is a one-line setting, so the analyst can point it at a different
manager without touching the skill.

## macOS keychain (default)

```bash
CREDS="${CLAUDE_PLUGIN_ROOT}/skills/adsbexchange-analyst/scripts/creds.py"

# Store the key (read from stdin so it never lands in shell history or process args):
printf 'YOUR_RAPIDAPI_KEY\n' | python3 "$CREDS" set --store keychain

# Check a key is present (prints only whether it exists and a short fingerprint, never the key):
python3 "$CREDS" status

# Remove it:
python3 "$CREDS" delete --store keychain
```

Under the hood this uses:

- store: `security add-generic-password -a adsbexchange-analyst -s adsbx-api-key -w <key>`
- read: `security find-generic-password -s adsbx-api-key -w`

The service name is `adsbx-api-key` and the account is `adsbexchange-analyst`.

## Environment variable and local config (for Claude Code or the DGX)

```bash
export ADSBX_API_KEY='YOUR_RAPIDAPI_KEY'          # option 3
# or write a gitignored local config:
printf 'YOUR_RAPIDAPI_KEY\n' | python3 "$CREDS" set --store file
```

When `set --store file` writes `./.adsbx-credentials.json`, it locks the file to
owner-only (chmod 600) and adds it to a sibling `.gitignore` automatically, the same
safety model as the oracle store. The script refuses to write the config inside the
plugin tree so it is never packaged or shared.

## When no key is stored

The skill never fails silently. If a live-API or monitor request needs a key and
none is found, it:

1. Tells the analyst, in plain words, that a live key is needed and that the live
   API is about 10 USD per month via RapidAPI ("API Lite" / "Personal Use Aircraft
   Data API"), with no standard free tier (a data feeder may get the fee waived).
2. Offers to **walk them to the signup** with the browser: navigate to the API Lite
   / developer-hub page (`https://www.adsbexchange.com/api-lite/` then the RapidAPI
   listing `https://rapidapi.com/adsbx/api/adsbexchange-com1/`), guide them through
   subscribing, and copy the `x-rapidapi-key`.
3. Offers a **one-time globe-UI spot check** in the meantime where the task allows
   it, with a clear note that continuous checking of the website is discouraged and
   that the website is for human, not programmatic, use.

Once the analyst provides a key, the skill stores it via `creds.py` and confirms
**without printing it**.

## Redaction rules (non-negotiable)

- Never write the key into the case file, the heal log, screenshots, exports,
  "Copy for Claude," chat, or memory.
- `creds.py status` prints only whether a key exists plus a short, non-reversible
  fingerprint (first 4 and last 2 characters), never the full key.
- Before showing the analyst any error text from an API call, redact anything that
  looks like the key.

## Remote (cloud) runs

A monitor can be scheduled to run in Anthropic's cloud so it fires even when the
analyst's computer is off (see `monitor-setup.md`). A cloud run **cannot read the
local keychain**, so for that path the key has to be made available to the remote
context (for example as the `ADSBX_API_KEY` environment variable in the scheduled
routine). Explain this trade-off plainly and let the analyst decide.
