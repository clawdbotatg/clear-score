#!/usr/bin/env -S uv run -q -p 3.13 --script
# /// script
# dependencies = ["clearsig", "eth-hash[pycryptodome]"]
# ///
# Score how truthfully and how clearly each ERC-7730 descriptor tells a signer what a transaction does.
#
#   ./score.py sync                      clone or pull the registry into registry/, npm ci its scripts, build the runner
#   ./score.py list                      work/catalog.json: every descriptor with deployments, and its hash
#   ./score.py prep <file|hash>...       build work/<hash>/: descriptor, cases + mined effects, verified source
#   ./score.py run [file ...]            prep → blind readers → truth agent → grade, N at a time
#        --sample N                      only N (busiest first)   --audited | --unaudited
#        --workers N                     parallel agents (default WORKERS or 10)
#        --force                         again, even when scores/<hash>.json is current
#        --bench                         the planted-bug mutants of mutate.py (work/bench-catalog.json → bench/scores/)
#   ./score.py grade [hash ...]          recompute scores/*.json from the saved answers (no model calls)
#   ./score.py report                    REPORT.md
#   ./score.py index                     index.json: chain:address:selector → grade, for wallets
#
# Each descriptor is keyed by its ERC-8176 hash (clearsig), the one auditors sign: a descriptor that changes
# upstream is unscored again on its own. The models write evidence and labels; grade.py turns them into numbers,
# so the rubric can change without running a model again.
import concurrent.futures as cf, datetime, hashlib, json, os, re, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REG = ROOT / "registry"
WORK = ROOT / "work"
SCORES = ROOT / ("bench/scores" if "--bench" in sys.argv else "scores")
CATALOG = WORK / ("bench-catalog.json" if "--bench" in sys.argv else "catalog.json")
RUNNER_REPO, RUNNER_REF = "https://github.com/sourcifyeth/clear-signing-test-runner", "9d6d2fe4715d53e002bb966f6593e1fbc44b53c7"
AI = REG / ".github/scripts/ai-review"
REPO = "https://github.com/ethereum/clear-signing-erc7730-registry"
DOTENV = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l) if (ROOT / ".env").exists() else {}
CFG = {**DOTENV, **os.environ}
MODEL = CFG.get("MODEL", "claude-opus-5-5")             # the truth agent
EFFORT = CFG.get("EFFORT", "high")
READER = CFG.get("READER", "claude-sonnet-5-5")          # the blind reader: a normal person, not an expert
WORKERS = int(CFG.get("WORKERS", "10"))
CTX = {"calldata": "contract", "eip712": "eip712"}
sys.path.insert(0, str(ROOT))
import effects as fx, grade


