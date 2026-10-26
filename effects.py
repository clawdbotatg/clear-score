#!/usr/bin/env -S uv run -q -p 3.13 --script
# /// script
# dependencies = ["eth-hash[pycryptodome]"]
# ///
# What a mined transaction really did: every token and ETH movement and every approval, read from its receipt and
# its call trace (Alchemy). This is the ground truth a descriptor's screen is checked against.
#
#   ./effects.py <chainId> <txHash>        prints the effects as JSON
#
# Effects are plain facts, no judgment: {kind, asset, symbol, decimals, amount, from, to, signer}. `signer` says how
# the signer (the tx's `from`) is involved: "out" (leaves the signer), "in" (arrives), "grant" (an approval the
# signer gives), or null (moves between other parties, e.g. inside a router).
import json, os, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOTENV = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l) if (ROOT / ".env").exists() else {}
KEY = os.environ.get("ALCHEMY_API_KEY") or DOTENV.get("ALCHEMY_API_KEY")

# Alchemy subdomains by chain id. A chain not here has no ground truth (the review then reads code only).
NET = {1: "eth-mainnet", 10: "opt-mainnet", 56: "bnb-mainnet", 100: "gnosis-mainnet", 130: "unichain-mainnet",
       137: "polygon-mainnet", 143: "monad-mainnet", 146: "sonic-mainnet", 252: "frax-mainnet", 324: "zksync-mainnet",
       480: "worldchain-mainnet", 999: "hyperliquid-mainnet", 1101: "polygonzkevm-mainnet", 1135: "lisk-mainnet",
       5000: "mantle-mainnet", 8453: "base-mainnet", 42161: "arb-mainnet", 42220: "celo-mainnet",
       43114: "avax-mainnet", 57073: "ink-mainnet", 59144: "linea-mainnet", 80094: "berachain-mainnet",
       81457: "blast-mainnet", 534352: "scroll-mainnet", 7777777: "zora-mainnet", 11155111: "eth-sepolia"}
NATIVE = {56: "BNB", 100: "xDAI", 137: "POL", 143: "MON", 146: "S", 5000: "MNT", 42220: "CELO", 43114: "AVAX",
          80094: "BERA", 999: "HYPE"}

from eth_hash.auto import keccak


def topic(sig):
    return "0x" + keccak(sig.encode()).hex()


T_TRANSFER = topic("Transfer(address,address,uint256)")              # ERC-20 (3 topics) and ERC-721 (4)
T_APPROVAL = topic("Approval(address,address,uint256)")
T_APPROVE_ALL = topic("ApprovalForAll(address,address,bool)")
T_SINGLE = topic("TransferSingle(address,address,address,uint256,uint256)")
T_BATCH = topic("TransferBatch(address,address,address,uint256[],uint256[])")
T_DEPOSIT = topic("Deposit(address,uint256)")                         # WETH-style wrap
T_WITHDRAW = topic("Withdrawal(address,uint256)")                     # WETH-style unwrap


def rpc(chain, method, params):
    if chain not in NET:
        raise LookupError(f"no Alchemy network for chain {chain}")
    if not KEY:
        raise LookupError("ALCHEMY_API_KEY not set")
    req = urllib.request.Request(f"https://{NET[chain]}.g.alchemy.com/v2/{KEY}", method="POST",
                                 headers={"Content-Type": "application/json"},
                                 data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    if "error" in j:
        raise RuntimeError(f"{method}: {j['error']}")
    return j["result"]


_meta = {}


def token(chain, addr):
    k = (chain, addr)
    if k not in _meta:
        try:
            m = rpc(chain, "alchemy_getTokenMetadata", [addr])
            _meta[k] = {"symbol": m.get("symbol"), "decimals": m.get("decimals"), "name": m.get("name")}
        except Exception:
            _meta[k] = {"symbol": None, "decimals": None, "name": None}
    return _meta[k]


def word_addr(t):
    return "0x" + t[-40:].lower()


def effects(chain, txhash):
    """Cached in work/mined/: a mined transaction never changes."""
    f = ROOT / "work/mined" / f"{chain}-{txhash.lower()}.json"
    if f.exists():
        return json.loads(f.read_text())
    out = _effects(chain, txhash)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out))
    return out


