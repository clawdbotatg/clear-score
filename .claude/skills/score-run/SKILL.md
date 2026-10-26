---
name: score-run
description: Run clear-score over the ERC-7730 registry at scale (many claude -p agents at once over several subscriptions), watch it, and handle failures. Use when asked to score descriptors, run the batch, score everything, or check how a run is going.
---

# Run the scorer at scale

## Before

1. `./score.py sync` then `./score.py list`. Note the registry commit and the descriptor count.
2. Check `.env`: `ALCHEMY_API_KEY`, and `TOKENS_ENV` pointing at a file of `CLAUDE_TOKEN_<NAME>=` lines (one per
   subscription). The run prints the plan names it found; fewer than expected = stop and fix.
3. A rubric or prompt change since the last run? `prompt_version()` changes with `prompts/` and `schema/`, and
   every score with an old version is redone. Make sure that is wanted before a full run.

## Run

```sh
./score.py run --workers 10 > work/run-$(date +%m%d-%H%M).log 2>&1     # in the background
```

- Each worker: prep (Alchemy + Sourcify, cached) → blind reader per mined case (Sonnet) → truth agent (Opus,
  read-only tools) → grade → `scores/<hash>.json`. One line per descriptor in the log.
- Workers rotate across plans. A plan at its limit rests 1 h; when all rest, workers wait.
- Resumable: a rerun skips every descriptor whose score has the current prompt version and no error.
- Start with `--sample 20` after any prompt change, read a few answers, then the rest.

## Watch

- `grep -c . work/run-*.log`, `ls scores | wc -l`, `grep 💥 work/run-*.log`.
- Errors: `"error"` in `scores/<hash>.json`. Common: Sourcify 429 (set `SOURCIFY_TOKEN` or fewer workers),
  a unit too big, a model that did not return the schema. A rerun retries them.

## After

1. `./score.py report` and `./score.py index`.
2. Read 5 F and 5 A answers by hand (`work/<hash>/answer.json`): is the evidence real? Note any pattern of wrong
   findings for the calibrate skill.
3. Commit `scores/`, `REPORT.md`, `index.json` (never `work/`, `.env`, `registry/`, `runner/`). Push.