def sh(*args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout


def commit():
    return sh("git", "-C", str(REG), "rev-parse", "HEAD").strip()


def prompt_version():
    h = hashlib.sha256()
    for p in sorted((ROOT / "prompts").glob("*.md")) + sorted((ROOT / "schema").glob("*.json")):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


# ---------------------------------------------------------------------------------------------------------------
# sync, list (same catalog as clawdbotatg/clear-review)
# ---------------------------------------------------------------------------------------------------------------

def sync():
    if not REG.exists():
        sh("git", "clone", "-q", "--depth", "1", REPO, str(REG))
    else:
        sh("git", "-C", str(REG), "fetch", "-q", "--depth", "1", "origin", "master")
        sh("git", "-C", str(REG), "reset", "-q", "--hard", "FETCH_HEAD")     # our scratch clone: macOS case collisions dirty it
    sh("npm", "ci", "--silent", "--ignore-scripts", cwd=REG)
    # Sourcify's runner (the registry CI's): renders a screen from a descriptor and a tx, offline (mutate.py).
    rn = ROOT / "runner"
    if not rn.exists():
        sh("git", "clone", "-q", RUNNER_REPO, str(rn))
    sh("git", "-C", str(rn), "fetch", "-q", "origin")
    sh("git", "-C", str(rn), "checkout", "-q", RUNNER_REF)
    sh("npm", "ci", "--silent", "--ignore-scripts", cwd=rn)
    sh("npm", "run", "build", cwd=rn)
    print("registry at", commit()[:7], "runner at", RUNNER_REF[:7])


def collisions():
    """Paths that differ only in case: on macOS only one of each is on disk, so skip them all."""
    seen = {}
    for f in sh("git", "-C", str(REG), "ls-files").splitlines():
        seen.setdefault(f.lower(), []).append(f)
    return {f for fs in seen.values() if len(fs) > 1 for f in fs}


def attested_by(path):
    sigs = path.parent / "sigs"
    return sorted({f.name.split(".")[-2].split("-")[-1].lower() for f in sigs.glob(path.stem + ".*.json")}) if sigs.is_dir() else []


def catalog():
    from clearsig._descriptor_hash import descriptor_hash
    from clearsig._includes import resolve_includes
    skip, out, bad = collisions(), [], {}
    for p in sorted((REG / "registry").rglob("*.json")) + sorted((REG / "ercs").rglob("*.json")):
        rel = str(p.relative_to(REG))
        if "/tests" in rel or "/sigs/" in rel or not p.name.startswith(("calldata-", "eip712-")):
            continue
        if rel in skip:
            bad[rel] = "path collides with another in case"
            continue
        try:
            doc = resolve_includes(json.loads(p.read_text()), p.parent)
            ctx = doc.get("context") or {}
            kind = "calldata" if "contract" in ctx else "eip712" if "eip712" in ctx else None
            deps = (ctx.get(CTX[kind]) or {}).get("deployments") if kind else None
            if not deps:
                continue
            out.append({"file": rel, "kind": kind, "hash": "0x" + descriptor_hash(p).hex(),
                        "deployments": [{"chainId": int(d["chainId"]), "address": d["address"].lower()} for d in deps],
                        "auditedBy": attested_by(p)})
        except Exception as e:
            bad[rel] = str(e)[:200]
    WORK.mkdir(exist_ok=True)
    (WORK / "catalog.json").write_text(json.dumps({"registry": commit(), "descriptors": out, "skipped": bad}, indent=1))
    print(f"{len(out)} descriptors, {sum(len(d['deployments']) for d in out)} deployments, "
          f"{sum(1 for d in out if d['auditedBy'])} attested, {len(bad)} skipped")


def load_catalog(path=None):
    cat = json.loads((path or CATALOG).read_text())
    return cat.get("registry") or commit(), cat["descriptors"]


def find(ref):
    _, ds = load_catalog()
    return next(d for d in ds if ref in (d["file"], d["hash"]))


# ---------------------------------------------------------------------------------------------------------------
# prep: everything the agent reads, as files (it greps them; one huge JSON is harder to work in)
# ---------------------------------------------------------------------------------------------------------------

def rlp(b, i=0):
    x = b[i]
    if x < 0x80:
        return b[i:i + 1], i + 1
    if x < 0xb8:
        return b[i + 1:i + 1 + x - 0x80], i + 1 + x - 0x80
    if x < 0xc0:
        n = int.from_bytes(b[i + 1:i + 1 + x - 0xb7], "big")
        s = i + 1 + x - 0xb7
        return b[s:s + n], s + n
    if x < 0xf8:
        s, e = i + 1, i + 1 + x - 0xc0
    else:
        n = int.from_bytes(b[i + 1:i + 1 + x - 0xf7], "big")
        s = i + 1 + x - 0xf7
        e = s + n
    items = []
    while s < e:
        it, s = rlp(b, s)
        items.append(it)
    return items, e


def tx_input(raw, chain):
    b = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    if b[0] >= 0xc0:
        f = rlp(b)[0]
        to, value, data = f[3], f[4], f[5]
    else:
        f = rlp(b, 1)[0]
        to, value, data = (f[4], f[5], f[6]) if b[0] == 1 else (f[5], f[6], f[7])
        chain = int.from_bytes(f[0], "big")
    return {"chainId": chain, "to": "0x" + to.hex(), "value": str(int.from_bytes(value, "big")),
            "selector": "0x" + data[:4].hex(), "data": "0x" + data.hex()}


def selector(sig):
    from eth_hash.auto import keccak
    m = re.match(r"^\s*(\w+)\s*\((.*)\)\s*$", sig, re.S)
    if not m:
        return sig if sig.startswith("0x") else None
    return "0x" + keccak(f"{m[1]}({canon(m[2])})".encode()).hex()[:8]


def canon(params):
    out, depth, cur = [], 0, ""
    for ch in params + ",":
        if ch == "," and depth == 0:
            p, cur = cur.strip(), ""
            if not p:
                continue
            if p.startswith("("):
                d, j = 0, 0
                for j, c in enumerate(p):
                    d += (c == "(") - (c == ")")
                    if d == 0:
                        break
                out.append("(" + canon(p[1:j]) + ")" + re.match(r"(\[\d*\])*", p[j + 1:])[0])
            else:
                out.append(p.split()[0])
            continue
        depth += (ch == "(") - (ch == ")")
        cur += ch
    return ",".join(out)


def abi_type(x):
    t = x["type"]
    return "(" + ",".join(abi_type(c) for c in x["components"]) + ")" + t[5:] if t.startswith("tuple") else t


def tests_of(d):
    p = REG / d["file"]
    tf = p.parent / "testsv2" / (p.stem + ".tests.json")
    return json.loads(tf.read_text()) if tf.exists() else None


def bundle(d, head, cases):
    """The test-report bundle shape Sourcify's collect.js reads, so we get their source fetch and focusing."""
    formats = {}
    for key in (head.get("display") or {}).get("formats") or {}:
        name = key.split("(")[0].strip()
        formats[key] = {"selector": selector(key) if "(" in key else None,
                        "cases": [c["index"] for c in cases if c["input"].get("primaryType") == name
                                  or c["input"].get("selector") == selector(key)]}
    return {"schemaVersion": 1, "pr": None, "run": None, "descriptors": [{
        "path": d["file"], "entity": Path(d["file"]).parent.name, "name": Path(d["file"]).stem, "kind": d["kind"],
        "change": None, "testFile": None, "head": head, "base": None, "dataProvider": None,
        "formats": formats, "recommendations": [], "cases": [{**c, "results": {}} for c in cases]}]}


def prep(d, force=False):
    from clearsig._includes import resolve_includes
    w = WORK / d["hash"]
    if (w / "FORMATS.md").exists() and not force:
        return w
    shutil.rmtree(w, ignore_errors=True)
    (w / "cases").mkdir(parents=True)
    (w / "contracts").mkdir()
    p = REG / d["file"]
    head = resolve_includes(json.loads(p.read_text()), p.parent)
    (w / "descriptor.json").write_text(json.dumps(head, indent=1))
    t = tests_of(d) or {}
    chain0 = d["deployments"][0]["chainId"]
    cases = []
    for i, c in enumerate(t.get("tests", [])):
        if c.get("rawTx"):
            try:
                inp = tx_input(c["rawTx"], chain0)
            except Exception:
                inp = {"undecoded": True}
        else:
            m = c.get("data") or {}
            inp = {"primaryType": m.get("primaryType"), "domain": m.get("domain"), "message": m.get("message")}
        case = {"index": i, "description": c.get("description"), "input": inp, "from": c.get("from"),
                "txHash": c.get("txHash"), "screen": c.get("expected")}
        if c.get("txHash") and inp.get("chainId"):
            try:
                m = fx.effects(inp["chainId"], c["txHash"])
                m["sameAsTest"] = m.pop("input").lower() == inp["data"].lower() and m["to"] == inp["to"].lower()
                case["mined"] = m
            except Exception as e:
                case["minedError"] = str(e)[:200]
        cases.append(case)
    for c in cases:
        (w / "cases" / f"{c['index']}.json").write_text(json.dumps(c, indent=1))
    # Verified source per deployment, through Sourcify's own collector.
    contracts, unverified = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        b = Path(tmp) / "bundle.json"
        head2 = json.loads(json.dumps(head))
        head2["context"][CTX[d["kind"]]]["deployments"] = d["deployments"]
        b.write_text(json.dumps(bundle(d, head2, [{k: v for k, v in c.items() if k not in ("mined",)} for c in cases])))
        try:
            sh("node", str(AI / "collect.js"), "--bundle", str(b), "--out", tmp, "--max-bytes", "5000000", cwd=REG,
               env={**os.environ, **({"SOURCIFY_TOKEN": CFG["SOURCIFY_TOKEN"]} if CFG.get("SOURCIFY_TOKEN") else {})})
            for u in json.loads((Path(tmp) / "inputs/index.json").read_text())["units"]:
                unit = json.loads((Path(tmp) / "inputs" / u["file"]).read_text())
                for x in unit.get("contracts") or []:
                    k = f"{x.get('chainId')}-{x.get('address', '').lower()}"
                    if x.get("match") is None:
                        unverified.append(k)
                    contracts.setdefault(k, x)
        except subprocess.CalledProcessError as e:
            (w / "contracts" / "COLLECT-FAILED.txt").write_text(e.stderr[-2000:])
    payable = set()
    for k, x in contracts.items():
        cd = w / "contracts" / k
        cd.mkdir(parents=True, exist_ok=True)
        for path, src in (x.get("sources") or {}).items():
            f = cd / "src" / path.lstrip("/").replace("..", "_")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(src.get("content", "") if isinstance(src, dict) else str(src))
        (cd / "abi.json").write_text(json.dumps(x.get("abi"), indent=1))
        (cd / "meta.json").write_text(json.dumps({k2: v for k2, v in x.items() if k2 not in ("sources", "abi")}, indent=1))
        for f in x.get("abi") or []:
            if f.get("type") == "function" and f.get("stateMutability") == "payable":
                payable.add(selector(f"{f['name']}({','.join(abi_type(i) for i in f['inputs'])})"))
    # FORMATS.md: the map the agent starts from.
    lines = [f"# {d['file']}", "", f"Kind: {d['kind']}. Deployments: " + ", ".join(f"{x['chainId']}:{x['address']}" for x in d["deployments"]),
             f"Contracts with source: {', '.join(sorted(contracts)) or 'none'}. Unverified: {', '.join(unverified) or 'none'}.", ""]
    for key, fmt in ((head.get("display") or {}).get("formats") or {}).items():
        sel = selector(key) if "(" in key else None
        name = key.split("(")[0].strip()
        hit = [c for c in cases if c["input"].get("selector") == sel or c["input"].get("primaryType") == name]
        lines += [f"## `{key}`", "", f"- selector: {sel}" + ("  **payable**" if sel in payable else ""),
                  f"- intent: {json.dumps(fmt.get('intent'))}", f"- interpolatedIntent: {json.dumps(fmt.get('interpolatedIntent'))}",
                  "- fields: " + ", ".join(f"`{f.get('path') or f.get('value') or f.get('$ref')}` {f.get('label', '')!r} ({f.get('format', '')}{', ' + str(f.get('visible')) if f.get('visible') not in (None, 'always') else ''})"
                                           for f in fmt.get("fields") or []),
                  "- cases: " + (", ".join(f"{c['index']} ({'mined' if c.get('mined') else c.get('minedError') and 'not found' or 'no tx'})" for c in hit) or "none"), ""]
    (w / "FORMATS.md").write_text("\n".join(lines))
    return w


# ---------------------------------------------------------------------------------------------------------------
# models: claude -p, one subscription token per worker, rotated when a plan hits its limit
# ---------------------------------------------------------------------------------------------------------------

class Tokens:
    """CLAUDE_TOKEN_* setup-tokens (1 year, `claude setup-token`) from TOKENS_ENV, or CLAUDE_CODE_OAUTH_TOKEN."""
    def __init__(self):
        src = {}
        if CFG.get("TOKENS_ENV") and Path(CFG["TOKENS_ENV"]).exists():
            src = dict(l.split("=", 1) for l in Path(CFG["TOKENS_ENV"]).read_text().splitlines() if l.startswith("CLAUDE_TOKEN_"))
        self.toks = [(k[13:].lower(), v.strip().strip('"')) for k, v in sorted(src.items())] or \
                    ([("default", CFG["CLAUDE_CODE_OAUTH_TOKEN"])] if CFG.get("CLAUDE_CODE_OAUTH_TOKEN") else [("login", None)])
        self.rest = {}
        self.n = 0
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            for _ in range(len(self.toks)):
                name, tok = self.toks[self.n % len(self.toks)]
                self.n += 1
                if self.rest.get(name, 0) < time.time():
                    return name, tok
        time.sleep(60)
        return self.take()

    def tired(self, name):
        with self.lock:
            self.rest[name] = time.time() + 3600
        print(f"  plan {name} at its limit, resting 1 h", flush=True)


TOKENS = None


def child_env(tok):
    # A claude started from inside a Claude Code session must not inherit its session vars (it would run
    # embedded), nor an API key (metered billing).
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "AI_AGENT")
           and not k.startswith("CLAUDE_CODE_")}
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    if tok:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    return env


