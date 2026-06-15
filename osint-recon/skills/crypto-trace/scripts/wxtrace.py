#!/usr/bin/env python3
"""
osint-recon : wxtrace.py
========================

A dependency-free Bitcoin tracing and attribution engine built on the public
WalletExplorer API (https://www.walletexplorer.com/). It reads the same public
ledger anyone can see on a block explorer: it attributes addresses and wallet
clusters to known services, fetches transactions, and follows the flow of funds
forward ("follow the money") until it reaches a known service (an exchange, a
mixer, a market) or a depth limit.

This script intentionally uses ONLY the Python standard library so it runs
anywhere Python 3.8+ is installed -- no `pip install` required.

Subcommands
-----------
  lookup            Attribute one or many addresses to a wallet/service + category.
  tx                Fetch and pretty-print one transaction (inputs, outputs, next_tx).
  address           List an address's transactions (paginated).
  wallet            List a wallet cluster's transactions (paginated).
  wallet-addresses  List the addresses in a wallet cluster (paginated).
  trace             Forward-trace the flow of funds from a txid or address.

Run `python3 wxtrace.py --help` or `python3 wxtrace.py trace --help` for usage.

This is Bitcoin only (WalletExplorer covers BTC). It is a free first-pass
investigator, not a replacement for a commercial platform like Chainalysis or
TRM. Attribution here is a LEAD with a stated confidence, never proof of who
controls a wallet. Identity comes from lawful off-chain data (a KYC subpoena to
an exchange, a matched forum post, breach data).

Authorized use only. Trace stolen or defrauded funds, ransomware/incident
response, sanctions and compliance screening, your own wallets, or consented
investigations. Do not use this to dox or locate a private individual without a
lawful basis. Respect WalletExplorer's rate limits (this client is deliberately
a polite, serial, single-host client; see the backoff logic below).
"""

import argparse
import csv
import io
import json
import os
import random
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from time import monotonic, sleep

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

API_BASE = "https://www.walletexplorer.com/api/1/"
WEB_BASE = "https://www.walletexplorer.com"

# A current, real browser User-Agent. WalletExplorer serves JSON to the API, but
# presenting a modern browser identity (the way hunt.py does) avoids stale-client
# handling and keeps us indistinguishable from an analyst opening the site.
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)

