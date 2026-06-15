# Bitcoin tracing tradecraft & WalletExplorer API reference

The "how it actually works" reference for `wxtrace.py`. Read it when tuning a trace,
extending the category map, adding the evidence step, or explaining the method.

## Contents

1. The core idea
2. The WalletExplorer API (all ten endpoints)
3. Verified response shapes
4. Attribution and the category map
5. The forward trace algorithm
6. Pattern detection (peel chains, mixers)
7. Backward tracing (shallow, and the planned deep version)
8. Rate limiting and politeness
9. The evidence recipe (trace JSON to a case file)
10. Limits and honesty

## 1. The core idea

A Bitcoin trace does not "search" anything. The ledger is public and complete. The
craft is two things. First, **attribution**: deciding which real-world service, if
any, controls an address, using the wallet clustering that WalletExplorer has already
done (common-input-ownership and change heuristics group addresses into wallets, and
many wallets are labeled with the service that operates them). Second, **following
the flow**: each transaction output records the transaction that later spent it
(`next_tx`), so you can walk the money forward hop by hop until it lands somewhere
known.

The goal of a forward trace is a **cash-out point**, an exchange or other regulated
service where the coins entered an account that did KYC. That service is the off-chain
pivot. A subpoena to it can attach a real identity to the chain. On-chain analysis
gets you to the door. The subpoena opens it.

## 2. The WalletExplorer API (all ten endpoints)

Base URL: `https://www.walletexplorer.com/api/1/`. JSON responses. No API key. Every
response carries `"found": true|false`, or `"error": "..."` on bad input. All query
parameters are mandatory.

| # | Endpoint | Parameters | Purpose |
| - | -------- | ---------- | ------- |
| 1 | `tx` | `txid` | Transaction detail. The tracing workhorse (carries `next_tx`). |
| 2 | `address` | `address`, `from`, `count` | Transactions for one address (paginated). |
| 3 | `address-lookup` | `address` | Which wallet/service an address belongs to. The attribution primitive. |
| 4 | `addresses-lookup` | `addresses` (comma list) | Batch version of address-lookup. |
| 5 | `wallet` | `wallet`, `from`, `count` | Transactions of a wallet cluster (paginated). |
| 6 | `wallet-addresses` | `wallet`, `from`, `count` | Addresses in a wallet cluster (paginated). |
| 7 | `firstbits` | `prefix` | First address in the chain matching a prefix. |
| 8 | `alternatives` | `service` | Alternative label names for a service (canonicalize). |
| 9 | `xpub-addresses` | `pub`, `gap_limit` | Addresses seen for an extended public key. |
| 10 | `xpub-txs` | `pub`, `gap_limit` | Transactions across all addresses of an xpub. |

Parameter rules, enforced client-side by `wxtrace.py` before the call:

- `from` starts at 0 and must be divisible by 100 (WalletExplorer stores fixed
  indexes in its data files).
- `count` is 0 to 1000 inclusive.
- `wallet` accepts a hex id, a label, or a label variant (for example `bitstamp`
  resolves "Bitstamp.net").
- `gap_limit` is 1 to 200 (wallets usually use 20).

## 3. Verified response shapes

Confirmed against live calls. Rely on these; re-confirm if WalletExplorer changes.

**`address-lookup`** returns the cluster label and id. An unlabeled address returns
`found: true` with a hex `wallet_id` and no `label` (a private cluster). An unknown
address returns `found: false`.

```json
{"found": true, "label": "BTC-e.com", "wallet_id": "000003a2f31608c0", "updated_to_block": 953005}
```

**`addresses-lookup`** returns a map. Addresses that are not known are simply absent
from the map. A present entry without a `label` is a private cluster.

```json
{"found": true,
 "existing_addresses_to_wallet_id": {
   "16SbwNa22nBwhLtg6HzWVYFQiUxtNzAUpt": {"label": "BTC-e.com", "wallet_id": "000003a2f31608c0"},
   "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa": {"wallet_id": "9155adea5d855091"}
 },
 "updated_to_block": 953683}
```

**`tx`** returns inputs and outputs. Each output carries `next_tx`, the transaction
that later spent it, which is what lets you walk forward. `label` is present only when
the destination is a known service. `time` is a Unix timestamp; convert to UTC for the
report.

