#!/usr/bin/env -S uv run -q -p 3.13 --script
# /// script
# dependencies = ["clearsig", "eth-hash[pycryptodome]"]
# ///
# Measure the measurer: plant one known bug in a descriptor, re-render its test screens with Sourcify's runner,
# and see if the scorer catches it. A scorer that grades a planted bug A is broken, whatever it says elsewhere.
#
#   ./mutate.py <registry file> ...     write mutants to work/bench/ + work/bench-catalog.json
#
# Mutants live outside the registry clone: Sourcify's runner indexes every descriptor under a `registry/` folder,
# so a mutant next to its original would render as the original.
#   ./mutate.py report                  bench/REPORT.md: caught or missed, per mutant
#
# Then: ./score.py run --bench   (scores into bench/scores/, never scores/)
#
# Mutations (each one is a lie or an omission the scale calls critical):
#   hide-party    a recipient/spender address field → visible: never
#   hide-amount   an amount field → visible: never
#   drop-value    a payable function's @.value field removed
#   swap-token    an amount's tokenPath → another address parameter of the same function
#   flip-intent   the intent's verb → its opposite (Deposit → Withdraw)
#   min-max       a "Minimum" label → "Maximum" (or the reverse)
import copy, hashlib, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REG = ROOT / "registry"
RUNNER = ROOT / "runner/dist/cli.js"
BENCH = ROOT / "work/bench-catalog.json"
sys.path.insert(0, str(ROOT))

OPPOSITE = {"Deposit": "Withdraw", "Withdraw": "Deposit", "Add": "Remove", "Remove": "Add", "Buy": "Sell",
            "Sell": "Buy", "Stake": "Unstake", "Unstake": "Stake", "Supply": "Withdraw", "Borrow": "Repay",
            "Repay": "Borrow", "Mint": "Burn", "Burn": "Mint", "Wrap": "Unwrap", "Unwrap": "Wrap", "Lock": "Unlock",
            "Unlock": "Lock", "Send": "Receive", "Transfer": "Receive", "Approve": "Revoke", "Swap": "Cancel",
            "Claim": "Forfeit", "Delegate": "Undelegate", "Bridge": "Cancel", "Redeem": "Deposit"}


def fields(fmt):
    return [f for f in fmt.get("fields") or [] if isinstance(f, dict) and (f.get("path") or f.get("value"))]


def params(key):
    """[(type, name)] of a format key's top-level parameters."""
    m = re.match(r"^\s*\w+\s*\((.*)\)\s*$", key, re.S)
    if not m:
        return []
    out, depth, cur = [], 0, ""
    for ch in m[1] + ",":
        if ch == "," and depth == 0:
            p = cur.strip().split()
            if len(p) >= 2:
                out.append((p[0], p[-1]))
            cur = ""
            continue
        depth += (ch == "(") - (ch == ")")
        cur += ch
    return out


def mutations(key, fmt, payable):
    fs = fields(fmt)
    for f in fs:
        if f.get("format") == "addressName" and f.get("visible") in (None, "always"):
            yield "hide-party", lambda fm, p=f.get("path"): [x.update(visible="never") for x in fields(fm) if x.get("path") == p]
            break
    for f in fs:
        if f.get("format") in ("tokenAmount", "amount") and f.get("visible") in (None, "always") and f.get("path") != "@.value":
            yield "hide-amount", lambda fm, p=f.get("path"): [x.update(visible="never") for x in fields(fm) if x.get("path") == p]
            break
    if payable and any(f.get("path") == "@.value" or f.get("value") == "@.value" for f in fs):
        yield "drop-value", lambda fm: fm.update(fields=[x for x in fm["fields"] if not (isinstance(x, dict) and "@.value" in (x.get("path"), x.get("value")))])
    addrs = [n for t, n in params(key) if t == "address"]
    for f in fs:
        tp = (f.get("params") or {}).get("tokenPath")
        if f.get("format") == "tokenAmount" and tp in addrs and len(addrs) > 1:
            other = next(a for a in addrs if a != tp)
            yield "swap-token", lambda fm, p=f.get("path"), o=other: [x["params"].update(tokenPath=o) for x in fields(fm) if x.get("path") == p]
            break
    verb = (fmt.get("intent") or "").split(" ")[0] if isinstance(fmt.get("intent"), str) else ""
    if verb in OPPOSITE:
        def flip(fm, v=verb):
            fm["intent"] = OPPOSITE[v] + fm["intent"][len(v):]
            if isinstance(fm.get("interpolatedIntent"), str) and fm["interpolatedIntent"].startswith(v):
                fm["interpolatedIntent"] = OPPOSITE[v] + fm["interpolatedIntent"][len(v):]
        yield "flip-intent", flip
    for f in fs:
        lab = f.get("label") or ""
        if re.search(r"\b(Minimum|Maximum|Min|Max)\b", lab):
            sw = {"Minimum": "Maximum", "Maximum": "Minimum", "Min": "Max", "Max": "Min"}
            new = re.sub(r"\b(Minimum|Maximum|Min|Max)\b", lambda m: sw[m[1]], lab)
            yield "min-max", lambda fm, p=f.get("path"), n=new: [x.update(label=n) for x in fields(fm) if x.get("path") == p]
            break