def claude(prompt, system, schema, cwd, model, effort, tools, add_dirs=(), timeout=3600):
    """One claude -p turn → (structured output, cost, account). Retries on another plan when one is at its limit."""
    for attempt in range(len(TOKENS.toks) + 2):
        name, tok = TOKENS.take()
        args = ["claude", "-p", "--model", model, "--effort", effort, "--output-format", "json",
                "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
                "--system-prompt", system, "--json-schema", json.dumps(schema), "--tools", ",".join(tools)]
        if tools:
            args += ["--allowedTools", *tools]
        for a in add_dirs:
            args += ["--add-dir", str(a)]
        r = subprocess.run(args, input=prompt, capture_output=True, text=True, env=child_env(tok), cwd=cwd, timeout=timeout)
        try:
            j = json.loads(r.stdout)
        except ValueError:
            j = {"is_error": True, "result": (r.stderr or r.stdout)[-400:]}
        text = str(j.get("result") or "")
        if j.get("is_error") or not j.get("structured_output"):
            if re.search(r"usage limit|rate limit|limit reached|out of extra usage|429", text, re.I):
                TOKENS.tired(name)
                continue
            if attempt < 1:
                continue
            raise RuntimeError(f"claude ({name}): {text[:300]}")
        return j["structured_output"], j.get("total_cost_usd") or 0, name
    raise RuntimeError("every plan is at its limit")