```json
{
  "found": true, "label": "Cex.io", "txid": "99fd988b...3ba7",
  "wallet_id": "0000d93360a82dd9", "block_height": 348151, "time": 1426693081,
  "in":  [{"address": "1KT9...Z5L", "amount": 0.2, "is_standard": true, "next_tx": "36b9...9244"}],
  "out": [
    {"address": "115Z...oxb", "wallet_id": "00000755defaf057", "amount": 0.07608991, "next_tx": "e651...2936", "label": "Cryptsy.com"},
    {"address": "1F3k...tGa", "wallet_id": "0000d93360a82dd9", "amount": 0.12381009, "next_tx": "300f...c987", "label": "Cex.io"}
  ],
  "is_coinbase": false, "updated_to_block": 951606
}
```

Key output fields: `address`, `wallet_id`, `amount` (BTC), `label` (only for a known
service), `next_tx` (only when the output was later spent; absent means unspent, so
funds rest there).

**`address`** returns the address's transactions. `used_as_input: true` marks a
transaction where the address **spent** funds, which is what the forward trace seeds
from. `used_as_output: true` marks one where it received.

```json
{"found": true, "label": "BTC-e.com", "address": "16Sbw...Upt", "wallet_id": "000003a2f31608c0",
 "txs_count": 962,
 "txs": [{"txid": "c95f...6089", "amount_sent": 0.065, "amount_received": 0, "block_height": 408879,
          "time": 1461604370, "balance": 0, "used_as_input": true, "used_as_output": false}],
 "updated_to_block": 953683}
```

**`wallet`** returns a cluster's transactions. Each row has `type`
(`received`/`sent`), the counterparty `wallet_id`, and `amount` (may be null on some
sent rows).

```json
{"found": true, "label": "BTC-e.com", "wallet_id": "000003a2f31608c0", "txs_count": 2583686,
 "txs": [{"txid": "6d87...823d", "block_height": 949195, "time": 1778666344, "balance": 0.00698355,
          "type": "received", "wallet_id": "00001abcaeb15e08", "amount": 0.00218}],
 "updated_to_block": 953683}
```

**`wallet-addresses`** returns a cluster's addresses.

```json
{"found": true, "label": "BTC-e.com", "wallet_id": "000003a2f31608c0", "addresses_count": 307511,
 "addresses": [{"address": "1GqM...7fK5", "balance": 0.00439259, "incoming_txs": 12,
                "last_used_in_block": 944880, "is_standard": true}],
 "updated_to_block": 953683}
```

`firstbits`, `alternatives`, `xpub-addresses`, and `xpub-txs` are wired in the client
but used less often. Confirm their exact shapes on first live use and adjust the
renderer if needed; the client already parses and guards them.

## 4. Attribution and the category map

`classify(label)` maps a service label to a conservative category by **lowercase
substring match**, in this order (specific brands before generic words). The map lives
in `scripts/wxtrace.py` as `CATEGORY_MAP` and is meant to be extended. To add a
service, drop a keyword into the right list.

| Category | Match keywords (substring, lowercase) |
| --- | --- |
| `exchange` | coinbase, binance, bitstamp, kraken, bitfinex, cex.io, btc-e, huobi, okx, okex, kucoin, gemini, poloniex, bittrex, localbitcoins, bithumb, cryptsy, mtgox |
| `mixer` | mixer, tumbler, helix, chipmixer, bitmixer, bestmixer, coinjoin, wasabi, blender, whirlpool, bitcoin fog |
| `market` | market, alphabay, hydra, silk road, silkroad, darknet, hansa, dream market, agora, nucleus, abraxas |
| `gambling` | casino, dice, satoshidice, poker, gambl, betting, sportsbet, 999dice, primedice, betcoin |
| `pool` | pool, mining, miner, slush, antpool, ghash |
| `service` | wallet, faucet, payment, escrow, processor, merchant, bitpay, coinpayments |

Two fallbacks that are not guesses:

- A label that matches nothing is `named-service`. You know a service controls it, you
  just have not categorized it. Still a strong lead.
- An address with no label at all is a `private-cluster`. A wallet WalletExplorer has
  not attributed.

