---
name: crypto-trace
description: >
  This skill should be used when the user wants to trace Bitcoin, follow stolen or
  suspicious crypto, find where coins went, or attribute a Bitcoin address or
  transaction to a known service. Trigger on phrases like "trace this bitcoin",
  "follow the crypto", "where did these funds go", "whose wallet is this address",
  "is this address an exchange", "find the cash-out point", "trace a ransom payment",
  "BTC transaction graph", or "run a crypto investigation". Bitcoin only (uses
  WalletExplorer). Covers attribution, forward tracing to a cash-out, peel-chain and
  mixer detection, and feeding the result into the evidence report.
metadata:
  version: "0.1.0"
  author: "Claude OSINT Investigator"
---

# Crypto trace (Bitcoin attribution & follow-the-money)

Start from a known Bitcoin address or transaction, attribute it to a known service,
follow the funds forward through intermediary wallets, and reach a cash-out point
where an off-chain subpoena can unmask identity. This reads the public ledger, the
same data anyone sees on a block explorer, through the free WalletExplorer API.

This is a first-pass, Bitcoin-only investigator. It is the native baseline an
analyst runs before paying for a commercial platform like Chainalysis or TRM, and
it cross-references with the username and email findings the plugin already
produces. An address found in a forum post or breach is the on-chain to off-chain
bridge.

## Authorized-use gate (check first)

This skill reads a public ledger, the same data anyone can see on a block explorer.
It is for lawful, authorized work: tracing stolen or defrauded funds, ransomware and
incident response, sanctions and compliance screening, your own wallets, or
consented investigations. On-chain tracing surfaces linkages between addresses and
services. It does not by itself prove who controls a wallet. Identity attribution
requires lawful off-chain data (a KYC subpoena to an exchange, a matched forum post,
breach data). Treat every attribution as a lead with a stated confidence, not proof.
Decline if the intent is to dox or locate a private individual without a legitimate
basis. If intent is unclear, ask one short question, then proceed.

## Step 0. Preflight (always)

Run the **preflight** skill first. This skill needs local execution to make the API
calls (the Claude sandbox's egress is allowlisted and cannot reach WalletExplorer,
so run `wxtrace.py` on the analyst's machine via Desktop Commander or their
terminal), Python 3.8+, and, only if visual evidence is wanted, the Playwright MCP.
Preflight self-skips fast when it already passed this session, so the analyst does
not wait. Tell them what is ready, then start.

## The workflow

A trace runs in three moves. Keep it interactive and share findings as they land.

1. **Attribute the starting point.** Run `lookup` on the seed address (or read the
   seed transaction with `tx`). A labeled cluster tells you immediately whether the
   start is already a known service. An unlabeled cluster is a private wallet to
   follow.
2. **Follow the money forward.** Run `trace` from the seed txid or address. It walks
   each spend forward, attributing every hop, and stops when funds reach a known
   service or a depth limit. Past an exchange the coins are commingled, so following
   further is meaningless without a subpoena.
3. **Read the endpoints.** The trace lists the services reached with categories and
   amounts. The exchange endpoints are your cash-out candidates, the off-chain pivot
   for a KYC request. Any mixer endpoint is an obfuscation point where the on-chain
   link likely breaks.

## The engine: `wxtrace.py`

Dependency-free standard-library Python (no `pip install`). Run it on the analyst's
machine, not the sandbox.

```bash
WX="${CLAUDE_PLUGIN_ROOT}/skills/crypto-trace/scripts/wxtrace.py"

# Attribute one or many addresses (label, wallet id, derived category):
python3 "$WX" lookup 16SbwNa22nBwhLtg6HzWVYFQiUxtNzAUpt --format json

# Read one transaction (inputs, outputs, labels, amounts, next_tx, UTC time):
python3 "$WX" tx 99fd988b...3ba7 --format json

# Forward-trace the flow of funds from a transaction or an address:
python3 "$WX" trace --txid 99fd988b...3ba7 --format console
python3 "$WX" trace --address 1KT9...Z5L --max-depth 12 --graph mermaid
```

Subcommands: `lookup`, `tx`, `address`, `wallet`, `wallet-addresses`, `trace`. Each
supports `--format {console,json,csv,md}` where it makes sense (`trace` defaults to
`json` for machine use; the others default to `console`). The paginated commands
(`address`, `wallet`, `wallet-addresses`) take `--from` (divisible by 100) and
`--count` (0 to 1000). `wallet` accepts a hex id, a label, or a label variant, so
`wallet Bitstamp.net` resolves the cluster.

### Trace options and guards

The trace is bounded so it cannot explode or hammer the host:

- `--max-depth N` (default 12), the hop limit.
- `--max-nodes N` (default 500), a hard cap on transactions expanded.
- `--min-amount BTC` (default 0.0001), a dust filter so trivial outputs are skipped.
- `--stop-at-service {true,false}` (default true). Past a known service the funds are
  commingled, so the trace stops there by default.
- `--direction {forward,backward}`. Forward is implemented fully. Backward is a
  shallow version that attributes each input of the seed transaction and follows one
  hop back. Deep backward tracing is a planned later enhancement.
- `--graph {none,dot,mermaid}` optionally emits a transaction graph. Mermaid renders
  in chat and in the evidence report.
- `--canonicalize` resolves a service name through the `alternatives` endpoint before
  categorizing.