def render(screen):
    if not screen:
        return "(no screen)"
    out = []
    if screen.get("owner"):
        out.append(f"App: {screen['owner']}")
    out.append(f"Action: {screen.get('intent')}")
    if screen.get("interpolatedIntent"):
        out.append(screen["interpolatedIntent"])
    for f in screen.get("fields") or []:
        out.append(f"{f.get('label')}: {f.get('value')}")
    return "\n".join(out)


def read_blind(w):
    """The blind reader: a fresh model with no code and no descriptor, only the screen. Cases in parallel."""
    system = (ROOT / "prompts/reader.md").read_text()
    schema = json.loads((ROOT / "schema/reader.schema.json").read_text())

    def one(f):
        c = json.loads(f.read_text())
        if "reader" in c or not c.get("mined"):
            return 0
        you = c["mined"].get("signer") or c.get("from") or "unknown"
        out, k, _ = claude(f"Your wallet's address: {you}\n\nThe screen:\n\n" + render(c["screen"]), system, schema,
                           tempfile.gettempdir(), READER, "low", [])
        c["reader"] = out
        f.write_text(json.dumps(c, indent=1))
        return k
    with cf.ThreadPoolExecutor(6) as ex:
        return sum(ex.map(one, sorted((w / "cases").glob("*.json"))))