# A real browser never sends User-Agent alone. These are the headers a browser
# attaches to a same-origin fetch of a JSON endpoint.
BASE_HEADERS = {
    "Accept": "application/json,text/javascript,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",  # ask for uncompressed JSON; stdlib won't gunzip for us here
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Category map: classify a service LABEL into a conservative category by
# lowercase substring match. Order matters (specific brands before generic
# words). Anything labeled but unmatched is "named-service"; an address with no
# label is a "private-cluster". This is intentionally easy to extend -- the
# canonical, documented copy lives in references/tradecraft.md. Do not overclaim;
# an uncategorized label is still a useful lead.
CATEGORY_MAP = [
    ("exchange", [
        "coinbase", "binance", "bitstamp", "kraken", "bitfinex", "cex.io",
        "btc-e", "huobi", "okx", "okex", "kucoin", "gemini", "poloniex",
        "bittrex", "localbitcoins", "bithumb", "cryptsy", "mtgox", "mt.gox",
    ]),
    ("mixer", [
        "mixer", "tumbler", "helix", "chipmixer", "bitmixer", "bestmixer",
        "coinjoin", "wasabi", "blender", "whirlpool", "bitcoinfog", "bitcoin fog",
    ]),
    ("market", [
        "market", "alphabay", "hydra", "silk road", "silkroad", "darknet",
        "hansa", "dream market", "agora", "nucleus", "abraxas",
    ]),
    ("gambling", [
        "casino", "dice", "satoshidice", "poker", "gambl", "betting", "sportsbet",
        "999dice", "luckygames", "primedice", "betcoin",
    ]),
    ("pool", ["pool", "mining", "miner", "slush", "antpool", "ghash"]),
    ("service", [
        "wallet", "faucet", "payment", "escrow", "processor", "merchant",
        "bitpay", "coinpayments",
    ]),
]

CAT_PRIVATE = "private-cluster"   # an address with no service label
CAT_NAMED = "named-service"       # labeled, but not matched to a known category


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class WalletExplorerError(Exception):
    """Any failure talking to WalletExplorer."""


class RateLimitError(WalletExplorerError):
    """Repeated 429/5xx after exhausting backoff retries."""


class RequestCapError(WalletExplorerError):
    """The per-run global request cap was reached (a runaway-trace guard)."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def iso_utc(ts):
    """Unix timestamp -> ISO 8601 UTC string (the report wants UTC)."""
    if ts in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, OverflowError):
        return None


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def addr_url(address):
    return "{}/address/{}".format(WEB_BASE, address)


def tx_url(txid):
    return "{}/txid/{}".format(WEB_BASE, txid)


def wallet_url(wallet_id):
    return "{}/wallet/{}".format(WEB_BASE, wallet_id)


def classify(label):
    """Map a service label to a conservative category by substring match.

    No label -> private-cluster (an unattributed address). Labeled but unmatched
    -> named-service (still a lead; we just don't claim a category).
    """
    if not label:
        return CAT_PRIVATE
    low = label.lower()
    for category, needles in CATEGORY_MAP:
        if any(n in low for n in needles):
            return category
    return CAT_NAMED


def short(value, head=8, tail=6):
    """Abbreviate a long hash/address for human-readable console/markdown output."""
    if not value or len(value) <= head + tail + 1:
        return value or ""
    return "{}...{}".format(value[:head], value[-tail:])


# --------------------------------------------------------------------------- #
# WalletExplorer client (polite, serial, single host)
# --------------------------------------------------------------------------- #

class WalletExplorerClient:
    """A deliberately polite client for ONE host (walletexplorer.com).

    Unlike the username engine, which fans out across hundreds of independent
    hosts, this talks to a single server, so it must behave like a single
    well-mannered visitor:

      * Serial requests (never concurrent).
      * A fixed `delay` before every request (default 0.5s, ~2 req/s).
      * Exponential backoff with jitter on 429 / 5xx (2, 4, 8, 16, 32s),
        honoring a Retry-After header when present, up to `max_retries`.
      * A global `max_requests` cap so a runaway trace can't hammer the host.

    The sleep function and backoff base are injectable so tests can exercise the
    backoff path quickly and deterministically.
    """

    def __init__(self, delay=0.5, max_retries=5, max_requests=2000, timeout=30,
                 proxy=None, verify=True, user_agent=None, base_url=API_BASE,
                 backoff_base=2.0, backoff_cap=32.0, jitter=0.3, sleep_fn=sleep,
                 verbose=False):
        self.delay = max(0.0, float(delay))
        self.max_retries = max(0, int(max_retries))
        self.max_requests = max(1, int(max_requests))
        self.timeout = float(timeout)
        self.base_url = base_url
        self.backoff_base = float(backoff_base)
        self.backoff_cap = float(backoff_cap)
        self.jitter = float(jitter)
        self._sleep = sleep_fn
        self.verbose = verbose
        self.user_agent = user_agent or DEFAULT_UA
        self.requests_made = 0

        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler(
                {"http": proxy, "https": proxy}))
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self._opener = urllib.request.build_opener(*handlers)

    # -- low level ---------------------------------------------------------- #

    def _retry_after(self, exc):
        """Seconds from a Retry-After header, if present and numeric."""
        try:
            val = exc.headers.get("Retry-After")
        except Exception:
            return None
        if not val:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None  # HTTP-date form is rare here; fall back to backoff

    def _request(self, endpoint, params):
        """GET `endpoint` with `params`, returning parsed JSON (a dict).

        Retries 429/5xx and transient transport errors with exponential backoff.
        A real, non-rate-limit HTTP response (including a JSON {"error": ...}) is
        returned to the caller rather than retried.
        """
        url = self.base_url + endpoint + "?" + urllib.parse.urlencode(params)
        backoff = self.backoff_base
        last_err = None
        for attempt in range(self.max_retries + 1):
            if self.requests_made >= self.max_requests:
                raise RequestCapError(
                    "request cap reached ({}); raise --max-requests if a larger "
                    "trace is justified".format(self.max_requests))
            if self.delay:
                self._sleep(self.delay)
            self.requests_made += 1
            try:
                req = urllib.request.Request(
                    url=url, headers=dict(BASE_HEADERS, **{"User-Agent": self.user_agent}))
                resp = self._opener.open(req, timeout=self.timeout)
                raw = resp.read()
                return self._parse(raw)
            except urllib.error.HTTPError as e:
                if e.code == 429 or 500 <= e.code < 600:
                    last_err = RateLimitError(
                        "HTTP {} from WalletExplorer (rate limited / server "
                        "error)".format(e.code))
                    if attempt < self.max_retries:
                        wait = self._retry_after(e)
                        if wait is None:
                            wait = min(backoff, self.backoff_cap)
                        wait += random.uniform(0, self.jitter)
                        if self.verbose:
                            sys.stderr.write(
                                "[wxtrace] {} -> backing off {:.1f}s "
                                "(attempt {}/{})\n".format(
                                    e.code, wait, attempt + 1, self.max_retries))
                        self._sleep(wait)
                        backoff = min(backoff * 2, self.backoff_cap)
                        continue
                    raise last_err
                # Other 4xx: a real response. WalletExplorer usually answers 200
                # with {"error": ...} for bad input, but be defensive.
                try:
                    return self._parse(e.read())
                except Exception:
                    raise WalletExplorerError(
                        "HTTP {} from WalletExplorer".format(e.code))
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    ssl.SSLError) as e:
                last_err = WalletExplorerError("network error: {}".format(e))
                if attempt < self.max_retries:
                    wait = min(backoff, self.backoff_cap) + random.uniform(0, self.jitter)
                    if self.verbose:
                        sys.stderr.write(
                            "[wxtrace] transport error -> retry in {:.1f}s "
                            "({}/{})\n".format(wait, attempt + 1, self.max_retries))
                    self._sleep(wait)
                    backoff = min(backoff * 2, self.backoff_cap)
                    continue
                raise last_err
        raise last_err or WalletExplorerError("request failed")

    @staticmethod
    def _parse(raw_bytes):
        if not raw_bytes:
            return {}
        text = raw_bytes.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise WalletExplorerError("non-JSON response: {}".format(text[:200])) from e

    @staticmethod
    def _guard(data):
        """Surface a WalletExplorer {"error": ...} as an exception."""
        if isinstance(data, dict) and data.get("error"):
            raise WalletExplorerError(data["error"])
        return data

    # -- parameter validation ---------------------------------------------- #

    @staticmethod
    def _check_from(frm):
        frm = int(frm)
        if frm < 0 or frm % 100 != 0:
            raise ValueError("--from must be >= 0 and divisible by 100 "
                             "(WalletExplorer uses fixed indexes)")
        return frm

    @staticmethod
    def _check_count(count):
        count = int(count)
        if not (0 <= count <= 1000):
            raise ValueError("--count must be between 0 and 1000")
        return count

    @staticmethod
    def _check_gap(gap):
        gap = int(gap)
        if not (1 <= gap <= 200):
            raise ValueError("gap_limit must be between 1 and 200")
        return gap

    # -- endpoints ---------------------------------------------------------- #

    def tx(self, txid):
        return self._guard(self._request("tx", {"txid": txid}))

    def address(self, address, frm=0, count=100):
        return self._guard(self._request("address", {
            "address": address,
            "from": self._check_from(frm),
            "count": self._check_count(count),
        }))

    def address_lookup(self, address):
        return self._guard(self._request("address-lookup", {"address": address}))

    def addresses_lookup(self, addresses):
        joined = ",".join(addresses)
        return self._guard(self._request("addresses-lookup", {"addresses": joined}))

    def wallet(self, wallet_id, frm=0, count=100):
        return self._guard(self._request("wallet", {
            "wallet": wallet_id,
            "from": self._check_from(frm),
            "count": self._check_count(count),
        }))

    def wallet_addresses(self, wallet_id, frm=0, count=100):
        return self._guard(self._request("wallet-addresses", {
            "wallet": wallet_id,
            "from": self._check_from(frm),
            "count": self._check_count(count),
        }))

    def firstbits(self, prefix):
        return self._guard(self._request("firstbits", {"prefix": prefix}))

    def alternatives(self, service):
        return self._guard(self._request("alternatives", {"service": service}))

    def xpub_addresses(self, pub, gap_limit=20):
        return self._guard(self._request("xpub-addresses", {
            "pub": pub, "gap_limit": self._check_gap(gap_limit)}))

    def xpub_txs(self, pub, gap_limit=20):
        return self._guard(self._request("xpub-txs", {
            "pub": pub, "gap_limit": self._check_gap(gap_limit)}))


# --------------------------------------------------------------------------- #
# Service-name canonicalization (optional, off by default)
# --------------------------------------------------------------------------- #

def canonicalize_label(client, label, cache):
    """Resolve a label to its canonical service name via `alternatives`.

    Off by default; the trace passes a cache so each label is resolved once.
    Defensive: any failure falls back to the original label.
    """
    if not label:
        return label
    if label in cache:
        return cache[label]
    canonical = label
    try:
        data = client.alternatives(label)
        # Shape is confirmed on first live use; accept a few plausible forms.
        if isinstance(data, dict):
            for key in ("label", "service", "name", "canonical"):
                if data.get(key):
                    canonical = data[key]
                    break
            else:
                alts = data.get("alternatives") or data.get("services")
                if isinstance(alts, list) and alts:
                    first = alts[0]
                    canonical = first.get("label", label) if isinstance(first, dict) else first
    except WalletExplorerError:
        pass
    cache[label] = canonical
    return canonical


# --------------------------------------------------------------------------- #
# Node / endpoint bookkeeping for the trace
# --------------------------------------------------------------------------- #

def record_node(nodes, address, wallet_id, label, category, amount, time_utc):
    """Accumulate per-address state across the trace."""
    n = nodes.get(address)
    if n is None:
        n = {
            "address": address,
            "wallet_id": wallet_id,
            "label": label,
            "category": category,
            "total_received_btc": 0.0,
            "times_seen": 0,
            "first_seen_utc": time_utc,
            "last_seen_utc": time_utc,
            "url": addr_url(address),
        }
        nodes[address] = n
    n["total_received_btc"] = round(n["total_received_btc"] + (amount or 0), 8)
    n["times_seen"] += 1
    if time_utc:
        if not n["first_seen_utc"] or time_utc < n["first_seen_utc"]:
            n["first_seen_utc"] = time_utc
        if not n["last_seen_utc"] or time_utc > n["last_seen_utc"]:
            n["last_seen_utc"] = time_utc
    # Prefer a label/wallet if we learn one later.
    if label and not n.get("label"):
        n["label"] = label
        n["category"] = category
    if wallet_id and not n.get("wallet_id"):
        n["wallet_id"] = wallet_id
    return n


# --------------------------------------------------------------------------- #
# The trace (forward "follow the money", plus a shallow backward attribution)
# --------------------------------------------------------------------------- #

def trace_forward(client, seed_txids, origin, max_depth=12, max_nodes=500,
                  min_amount=0.0001, stop_at_service=True, peel_threshold=4,
                  canonicalize=False):
    """Walk forward from seed transactions, attributing every hop.

    Returns the full result dict (origin, summary, nodes, edges, endpoints,
    paths, patterns_flagged, generated_utc).
    """
    visited = set()
    nodes = {}
    edges = []
    endpoints = []
    paths = []
    truncations = []
    patterns = []
    cache = {}
    max_depth_reached = 0
    deepest_peel = {"length": 0, "path": []}

    queue = deque()
    for t in seed_txids:
        queue.append((t, 0, [t], 0))

    while queue and len(visited) < max_nodes:
        txid, depth, path, peel_run = queue.popleft()
        if txid in visited:
            continue
        visited.add(txid)
        max_depth_reached = max(max_depth_reached, depth)

        try:
            tx = client.tx(txid)
        except WalletExplorerError as e:
            truncations.append({"txid": txid, "reason": "fetch-failed: {}".format(e),
                                "url": tx_url(txid)})
            continue
        if not tx.get("found"):
            truncations.append({"txid": txid, "reason": "tx not found",
                                "url": tx_url(txid)})
            continue

        time_utc = iso_utc(tx.get("time"))
        outs = tx.get("out", []) or []
        ins = tx.get("in", []) or []
        from_addr = ins[0].get("address") if ins else None
        total_out = sum((o.get("amount") or 0) for o in outs)

        for o in outs:
            address = o.get("address")
            wallet_id = o.get("wallet_id")
            label = o.get("label")
            amount = o.get("amount") or 0
            nxt = o.get("next_tx")

            if canonicalize and label:
                label = canonicalize_label(client, label, cache)
            category = classify(label)

            record_node(nodes, address, wallet_id, label, category, amount, time_utc)
            edges.append({
                "txid": txid,
                "from_addr": from_addr,
                "to_addr": address,
                "to_wallet": wallet_id,
                "to_label": label,
                "category": category,
                "amount_btc": round(amount, 8),
                "time_utc": time_utc,
                "tx_url": tx_url(txid),
                "to_url": addr_url(address) if address else None,
            })

            if label:
                # Reached a named service: a stopping point. Past an exchange the
                # coins are commingled, so following further is meaningless
                # without a subpoena.
                ep = {
                    "address": address,
                    "wallet_id": wallet_id,
                    "label": label,
                    "category": category,
                    "amount_btc": round(amount, 8),
                    "time_utc": time_utc,
                    "reason": "named-service",
                    "depth": depth,
                    "path": path,
                    "address_url": addr_url(address) if address else None,
                    "wallet_url": wallet_url(wallet_id) if wallet_id else None,
                }
                endpoints.append(ep)
                paths.append({"to": label, "category": category,
                              "amount_btc": round(amount, 8), "hops": len(path),
                              "txids": path})
                if not stop_at_service and nxt and depth < max_depth:
                    queue.append((nxt, depth + 1, path + [nxt], 0))
            else:
                # Unlabeled private cluster.
                if not nxt:
                    # Output never spent: funds came to rest here. A real lead --
                    # this address may still hold the coins.
                    ep = {
                        "address": address,
                        "wallet_id": wallet_id,
                        "label": None,
                        "category": CAT_PRIVATE,
                        "amount_btc": round(amount, 8),
                        "time_utc": time_utc,
                        "reason": "unspent-holding",
                        "depth": depth,
                        "path": path,
                        "address_url": addr_url(address) if address else None,
                        "wallet_url": wallet_url(wallet_id) if wallet_id else None,
                    }
                    endpoints.append(ep)
                elif amount < min_amount:
                    truncations.append({"txid": txid, "reason": "below-min-amount",
                                        "amount_btc": round(amount, 8),
                                        "url": tx_url(txid)})
                elif depth >= max_depth:
                    truncations.append({"txid": txid, "reason": "max-depth-reached",
                                        "url": tx_url(txid)})
                else:
                    # Peel-chain heuristic: a peel step is a tx with >=2 outputs
                    # where the output we follow (the "change") is a minority of
                    # the total spent -- the rest was peeled off to a payee/service.
                    is_peel = len(outs) >= 2 and total_out > 0 and amount <= 0.5 * total_out
                    new_run = peel_run + 1 if is_peel else 0
                    if new_run > deepest_peel["length"]:
                        deepest_peel = {"length": new_run, "path": path + [nxt]}
                    queue.append((nxt, depth + 1, path + [nxt], new_run))

    # ---- patterns ---- #
    if deepest_peel["length"] >= peel_threshold:
        patterns.append({
            "type": "peel-chain",
            "detail": ("A peel chain of {} consecutive change-hops was followed. "
                       "One output is peeled off at each hop while a shrinking "
                       "change output keeps moving -- a common layering pattern."
                       ).format(deepest_peel["length"]),
            "length": deepest_peel["length"],
            "txids": deepest_peel["path"],
        })
    mixer_eps = [e for e in endpoints if e["category"] == "mixer"]
    for m in mixer_eps:
        patterns.append({
            "type": "mixer-hop",
            "detail": ("Funds reached '{}', classified as a mixer/tumbler. This is "
                       "an obfuscation point; the on-chain link very likely breaks "
                       "here and tracing past it is unreliable without off-chain "
                       "data.").format(m["label"]),
            "label": m["label"],
            "address": m["address"],
            "amount_btc": m["amount_btc"],
        })
    if len(visited) >= max_nodes:
        patterns.append({
            "type": "node-cap-reached",
            "detail": ("Stopped after expanding {} transactions (--max-nodes). The "
                       "graph may be incomplete; raise --max-nodes for a deeper "
                       "trace.").format(max_nodes),
        })

    # ---- summary ---- #
    cashouts = [e for e in endpoints if e["category"] == "exchange"]
    by_category = {}
    for e in endpoints:
        by_category.setdefault(e["category"], {"count": 0, "amount_btc": 0.0})
        by_category[e["category"]]["count"] += 1
        by_category[e["category"]]["amount_btc"] = round(
            by_category[e["category"]]["amount_btc"] + e["amount_btc"], 8)

    summary = {
        "txs_expanded": len(visited),
        "max_depth_reached": max_depth_reached,
        "nodes_seen": len(nodes),
        "edges": len(edges),
        "endpoints": len(endpoints),
        "services_reached": len([e for e in endpoints if e["label"]]),
        "cashout_candidates": len(cashouts),
        "by_category": by_category,
        "stopped_at_service": stop_at_service,
    }

    return {
        "origin": origin,
        "direction": "forward",
        "summary": summary,
        "nodes": list(nodes.values()),
        "edges": edges,
        "endpoints": endpoints,
        "cashout_candidates": cashouts,
        "paths": paths,
        "truncations": truncations,
        "patterns_flagged": patterns,
        "generated_utc": now_utc(),
    }


def trace_backward(client, txid, origin, one_hop=True, canonicalize=False):
    """Shallow backward attribution: attribute the inputs that funded `txid`.

    Deep backward tracing (recursively walking every funding path) is a planned
    enhancement; this version attributes each input address and, optionally,
    follows ONE hop back to the transaction that produced each input.
    """
    nodes = {}
    edges = []
    sources = []
    cache = {}

    tx = client.tx(txid)
    if not tx.get("found"):
        raise WalletExplorerError("transaction not found: {}".format(txid))
    time_utc = iso_utc(tx.get("time"))
    ins = tx.get("in", []) or []

    in_addrs = [i.get("address") for i in ins if i.get("address")]
    lookups = {}
    if in_addrs:
        try:
            data = client.addresses_lookup(in_addrs)
            lookups = data.get("existing_addresses_to_wallet_id", {}) or {}
        except WalletExplorerError:
            lookups = {}

    for i in ins:
        address = i.get("address")
        amount = i.get("amount") or 0
        meta = lookups.get(address, {}) if address else {}
        label = meta.get("label")
        wallet_id = meta.get("wallet_id")
        if canonicalize and label:
            label = canonicalize_label(client, label, cache)
        category = classify(label)
        record_node(nodes, address, wallet_id, label, category, amount, time_utc)
        src = {
            "address": address,
            "wallet_id": wallet_id,
            "label": label,
            "category": category,
            "amount_btc": round(amount, 8),
            "time_utc": time_utc,
            "address_url": addr_url(address) if address else None,
            "prev_tx": i.get("next_tx"),  # WalletExplorer carries the funding tx here
        }
        # Optional single hop back to the transaction that produced this input.
        if one_hop and i.get("next_tx"):
            try:
                prev = client.tx(i["next_tx"])
                src["prev_tx_time_utc"] = iso_utc(prev.get("time"))
                src["prev_tx_label"] = prev.get("label")
            except WalletExplorerError:
                pass
        sources.append(src)
        edges.append({
            "txid": txid,
            "from_addr": address,
            "to_addr": None,
            "to_label": label,
            "category": category,
            "amount_btc": round(amount, 8),
            "time_utc": time_utc,
            "tx_url": tx_url(txid),
        })

    by_category = {}
    for s in sources:
        by_category.setdefault(s["category"], {"count": 0, "amount_btc": 0.0})
        by_category[s["category"]]["count"] += 1
        by_category[s["category"]]["amount_btc"] = round(
            by_category[s["category"]]["amount_btc"] + s["amount_btc"], 8)

    return {
        "origin": origin,
        "direction": "backward",
        "summary": {
            "inputs_attributed": len(sources),
            "by_category": by_category,
            "note": "shallow backward attribution; deep backward tracing is a "
                    "planned enhancement",
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "sources": sources,
        "endpoints": [s for s in sources if s["label"]],
        "patterns_flagged": [],
        "generated_utc": now_utc(),
    }


# --------------------------------------------------------------------------- #
# Graph emitters (optional)
# --------------------------------------------------------------------------- #

def graph_mermaid(result):
    lines = ["flowchart LR"]
    seen = set()

    def node_id(key):
        return "n" + str(abs(hash(key)) % (10 ** 9))

    for e in result.get("edges", []):
        src = e.get("from_addr") or e.get("txid")
        dst = e.get("to_addr") or e.get("to_label") or e.get("txid")
        if not src or not dst:
            continue
        sid, did = node_id(src), node_id(dst)
        if sid not in seen:
            lines.append('    {}["{}"]'.format(sid, short(src)))
            seen.add(sid)
        if did not in seen:
            dlabel = e.get("to_label") or short(dst)
            lines.append('    {}["{}"]'.format(did, dlabel))
            seen.add(did)
        amt = e.get("amount_btc") or 0
        lines.append('    {} -->|{} BTC| {}'.format(sid, amt, did))
    return "\n".join(lines)


def graph_dot(result):
    lines = ["digraph trace {", '  rankdir=LR;', '  node [shape=box];']
    for e in result.get("edges", []):
        src = e.get("from_addr") or e.get("txid")
        dst = e.get("to_addr") or e.get("to_label") or e.get("txid")
        if not src or not dst:
            continue
        label = e.get("to_label") or short(dst)
        amt = e.get("amount_btc") or 0
        lines.append('  "{}" -> "{}" [label="{} BTC"];'.format(
            short(src), label, amt))
    lines.append("}")
    return "\n".join(lines)


def maybe_graph(result, kind):
    if kind == "mermaid":
        return graph_mermaid(result)
    if kind == "dot":
        return graph_dot(result)
    return None


# --------------------------------------------------------------------------- #
# Renderers
# --------------------------------------------------------------------------- #

def _emit(text, out_path):
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        sys.stderr.write("[wxtrace] wrote {}\n".format(out_path))
    else:
        print(text)


def render_lookup(results, fmt):
    """results: list of dicts {address, label, wallet_id, category, url, found}."""
    if fmt == "json":
        return json.dumps(results, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["address", "found", "label", "wallet_id", "category", "url"])
        for r in results:
            w.writerow([r["address"], r["found"], r.get("label") or "",
                        r.get("wallet_id") or "", r["category"], r["url"]])
        return buf.getvalue().rstrip("\n")
    # console / md
    rows = []
    for r in results:
        label = r.get("label") or ("(unlabeled)" if r["found"] else "(unknown)")
        rows.append((short(r["address"], 10, 8), label, r.get("wallet_id") or "",
                     r["category"]))
    if fmt == "md":
        out = ["| Address | Label | Wallet ID | Category |",
               "| --- | --- | --- | --- |"]
        out += ["| {} | {} | {} | {} |".format(*row) for row in rows]
        return "\n".join(out)
    out = []
    for r, row in zip(results, rows):
        out.append("{}  {}  [{}]  wallet={}\n    {}".format(
            row[0], row[1], row[3], row[2] or "-", r["url"]))
    return "\n".join(out)


def render_tx(tx, fmt):
    enriched = {
        "found": tx.get("found"),
        "txid": tx.get("txid"),
        "url": tx_url(tx.get("txid")) if tx.get("txid") else None,
        "time_utc": iso_utc(tx.get("time")),
        "block_height": tx.get("block_height"),
        "wallet_label": tx.get("label"),
        "wallet_id": tx.get("wallet_id"),
        "is_coinbase": tx.get("is_coinbase"),
        "in": [{
            "address": i.get("address"),
            "amount_btc": i.get("amount"),
            "address_url": addr_url(i.get("address")) if i.get("address") else None,
        } for i in (tx.get("in") or [])],
        "out": [{
            "address": o.get("address"),
            "amount_btc": o.get("amount"),
            "wallet_id": o.get("wallet_id"),
            "label": o.get("label"),
            "category": classify(o.get("label")),
            "next_tx": o.get("next_tx"),
            "address_url": addr_url(o.get("address")) if o.get("address") else None,
            "next_tx_url": tx_url(o.get("next_tx")) if o.get("next_tx") else None,
        } for o in (tx.get("out") or [])],
    }
    if fmt == "json":
        return json.dumps(enriched, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["side", "address", "amount_btc", "label", "category", "next_tx"])
        for i in enriched["in"]:
            w.writerow(["in", i["address"], i["amount_btc"], "", "", ""])
        for o in enriched["out"]:
            w.writerow(["out", o["address"], o["amount_btc"], o["label"] or "",
                        o["category"], o["next_tx"] or ""])
        return buf.getvalue().rstrip("\n")
    # console / md narrative
    lines = []
    bullet = "- " if fmt == "md" else "  "
    head = "Transaction {}".format(enriched["txid"])
    lines.append("# " + head if fmt == "md" else head)
    lines.append("{}time:  {}".format(bullet, enriched["time_utc"]))
    lines.append("{}block: {}".format(bullet, enriched["block_height"]))
    if enriched["wallet_label"]:
        lines.append("{}wallet label: {} ({})".format(
            bullet, enriched["wallet_label"], enriched["wallet_id"]))
    lines.append("{}url:   {}".format(bullet, enriched["url"]))
    lines.append("")
    lines.append("Inputs ({}):".format(len(enriched["in"])))
    for i in enriched["in"]:
        lines.append("{}{}  {} BTC".format(bullet, short(i["address"], 12, 8),
                                           i["amount_btc"]))
    lines.append("")
    lines.append("Outputs ({}):".format(len(enriched["out"])))
    for o in enriched["out"]:
        tag = "  ->{}".format(o["label"]) if o["label"] else ""
        nxt = "  next_tx={}".format(short(o["next_tx"])) if o["next_tx"] else "  (unspent)"
        lines.append("{}{}  {} BTC  [{}]{}{}".format(
            bullet, short(o["address"], 12, 8), o["amount_btc"],
            o["category"], tag, nxt))
    return "\n".join(lines)


def render_txlist(data, fmt, kind):
    """Render the `address` and `wallet` transaction lists."""
    label = data.get("label")
    wallet_id = data.get("wallet_id")
    txs = data.get("txs", []) or []
    if fmt == "json":
        out = {
            "found": data.get("found"),
            "label": label,
            "wallet_id": wallet_id,
            "category": classify(label),
            "txs_count": data.get("txs_count"),
            "url": (addr_url(data.get("address")) if kind == "address"
                    else wallet_url(wallet_id)),
            "txs": [],
        }
        for t in txs:
            row = dict(t)
            row["time_utc"] = iso_utc(t.get("time"))
            row["tx_url"] = tx_url(t.get("txid"))
            out["txs"].append(row)
        return json.dumps(out, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        if kind == "address":
            w.writerow(["txid", "time_utc", "amount_received", "amount_sent",
                        "balance", "used_as_input", "used_as_output"])
            for t in txs:
                w.writerow([t.get("txid"), iso_utc(t.get("time")),
                            t.get("amount_received"), t.get("amount_sent"),
                            t.get("balance"), t.get("used_as_input"),
                            t.get("used_as_output")])
        else:
            w.writerow(["txid", "time_utc", "type", "amount", "counterparty_wallet",
                        "balance"])
            for t in txs:
                w.writerow([t.get("txid"), iso_utc(t.get("time")), t.get("type"),
                            t.get("amount"), t.get("wallet_id"), t.get("balance")])
        return buf.getvalue().rstrip("\n")
    # console / md
    lines = []
    header = "{} {}  [{}]  wallet={}  ({} txs total)".format(
        kind, label or short(data.get("address") or wallet_id, 12, 8),
        classify(label), wallet_id or "-", data.get("txs_count"))
    lines.append(("# " + header) if fmt == "md" else header)
    bullet = "- " if fmt == "md" else "  "

    def amt(v):
        return "?" if v is None else v

    for t in txs:
        if kind == "address":
            flow = ("recv {}".format(amt(t.get("amount_received")))
                    if t.get("used_as_output")
                    else "sent {}".format(amt(t.get("amount_sent"))))
        else:
            flow = "{} {}".format(t.get("type"), amt(t.get("amount")))
        lines.append("{}{}  {}  {} BTC".format(
            bullet, iso_utc(t.get("time")), short(t.get("txid")), flow))
    return "\n".join(lines)


def render_waddresses(data, fmt):
    wallet_id = data.get("wallet_id")
    label = data.get("label")
    addrs = data.get("addresses", []) or []
    if fmt == "json":
        out = dict(data)
        out["category"] = classify(label)
        out["url"] = wallet_url(wallet_id)
        for a in out.get("addresses", []):
            a["url"] = addr_url(a.get("address"))
        return json.dumps(out, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["address", "balance", "incoming_txs", "last_used_in_block", "url"])
        for a in addrs:
            w.writerow([a.get("address"), a.get("balance"), a.get("incoming_txs"),
                        a.get("last_used_in_block"), addr_url(a.get("address"))])
        return buf.getvalue().rstrip("\n")
    lines = []
    header = "wallet {} [{}] {}  ({} addresses total)".format(
        label or short(wallet_id, 12, 8), classify(label), wallet_id,
        data.get("addresses_count"))
    lines.append(("# " + header) if fmt == "md" else header)
    bullet = "- " if fmt == "md" else "  "
    for a in addrs:
        lines.append("{}{}  bal={} BTC  in_txs={}".format(
            bullet, a.get("address"), a.get("balance"), a.get("incoming_txs")))
    return "\n".join(lines)


def render_trace(result, fmt, graph_kind="none"):
    graph_text = maybe_graph(result, graph_kind)
    if graph_text is not None:
        result = dict(result, graph={"format": graph_kind, "text": graph_text})

    if fmt == "json":
        return json.dumps(result, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["txid", "from_addr", "to_addr", "to_label", "amount_btc",
                    "time_utc"])
        for e in result.get("edges", []):
            w.writerow([e.get("txid"), e.get("from_addr") or "",
                        e.get("to_addr") or "", e.get("to_label") or "",
                        e.get("amount_btc"), e.get("time_utc") or ""])
        return buf.getvalue().rstrip("\n")

    # console / md narrative
    s = result["summary"]
    o = result["origin"]
    lines = []
    h = "Bitcoin trace ({})".format(result["direction"])
    lines.append(("# " + h) if fmt == "md" else "=== {} ===".format(h))
    lines.append("Origin: {} {}".format(o.get("type"), o.get("value")))
    lines.append("  {}".format(o.get("url")))
    lines.append("Generated (UTC): {}".format(result["generated_utc"]))
    lines.append("")

    if result["direction"] == "backward":
        lines.append("Inputs attributed: {}".format(s.get("inputs_attributed")))
        lines.append("Note: {}".format(s.get("note")))
        lines.append("")
        lines.append("Funding sources:")
        for src in result.get("sources", []):
            tag = src["label"] or "(unlabeled cluster)"
            lines.append("  {} BTC  {}  [{}]  {}".format(
                src["amount_btc"], short(src["address"], 12, 8), src["category"], tag))
        return "\n".join(lines)

    lines.append("Hops (max depth reached): {}".format(s["max_depth_reached"]))
    lines.append("Transactions expanded: {}".format(s["txs_expanded"]))
    lines.append("Distinct addresses seen: {}".format(s["nodes_seen"]))
    lines.append("Endpoints reached: {}  (services: {}, cash-out candidates: {})".format(
        s["endpoints"], s["services_reached"], s["cashout_candidates"]))
    lines.append("")

    cashouts = result.get("cashout_candidates", [])
    if cashouts:
        lines.append("CASH-OUT CANDIDATES (exchange endpoints -- KYC subpoena targets):")
        for e in cashouts:
            lines.append("  {} BTC -> {}  [{}]".format(
                e["amount_btc"], e["label"], e["category"]))
            lines.append("    {}".format(e.get("address_url") or e.get("wallet_url")))
        lines.append("")

    services = [e for e in result["endpoints"] if e["label"]]
    if services:
        lines.append("Services reached:")
        for e in services:
            lines.append("  {} BTC -> {}  [{}]  ({} hops)".format(
                e["amount_btc"], e["label"], e["category"], len(e["path"])))
        lines.append("")

    holdings = [e for e in result["endpoints"] if e["reason"] == "unspent-holding"]
    if holdings:
        lines.append("Unspent holdings (funds at rest in unattributed addresses):")
        for e in holdings[:20]:
            lines.append("  {} BTC at {}".format(
                e["amount_btc"], short(e["address"], 12, 8)))
            lines.append("    {}".format(e.get("address_url")))
        if len(holdings) > 20:
            lines.append("  ... and {} more".format(len(holdings) - 20))
        lines.append("")

    if result["patterns_flagged"]:
        lines.append("Patterns flagged:")
        for p in result["patterns_flagged"]:
            lines.append("  [{}] {}".format(p["type"], p["detail"]))
        lines.append("")

    if graph_text:
        lines.append("Graph ({}):".format(graph_kind))
        lines.append(graph_text)

    lines.append("Reminder: attribution is a LEAD, not proof of identity. Confirm a "
                 "cash-out with a lawful off-chain request (KYC subpoena).")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #

def make_client(args):
    return WalletExplorerClient(
        delay=getattr(args, "delay", 0.5),
        max_retries=getattr(args, "max_retries", 5),
        max_requests=getattr(args, "max_requests", 2000),
        timeout=getattr(args, "timeout", 30),
        proxy=getattr(args, "proxy", None),
        verify=not getattr(args, "insecure", False),
        user_agent=getattr(args, "ua", None),
        verbose=getattr(args, "verbose", False),
    )


def cmd_lookup(args):
    client = make_client(args)
    cache = {}
    results = []
    addresses = args.address

    # Use the batch endpoint for many addresses; single endpoint for one.
    batch = {}
    if len(addresses) > 1:
        data = client.addresses_lookup(addresses)
        batch = data.get("existing_addresses_to_wallet_id", {}) or {}

    for a in addresses:
        if len(addresses) > 1:
            meta = batch.get(a)
            found = meta is not None
            label = (meta or {}).get("label")
            wallet_id = (meta or {}).get("wallet_id")
        else:
            data = client.address_lookup(a)
            found = bool(data.get("found"))
            label = data.get("label")
            wallet_id = data.get("wallet_id")
        if args.canonicalize and label:
            label = canonicalize_label(client, label, cache)
        results.append({
            "address": a,
            "found": found,
            "label": label,
            "wallet_id": wallet_id,
            "category": classify(label) if found else "unknown",
            "url": addr_url(a),
        })
    _emit(render_lookup(results, args.format), args.out)


def cmd_tx(args):
    client = make_client(args)
    tx = client.tx(args.txid)
    _emit(render_tx(tx, args.format), args.out)


def cmd_address(args):
    client = make_client(args)
    data = client.address(args.address, args.__dict__["from"], args.count)
    _emit(render_txlist(data, args.format, "address"), args.out)


def cmd_wallet(args):
    client = make_client(args)
    data = client.wallet(args.wallet, args.__dict__["from"], args.count)
    _emit(render_txlist(data, args.format, "wallet"), args.out)


def cmd_wallet_addresses(args):
    client = make_client(args)
    data = client.wallet_addresses(args.wallet, args.__dict__["from"], args.count)
    _emit(render_waddresses(data, args.format), args.out)


def cmd_trace(args):
    client = make_client(args)
    stop_at_service = args.stop_at_service == "true"

    if args.txid:
        origin = {"type": "txid", "value": args.txid, "url": tx_url(args.txid)}
        seeds = [args.txid]
    else:
        origin = {"type": "address", "value": args.address, "url": addr_url(args.address)}
        adata = client.address(args.address, 0, 100)
        # Forward = where the address SENT funds: txs where it is an input.
        seeds = [t["txid"] for t in (adata.get("txs") or [])
                 if t.get("used_as_input")]
        origin["label"] = adata.get("label")
        origin["wallet_id"] = adata.get("wallet_id")
        origin["outgoing_txs"] = len(seeds)

    if args.direction == "backward":
        if not args.txid:
            # Resolve the address's most recent spend to a tx to attribute its inputs.
            if not seeds:
                raise WalletExplorerError(
                    "no outgoing transaction found for that address to trace "
                    "backward from")
            result = trace_backward(client, seeds[0], origin,
                                    canonicalize=args.canonicalize)
        else:
            result = trace_backward(client, args.txid, origin,
                                    canonicalize=args.canonicalize)
    else:
        if not seeds:
            raise WalletExplorerError(
                "nothing to trace forward: the address has no outgoing "
                "(spending) transactions yet")
        result = trace_forward(
            client, seeds, origin,
            max_depth=args.max_depth, max_nodes=args.max_nodes,
            min_amount=args.min_amount, stop_at_service=stop_at_service,
            canonicalize=args.canonicalize)

    _emit(render_trace(result, args.format, args.graph), args.out)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        prog="wxtrace.py",
        description="Bitcoin tracing & attribution on the public WalletExplorer "
                    "API (dependency-free). Authorized use only.")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--delay", type=float, default=0.5,
                        help="Seconds to pause before each request (polite single-"
                             "host pacing; default 0.5, ~2 req/s).")
        sp.add_argument("--max-retries", type=int, default=5,
                        help="Backoff retries on 429/5xx (default 5; 2,4,8,16,32s "
                             "with jitter, honoring Retry-After).")
        sp.add_argument("--max-requests", type=int, default=2000,
                        help="Global cap on total requests per run (default 2000; "
                             "a runaway-trace guard).")
        sp.add_argument("--timeout", type=float, default=30,
                        help="Per-request timeout in seconds (default 30).")
        sp.add_argument("--proxy", help="A single HTTP(S) proxy URL.")
        sp.add_argument("--insecure", action="store_true",
                        help="Disable TLS certificate verification.")
        sp.add_argument("--ua", help="Override the User-Agent string.")
        sp.add_argument("--out", help="Write output to this file instead of stdout.")
        sp.add_argument("--verbose", action="store_true",
                        help="Log backoff/retry decisions to stderr.")

    def add_pagination(sp):
        sp.add_argument("--from", type=int, default=0,
                        help="Pagination start (must be divisible by 100; default 0).")
        sp.add_argument("--count", type=int, default=100,
                        help="How many to return (0-1000; default 100).")

    # lookup
    lo = sub.add_parser("lookup", help="Attribute one or many addresses.")
    add_common(lo)
    lo.add_argument("address", nargs="+", help="One or more Bitcoin addresses.")
    lo.add_argument("--canonicalize", action="store_true",
                    help="Canonicalize labels via the alternatives endpoint first.")
    lo.add_argument("--format", choices=["console", "json", "csv", "md"],
                    default="console")
    lo.set_defaults(func=cmd_lookup)

    # tx
    tx = sub.add_parser("tx", help="Fetch and pretty-print one transaction.")
    add_common(tx)
    tx.add_argument("txid", help="Transaction id.")
    tx.add_argument("--format", choices=["console", "json", "csv", "md"],
                    default="console")
    tx.set_defaults(func=cmd_tx)

    # address
    ad = sub.add_parser("address", help="List an address's transactions.")
    add_common(ad)
    add_pagination(ad)
    ad.add_argument("address", help="Bitcoin address.")
    ad.add_argument("--format", choices=["console", "json", "csv", "md"],
                    default="console")
    ad.set_defaults(func=cmd_address)

    # wallet
    wa = sub.add_parser("wallet", help="List a wallet cluster's transactions.")
    add_common(wa)
    add_pagination(wa)
    wa.add_argument("wallet", help="Wallet id, label, or label variant.")
    wa.add_argument("--format", choices=["console", "json", "csv", "md"],
                    default="console")
    wa.set_defaults(func=cmd_wallet)

    # wallet-addresses
    wad = sub.add_parser("wallet-addresses",
                         help="List the addresses in a wallet cluster.")
    add_common(wad)
    add_pagination(wad)
    wad.add_argument("wallet", help="Wallet id, label, or label variant.")
    wad.add_argument("--format", choices=["console", "json", "csv", "md"],
                     default="console")
    wad.set_defaults(func=cmd_wallet_addresses)

    # trace
    tr = sub.add_parser("trace", help="Forward-trace the flow of funds.")
    add_common(tr)
    g = tr.add_mutually_exclusive_group(required=True)
    g.add_argument("--txid", help="Seed the trace from this transaction.")
    g.add_argument("--address", help="Seed from this address's outgoing txs.")
    tr.add_argument("--direction", choices=["forward", "backward"],
                    default="forward",
                    help="forward = follow the money (full); backward = shallow "
                         "input attribution (deep backward is a planned enhancement).")
    tr.add_argument("--max-depth", type=int, default=12,
                    help="Hop limit (default 12).")
    tr.add_argument("--max-nodes", type=int, default=500,
                    help="Total transactions to expand (default 500; graph-"
                         "explosion guard).")
    tr.add_argument("--min-amount", type=float, default=0.0001,
                    help="Dust filter; don't chase outputs below this BTC "
                         "(default 0.0001).")
    tr.add_argument("--stop-at-service", choices=["true", "false"], default="true",
                    help="Stop at a known service; past an exchange coins are "
                         "commingled (default true).")
    tr.add_argument("--canonicalize", action="store_true",
                    help="Canonicalize service labels via the alternatives endpoint.")
    tr.add_argument("--graph", choices=["none", "dot", "mermaid"], default="none",
                    help="Also emit a transaction graph (mermaid renders in chat "
                         "and the report).")
    tr.add_argument("--format", choices=["console", "json", "csv", "md"],
                    default="json",
                    help="Output format (default json for machine use).")
    tr.set_defaults(func=cmd_trace)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (WalletExplorerError, ValueError) as e:
        sys.stderr.write("[!] {}\n".format(e))
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