Politeness is built in because this is a single host, unlike the username engine that
spreads across many. Requests are serial with a fixed `--delay` (default 0.5s, about
two per second), exponential backoff with jitter on 429 or 5xx (honoring
`Retry-After`, up to `--max-retries`, default 5), and a global `--max-requests` cap
(default 2000). Do not raise these to be aggressive.

## Attribution and categories

The engine classifies a service label into a conservative category by lowercase
substring match: `exchange`, `mixer`, `market`, `gambling`, `pool`, or `service`. A
labeled cluster that matches nothing is `named-service` (still a useful lead, just
uncategorized). An address with no label is a `private-cluster`. The full category
map, and how to extend it, lives in the reference (see below). Do not overclaim. An
uncategorized label is a lead to confirm, not a guess to assert.

## Pattern detection

The trace flags two patterns analysts care about:

- **Peel chain.** A long, mostly single-line path where a large amount is peeled off
  at each hop while a shrinking change output keeps moving. The trace reports the
  path and its length. This is a common layering tactic.
- **Mixer or tumbler hop.** Any endpoint categorized as `mixer` is called out as an
  obfuscation point, with a note that the on-chain link very likely breaks there.

## Interpreting results

Lead with the cash-out candidates, the exchange endpoints, because those are where a
lawful KYC subpoena can attach a real identity. Then the other services reached, then
any unspent holdings (funds still sitting at an unattributed address). Every node and
endpoint carries its WalletExplorer URL
(`https://www.walletexplorer.com/address/<ADDR>` and `.../txid/<TXID>`) so the
evidence step can open and screenshot it.

A cluster label is an attribution, not proof of identity. State a confidence: an
exchange or mixer cluster label is a strong lead, a `named-service` label is a medium
lead, an unlabeled cluster is weak on its own. Identity comes from the off-chain
request, not the chain.

## Cross-reference with recon (the on-chain to off-chain bridge)

This skill is most powerful next to the rest of the plugin. A Bitcoin address that
**username-search** or **email-search** surfaced (in a forum profile, a paste, or
breach data) feeds straight into `crypto-trace` as the seed. Conversely, the cash-out
exchange that `crypto-trace` reaches is the off-chain pivot, a KYC subpoena target
that ties the chain back to a person. When an investigation already has an address,
the **recon** orchestrator can call this skill as part of the run.

## Evidence integration (reuse evidence-report, do not rebuild it)

The deliverable is the same court-ready HTML the rest of the plugin produces. Map
each crypto finding into the existing **evidence-report** case-file schema so
`build_report.py` runs unchanged. The mapping:

| Case-file field | Crypto finding |
| --- | --- |
| `site` | "WalletExplorer" |
| `category` | the derived category (exchange, mixer, market, private-cluster, ...) |
| `status` | "attributed" for a labeled hit, "unlabeled" for a private cluster |
| `profile_url` | the WalletExplorer address or transaction URL |
| `captured_at` | the transaction time, or the run's generated time, in UTC |
| `notes` | amount in BTC, the path summary (origin to this endpoint), the confidence and heuristic used |
| `page_title` | the cluster label, or "private cluster" |
| `screenshot` | optional, see below |

A copy-paste recipe that turns `trace --format json` into a case file is in the
reference. Then build the report with the unchanged generator:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py" \
    case.json --out "Evidence_<subject>.html"
```

Optional visual evidence: for the high-value endpoints (the cash-out exchange, any
mixer, the origin), use the plugin's Playwright capture path exactly as
**evidence-report** describes. Navigate to the WalletExplorer page, confirm from the
title and URL, screenshot to `evidence/<case-id>/<name>.png`, and close the tab.
`build_report.py` then embeds the image and computes its SHA-256 so the report
self-verifies. Follow the same bot-challenge policy as the other skills. Never
auto-bypass a challenge.

## Output

`trace` emits, depending on `--format`:

- `json` (default), the full result: `origin`, `summary`, `nodes`, `edges`,
  `endpoints`, `cashout_candidates`, `paths`, `truncations`, `patterns_flagged`, and
  `generated_utc`.
- `console` or `md`, a readable narrative: the origin, the hop count, the services
  reached with categories and amounts, the cash-out candidates, and any flagged
  patterns.
- `csv`, the edge list (`txid`, `from_addr`, `to_addr`, `to_label`, `amount_btc`,
  `time_utc`) to pivot on.
- `--graph mermaid` or `--graph dot` adds a transaction graph.

Tell the analyst they can ask for the HTML evidence report (the default deliverable),
the CSV or JSON to pivot on, or a Word or PDF write-up. Offer, do not assume.

## What this skill deliberately does not do

- **No evidence rendering or screenshot hashing.** That is **evidence-report** and its
  `build_report.py`. This skill only produces the findings and the WalletExplorer
  URLs that feed it.
- **No prerequisite setup.** That is **preflight**.
- **No non-Bitcoin chains.** WalletExplorer is Bitcoin only, so this is BTC only in
  v1. Ethereum and other chains are a later enhancement.
- **No identity claims.** Attribution is a lead. Identity needs lawful off-chain data.

## Deeper reference

For the full WalletExplorer API schema (all ten endpoints and their response shapes),
the complete category map and how to extend it, the trace-tuning notes, the
peel-chain heuristic, and the copy-paste evidence recipe, read
`${CLAUDE_PLUGIN_ROOT}/skills/crypto-trace/references/tradecraft.md`.