def _effects(chain, txhash):
    tx = rpc(chain, "eth_getTransactionByHash", [txhash])
    if not tx:
        raise LookupError("tx not found")
    rc = rpc(chain, "eth_getTransactionReceipt", [txhash])
    signer = tx["from"].lower()
    out = []

    def add(kind, asset, amount, frm, to, **kw):
        sym = NATIVE.get(chain, "ETH") if asset == "native" else None
        meta = {"symbol": sym, "decimals": 18, "name": None} if asset == "native" else token(chain, asset)
        who = "out" if frm == signer else "in" if to == signer else None
        if kind in ("approval", "approvalForAll"):
            who = "grant" if frm == signer else None
        out.append({"kind": kind, "asset": asset, "symbol": meta["symbol"], "decimals": meta["decimals"],
                    "amount": str(amount), "from": frm, "to": to, "signer": who, **kw})

    # ETH: the tx's own value, then every internal call that carries value (call trace).
    calls = []
    try:
        tr = rpc(chain, "debug_traceTransaction", [txhash, {"tracer": "callTracer"}])

        def walk(c, depth):
            if int(c.get("value") or "0x0", 16) and c.get("type") in ("CALL", "CREATE", "CREATE2", "SELFDESTRUCT"):
                calls.append((c["from"].lower(), (c.get("to") or "").lower(), int(c["value"], 16), depth))
            for s in c.get("calls") or []:
                walk(s, depth + 1)
        walk(tr, 0)
        traced = True
    except Exception as e:
        traced = False
        if int(tx["value"], 16):
            calls.append((signer, (tx.get("to") or "").lower(), int(tx["value"], 16), 0))
    for frm, to, v, depth in calls:
        add("native", "native", v, frm, to, depth=depth)

    for lg in rc["logs"]:
        t = lg["topics"]
        if not t:
            continue
        a = lg["address"].lower()
        data = lg["data"][2:]
        if t[0] == T_TRANSFER and len(t) == 3:
            add("transfer", a, int(data[:64] or "0", 16), word_addr(t[1]), word_addr(t[2]))
        elif t[0] == T_TRANSFER and len(t) == 4:
            add("nft", a, 1, word_addr(t[1]), word_addr(t[2]), tokenId=str(int(t[3], 16)))
        elif t[0] == T_APPROVAL and len(t) == 3:
            add("approval", a, int(data[:64] or "0", 16), word_addr(t[1]), word_addr(t[2]))
        elif t[0] == T_APPROVAL and len(t) == 4:
            add("approval", a, 1, word_addr(t[1]), word_addr(t[2]), tokenId=str(int(t[3], 16)))
        elif t[0] == T_APPROVE_ALL:
            add("approvalForAll", a, int(data[:64] or "0", 16), word_addr(t[1]), word_addr(t[2]))
        elif t[0] == T_SINGLE:
            add("nft", a, int(data[64:128], 16), word_addr(t[2]), word_addr(t[3]), tokenId=str(int(data[:64], 16)))
        elif t[0] == T_BATCH:
            add("nft", a, -1, word_addr(t[2]), word_addr(t[3]), note="ERC-1155 batch (ids and amounts in data)")
        elif t[0] == T_DEPOSIT and len(t) == 2:
            add("wrap", a, int(data[:64] or "0", 16), word_addr(t[1]), a)
        elif t[0] == T_WITHDRAW and len(t) == 2:
            add("unwrap", a, int(data[:64] or "0", 16), a, word_addr(t[1]))
    # Net change of the signer per asset: what a wallet's balance shows afterwards (gas left out).
    net = {}
    for e in out:
        if e["kind"] in ("native", "transfer") and e["signer"] in ("in", "out"):
            k = e["asset"]
            net.setdefault(k, {"asset": k, "symbol": e["symbol"], "decimals": e["decimals"], "amount": 0})
            net[k]["amount"] += int(e["amount"]) * (1 if e["signer"] == "in" else -1)
    return {"chain": chain, "tx": txhash, "signer": signer, "to": (tx.get("to") or "").lower(),
            "value": str(int(tx["value"], 16)), "input": tx["input"], "status": int(rc["status"], 16),
            "traced": traced, "effects": out,
            "signerNet": [{**v, "amount": str(v["amount"])} for v in net.values() if v["amount"]]}


if __name__ == "__main__":
    print(json.dumps(effects(int(sys.argv[1]), sys.argv[2]), indent=1))
