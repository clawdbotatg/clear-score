# Evidence → numbers. The agent writes findings and per-case judgments; this file alone decides the scores, so the
# rubric can change and `./score.py grade` recomputes every score with no model call. Rules: RUBRIC.md.
RUBRIC = "v1"

CRIT_TRUTH = 25        # a critical truth/completeness finding caps truth here, and each further one takes this off
WARN_TRUTH = 10        # each truth/completeness warning
WARN_CLARITY = 5       # each clarity warning
READER = {"right": 1.0, "partial": 0.5, "missed": 0.0, "wrong": -0.5}
ORDER = "ABCDF"


def letter(truth, clarity, critical):
    if critical:
        return "F"
    if truth >= 90 and clarity >= 80:
        return "A"
    if truth >= 75 and clarity >= 60:
        return "B"
    if truth >= 60:
        return "C"
    return "D"


def format_score(f, cases):
    fs = f.get("findings") or []
    crit = [x for x in fs if x["severity"] == "critical" and x["axis"] in ("truth", "completeness")]
    warn = [x for x in fs if x["severity"] == "warning" and x["axis"] in ("truth", "completeness")]
    cwarn = [x for x in fs if x["severity"] in ("warning", "critical") and x["axis"] == "clarity"]
    truth = 100 - WARN_TRUTH * len(warn)
    if crit:
        truth = min(truth, CRIT_TRUTH) - CRIT_TRUTH * (len(crit) - 1)
    # Receipts: the share of the signer's real effects the screen states right (only cases the agent judged).
    shown = [(c["shownRight"], c["signerEffects"]) for c in f.get("cases") or [] if c.get("signerEffects")]
    if shown:
        truth = min(truth, round(100 * sum(a for a, _ in shown) / sum(b for _, b in shown)))
    truth = max(0, truth)
    # Clarity: what a blind reader got from the screen, then the glance and depth judgments.
    reads = [v for c in f.get("cases") or [] for v in c.get("reader") or []]
    comprehension = max(0.0, sum(READER[v] for v in reads) / len(reads)) if reads else None
    look = (f["glance"] + f["depth"]) / 2
    clarity = round(0.6 * 100 * comprehension + 0.4 * look) if comprehension is not None else round(look)
    clarity = max(0, clarity - WARN_CLARITY * len(cwarn))
    worst = (crit or warn or cwarn or [{}])[0].get("title")
    return {"grade": letter(truth, clarity, bool(crit)), "truth": truth, "clarity": clarity,
            "measured": comprehension is not None, "groundTruth": any(x.get("groundTruth") for x in fs),
            "critical": len(crit), "warnings": len(warn) + len(cwarn), "worst": worst,
            "comprehension": None if comprehension is None else round(100 * comprehension)}


def grade(rec):
    ans = rec.get("answer")
    rec["rubric"] = RUBRIC
    if not ans:
        rec.pop("formats", None), rec.pop("summary", None)
        return rec
    fmts = {f["key"]: format_score(f, rec.get("cases") or []) for f in ans["formats"]}
    if not fmts:
        rec["summary"] = {"grade": "?", "worst": "no formats"}
        return rec
    rec["formats"] = fmts
    worst = max(fmts.values(), key=lambda s: (ORDER.index(s["grade"]), -s["truth"]))
    g = {k: sum(1 for s in fmts.values() if s["grade"] == k) for k in ORDER}
    rec["summary"] = {
        "grade": worst["grade"],                                    # the worst function: one wrong screen is enough
        "truth": round(sum(s["truth"] for s in fmts.values()) / len(fmts)),
        "clarity": round(sum(s["clarity"] for s in fmts.values()) / len(fmts)),
        "functions": " ".join(f"{v}{k}" for k, v in g.items() if v),
        "incomplete": bool(ans.get("couldNotCheck")),
        "worst": worst["worst"]}
    return rec