Substring matching is a deliberate trade. It is permissive (it catches "Binance.com",
"Binance 2", "Binance-cold" with one keyword) at the cost of rare false hits (a
service with "bet" in an unrelated name). Because every result is framed as a lead,
not proof, a permissive category that an analyst confirms is the right default. When
in doubt, `--canonicalize` resolves the label through the `alternatives` endpoint
first, which collapses label variants to one canonical name before categorizing.

## 5. The forward trace algorithm

Forward tracing answers "where did the money go". It is a breadth-first walk from the
seed, attributing every hop and stopping at known services or a depth limit.

```
seed:
  --txid TXID         -> seed = [TXID]
  --address ADDR      -> seed = txids where ADDR is an input (used_as_input: true)
  push each seed as (txid, depth=0, path=[txid])

visited = set()       # txids already expanded, stops cycles
nodes   = {}          # address -> {label, category, total_received, first/last_seen, url}
edges   = []          # {txid, from_addr, to_addr, to_wallet, to_label, amount_btc, time_utc, urls}
endpoints = []        # services reached + unspent holdings

while queue and len(visited) < max_nodes:
  (txid, depth, path) = queue.popleft()
  if txid in visited: continue
  visited.add(txid)
  tx = GET tx?txid=txid           # serial, with delay + backoff
  for output in tx.out:
    record node + edge, classify(output.label)
    if output.label:                      # reached a named service
        endpoints.append(... reason="named-service")
        if stop_at_service: do not expand past it      # coins commingle here
        elif output.next_tx and depth < max_depth: enqueue(next_tx)
    else:                                  # unlabeled private cluster
        if not output.next_tx:             # unspent: funds rest here
            endpoints.append(... reason="unspent-holding")
        elif output.amount < min_amount:   # dust filter
            record truncation
        elif depth >= max_depth:           # hop limit
            record truncation
        else:
            enqueue((output.next_tx, depth+1, path+[next_tx]))
```

Tuning the guards:

- **`--max-depth` (12).** Most cash-outs are within a handful of hops. Raise it for a
  long layering chain, but expect more `truncations` and a bigger graph.
- **`--max-nodes` (500).** The hard stop on graph explosion. When it trips, the trace
  flags `node-cap-reached` so you know the picture is partial. Raise it deliberately.
- **`--min-amount` (0.0001).** Do not chase dust. Attackers sometimes spray tiny
  outputs to pad the graph; this skips them.
- **`--stop-at-service` (true).** The most important one. Once funds enter an exchange
  they mix with every other customer's coins, so an output from the exchange is not
  "the same money". Stopping there is correct. Set it false only to study an exchange's
  own outbound behavior, knowing the link is no longer clean.

## 6. Pattern detection

**Peel chain.** A peel chain launders a large sum by peeling a little off at a time.
At each hop the transaction sends most of the value onward to one address and a smaller
"change" amount continues the chain, over and over. The heuristic: a hop is a peel step
when the transaction has two or more outputs and the output the trace follows is a
minority (half or less) of the total spent. A run of four or more consecutive peel
steps is flagged with the path and its length. Tune the threshold in
`trace_forward(peel_threshold=...)`.

**Mixer or tumbler hop.** Any endpoint whose category is `mixer` is flagged as an
obfuscation point. A mixer deliberately breaks the link between input and output, so
on-chain tracing past it is unreliable. Record it, note that the trail likely ends
there on-chain, and pivot to off-chain leads (timing analysis, amounts, or the service's
own records by subpoena).

## 7. Backward tracing

Backward tracing answers "where did the money come from". `--direction backward` is
implemented as a **shallow** version: it attributes every input address of the seed
transaction (one batched `addresses-lookup`) and optionally follows one hop back to
the transaction that produced each input. That is enough to answer "who funded this"
when the funder is a known service.

Deep backward tracing (recursively walking every funding path, which fans out fast
because a transaction can have many inputs each with their own history) is a planned
later enhancement. It needs the same guards as forward plus careful handling of the
fan-out, so it is intentionally not enabled in v1. Say so plainly rather than implying
the shallow version is exhaustive.

## 8. Rate limiting and politeness

WalletExplorer documents no hard limit today but says limits may apply, that exceeding
them returns HTTP 429 and a short ban, and that the rule of thumb is to back off harder
when the server errors. `wxtrace.py` is built as a polite single-host client, which is
different from the username engine that spreads across many hosts:

- **Serial requests.** Never concurrent. One server, one visitor.
- **Fixed delay.** `--delay` (default 0.5s) pauses before every request, about two per
  second.
- **Exponential backoff with jitter.** On 429 or 5xx the client waits 2, 4, 8, 16, 32
  seconds (capped), adding a little random jitter, up to `--max-retries` (default 5).
  A `Retry-After` header, when present, overrides the computed wait.
- **Global request cap.** `--max-requests` (default 2000) stops a runaway trace from
  hammering the host. Reaching it raises a clean error, not a crash.

Do not raise these to push throughput. A short ban costs more time than the delay
saves, and abusing a free public service is not acceptable tradecraft.

## 9. The evidence recipe (trace JSON to a case file)

Reuse **evidence-report**. Do not rebuild it. Run a trace with `--format json`, then
map its endpoints into the plugin's case-file schema and hand that to the unchanged
`build_report.py`. This snippet is the bridge; run it verbatim and adjust the case
header.

```python
import json, datetime

tr = json.load(open("trace.json"))   # output of: wxtrace.py trace ... --format json --out trace.json

def confidence(cat):
    return {"exchange": "high (service cluster)",
            "mixer": "high (service cluster)",
            "market": "high (service cluster)",
            "named-service": "medium (labeled, uncategorized)"
            }.get(cat, "low (unattributed cluster)")

findings = [{
    "site": "WalletExplorer", "category": "crypto", "status": "origin",
    "profile_url": tr["origin"]["url"], "captured_at": tr["generated_utc"],
    "method": "walletexplorer-api", "page_title": "Trace origin " + tr["origin"]["type"],
    "notes": "Origin of the forward trace (" + tr["origin"]["type"] + ").",
}]
for e in tr["endpoints"]:
    findings.append({
        "site": "WalletExplorer",
        "category": e["category"],
        "status": "attributed" if e.get("label") else "unlabeled",
        "profile_url": e.get("address_url") or e.get("wallet_url"),
        "captured_at": e.get("time_utc") or tr["generated_utc"],
        "method": "walletexplorer-api",
        "page_title": e.get("label") or "private cluster",
        "notes": "%s BTC; reason=%s; %d hops from origin; attribution=%s; confidence=%s; LEAD not proof" % (
            e["amount_btc"], e["reason"], len(e.get("path", [])),
            e.get("label") or "unlabeled cluster", confidence(e["category"])),
    })

case = {"schema": "1.0",
        "case": {"title": "Bitcoin trace from %s" % tr["origin"]["value"][:16],
                 "case_id": "CASE-CRYPTO-001", "investigator": "Not provided",
                 "subject": tr["origin"]["value"],
                 "authorization": "Authorized investigation (public ledger)",
                 "opened": datetime.date.today().isoformat()},
        "findings": findings}
json.dump(case, open("case.json", "w"), indent=2)
```

Then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/evidence-report/scripts/build_report.py" \
    case.json --out "Evidence_<subject>.html"
```

For visual evidence on the high-value endpoints (the cash-out exchange, any mixer, the
origin), follow **evidence-report**'s Playwright capture: navigate to the
`profile_url`, confirm the title and URL, screenshot to `evidence/<case-id>/<name>.png`,
add that path to the finding's `screenshot` field, and let `build_report.py` embed it
and hash it. Same bot-challenge policy as the rest of the plugin. Never auto-bypass a
challenge.

## 10. Limits and honesty

- **Bitcoin only.** WalletExplorer is a BTC explorer. No Ethereum, no other chains, in
  v1.
- **Attribution is a lead.** A wallet label says which service clustering thinks owns an
  address. It is strong signal, not proof, and clustering can be wrong. Identity comes
  from off-chain data obtained lawfully.
- **Coverage and freshness.** WalletExplorer's labels are good for older and major
  services and thinner for new ones. An unlabeled cluster is not "clean", just
  unattributed by this source. A commercial platform may label it.
- **Mixers end the clean trail.** Past a mixer, treat on-chain continuations as
  unproven.
- **This is a first pass.** It is the free baseline before a paid platform, and a strong
  partner to the username and email findings, not a replacement for either.