def truth(w):
    system = (ROOT / "prompts/truth.md").read_text()
    schema = json.loads((ROOT / "schema/truth.schema.json").read_text())
    return claude("Score the descriptor in this directory. Start with FORMATS.md.", system, schema, w, MODEL, EFFORT,
                  ["Read", "Grep", "Glob"], add_dirs=[REG / "specs", AI])


# ---------------------------------------------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------------------------------------------

def current(d):
    f = SCORES / f"{d['hash']}.json"
    if not f.exists():
        return False
    s = json.loads(f.read_text())
    return s.get("prompt") == prompt_version() and "error" not in s


def score_one(d, registry):
    t0 = time.time()
    rec = {"hash": d["hash"], "file": d["file"], "kind": d["kind"], "registry": registry, "deployments": d["deployments"],
           "auditedBy": d["auditedBy"], "model": f"{MODEL} ({EFFORT})", "reader": READER, "prompt": prompt_version(),
           "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    try:
        w = prep(d)
        cost = read_blind(w)
        ans, c, acct = truth(w)
        (w / "answer.json").write_text(json.dumps(ans, indent=1))
        rec.update(answer=ans, cost=round(cost + c, 3), account=acct)
    except Exception as e:
        rec["error"] = str(e)[:500]
    rec["seconds"] = round(time.time() - t0)
    rec["cases"] = [json.loads(f.read_text()) for f in sorted((WORK / d["hash"] / "cases").glob("*.json"), key=lambda f: int(f.stem))] \
        if (WORK / d["hash"] / "cases").exists() else []
    rec = grade.grade(rec)
    rec.pop("cases")
    SCORES.mkdir(exist_ok=True)
    (SCORES / f"{d['hash']}.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    s = rec.get("summary") or {}
    print(f"{s.get('grade', '💥')} truth {s.get('truth', '-'):>3} clarity {s.get('clarity', '-'):>3}  {d['file']}  "
          f"{rec.get('error', '')[:120]} ({rec['seconds']} s, ${rec.get('cost', 0)})", flush=True)
    return rec


def run(args):
    global TOKENS
    TOKENS = Tokens()
    registry, todo = load_catalog()
    files = [a for a in args if not a.startswith("--") and not a.isdigit()]
    if files:
        todo = [d for d in todo if d["file"] in files or d["hash"] in files]
    if "--audited" in args:
        todo = [d for d in todo if d["auditedBy"]]
    if "--unaudited" in args:
        todo = [d for d in todo if not d["auditedBy"]]
    if "--force" not in args:
        todo = [d for d in todo if not current(d)]
    todo.sort(key=lambda d: -len(d["deployments"]))
    if "--sample" in args:
        todo = todo[:int(args[args.index("--sample") + 1])]
    n = int(args[args.index("--workers") + 1]) if "--workers" in args else WORKERS
    print(f"scoring {len(todo)} descriptors, {n} at a time, {MODEL} + reader {READER}, "
          f"plans: {', '.join(t[0] for t in TOKENS.toks)}", flush=True)
    with cf.ThreadPoolExecutor(n) as ex:
        list(ex.map(lambda d: score_one(d, registry), todo))


def regrade(hashes):
    for f in sorted(SCORES.glob("*.json")):
        if hashes and f.stem not in hashes:
            continue
        rec = json.loads(f.read_text())
        w = WORK / rec["hash"] / "cases"
        rec["cases"] = [json.loads(c.read_text()) for c in sorted(w.glob("*.json"), key=lambda c: int(c.stem))] if w.exists() else []
        rec = grade.grade(rec)
        rec.pop("cases")
        f.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    print("regraded")


def recs():
    return [json.loads(f.read_text()) for f in sorted(SCORES.glob("*.json"))]


def report():
    rs = recs()
    tally = {}
    for r in rs:
        g = (r.get("summary") or {}).get("grade", "error")
        tally[g] = tally.get(g, 0) + 1
    lines = ["# Report", "", f"{len(rs)} descriptors scored. Rubric {grade.RUBRIC}.", "",
             " · ".join(f"{k}: {v}" for k, v in sorted(tally.items())), "",
             "| Grade | Truth | Clarity | File | Worst finding |", "|---|---|---|---|---|"]
    for r in sorted(rs, key=lambda r: ((r.get("summary") or {}).get("truth", -1), r["file"])):
        s = r.get("summary") or {}
        lines.append(f"| {s.get('grade', 'error')} | {s.get('truth', '')} | {s.get('clarity', '')} | `{r['file']}` | "
                     + (s.get("worst") or r.get("error", "")).replace("|", "\\|")[:200] + " |")
    lines += ["", f"Model cost (list price, from the CLI): ${sum(r.get('cost', 0) for r in rs):.2f}."]
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(" ".join(f"{k}:{v}" for k, v in sorted(tally.items())))


def index():
    """chain:address:selector → the grade a wallet shows for that one function, plus the descriptor's summary."""
    out = {}
    for r in recs():
        if "summary" not in r:
            continue
        for x in r["deployments"]:
            for key, f in (r.get("formats") or {}).items():
                sel = selector(key) if "(" in key else key.split("(")[0]
                out[f"{x['chainId']}:{x['address']}:{sel}"] = {"grade": f["grade"], "truth": f["truth"], "clarity": f["clarity"],
                                                               "file": r["file"]}
    (ROOT / "index.json").write_text(json.dumps({"rubric": grade.RUBRIC, "functions": out}, indent=0, sort_keys=True) + "\n")
    print(f"{len(out)} functions")


if __name__ == "__main__":
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "prep":
        for ref in rest:
            print(prep(find(ref), force=True))
    else:
        {"sync": sync, "list": catalog, "run": lambda: run(rest), "grade": lambda: regrade(rest), "report": report,
         "index": index}.get(cmd, lambda: print(open(__file__).read().split("\nimport ")[0]))()