def mutate(rel):
    from clearsig._includes import resolve_includes
    import score
    p = REG / rel
    head = resolve_includes(json.loads(p.read_text()), p.parent)
    head.pop("includes", None)
    tf = p.parent / "testsv2" / (p.stem + ".tests.json")
    if not tf.exists():
        print("no test file:", rel)
        return []
    tests = json.loads(tf.read_text())
    cases = []
    for c in tests["tests"]:
        try:
            cases.append(score.tx_input(c["rawTx"], 1)["selector"] if c.get("rawTx") else None)
        except Exception:
            cases.append(None)
    d = next(x for x in score.load_catalog(score.WORK / "catalog.json")[1] if x["file"] == rel)
    payable = set()
    w = ROOT / "work" / d["hash"] / "contracts"
    for abi in w.glob("*/abi.json"):
        for f in json.loads(abi.read_text()) or []:
            if f.get("type") == "function" and f.get("stateMutability") == "payable":
                payable.add(score.selector(f"{f['name']}({','.join(score.abi_type(i) for i in f['inputs'])})"))
    out, done = [], set()
    for key, fmt in head["display"]["formats"].items():
        sel = score.selector(key) if "(" in key else None
        hit = [i for i, s in enumerate(cases) if s and s == sel]
        if not hit:
            continue
        for kind, fn in mutations(key, fmt, sel in payable):
            if kind in done:
                continue                    # one mutant of each kind per descriptor
            m = copy.deepcopy(head)
            fn(m["display"]["formats"][key])
            if m == head:
                continue
            name = f"{p.stem}.mut-{kind}"
            mp = ROOT / "work/bench" / p.parent.name / f"{name}.json"
            (mp.parent / "testsv2").mkdir(parents=True, exist_ok=True)
            mp.write_text(json.dumps(m, indent=2))
            mt = copy.deepcopy(tests)
            mt["descriptor"] = f"../{mp.name}"
            mt["tests"] = [tests["tests"][i] for i in hit]
            mtf = mp.parent / "testsv2" / f"{name}.tests.json"
            mtf.write_text(json.dumps(mt, indent=2))
            # The screen the mutant really shows: render it, and make that the case's expected screen.
            r = subprocess.run(["node", str(RUNNER), str(mtf), "-o", str(mtf) + ".out"], capture_output=True, text=True)
            try:
                res = json.loads(Path(str(mtf) + ".out").read_text())["cases"]
                for t, rc in zip(mt["tests"], res):
                    if not rc.get("rendered"):
                        raise ValueError(rc.get("error") or rc.get("status"))
                    t["expected"] = rc["rendered"]
            except Exception as e:
                print(f"skip {name}: runner could not render ({str(e)[:100]})")
                mp.unlink(), mtf.unlink()
                continue
            mtf.write_text(json.dumps(mt, indent=2))
            done.add(kind)
            out.append({"file": str(mp), "kind": d["kind"],
                        "hash": "0x" + hashlib.sha256(mp.read_bytes()).hexdigest(),
                        "deployments": d["deployments"], "auditedBy": [],
                        "bench": {"original": d["hash"], "mutation": kind, "format": key}})
            print("mutant", out[-1]["file"], "→", key.split("(")[0])
    return out


def report():
    cat = json.loads(BENCH.read_text())
    lines = ["# Bench: planted bugs", "", "| Mutation | Descriptor | Function | Original | Mutant | Caught |", "|---|---|---|---|---|---|"]
    caught = total = 0
    for d in cat["descriptors"]:
        b = d["bench"]
        mf, of = ROOT / "bench/scores" / f"{d['hash']}.json", ROOT / "scores" / f"{b['original']}.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text()).get("formats", {}).get(b["format"])
        o = json.loads(of.read_text()).get("formats", {}).get(b["format"]) if of.exists() else None
        if not m:
            continue
        hit = m["grade"] == "F" or (o and o["truth"] - m["truth"] >= 40)
        caught += hit
        total += 1
        lines.append(f"| {b['mutation']} | `{Path(d['file']).name}` | {b['format'].split('(')[0]} | "
                     f"{o and o['grade'] or '-'} {o and o['truth'] or ''} | {m['grade']} {m['truth']} | {'✅' if hit else '❌'} |")
    lines[1:1] = ["", f"Caught {caught} of {total}."]
    (ROOT / "bench").mkdir(exist_ok=True)
    (ROOT / "bench/REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"caught {caught}/{total}")


if __name__ == "__main__":
    if sys.argv[1:] == ["report"]:
        report()
    else:
        cat = json.loads(BENCH.read_text()) if BENCH.exists() else {"descriptors": []}
        new = [m for rel in sys.argv[1:] for m in mutate(rel)]
        keep = [d for d in cat["descriptors"] if d["file"] not in {n["file"] for n in new}]
        BENCH.write_text(json.dumps({"descriptors": keep + new}, indent=1))
        print(f"{len(new)} mutants, {len(keep) + len(new)} in the bench")
