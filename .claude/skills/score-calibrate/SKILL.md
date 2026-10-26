---
name: score-calibrate
description: Check that clear-score's grades are right - plant known bugs in descriptors (mutate.py), re-run, measure the catch rate; compare against Cyfrin audits and clear-review; tune the prompt or rubric. Use when asked to calibrate, benchmark, test the scorer, or when grades look wrong.
---

# Calibrate the scorer

A score is only worth something if the scorer catches what it should and leaves alone what is fine.

## 1. Planted bugs (recall)

```sh
./mutate.py registry/<entity>/<file>.json ...    # needs the original prepped and scored first
./score.py run --bench --workers 10
./mutate.py report                                # bench/REPORT.md
```

Pick originals that score A or B (a planted bug in a broken file proves nothing). Caught = the mutated function
grades F or loses 40+ truth. Target: every hide-amount, drop-value, swap-token, flip-intent caught. A miss: read
its `bench/scores/<hash>.json` answer and find why (did it read the screen? did the receipt show it?).

## 2. Known-bad and known-good (precision)

- Known-bad: clear-review's fails (`../clear-review/REPORT.md`: 1inch V3/V4, ParaSwap v5, Uniswap V3 Router02,
  Safe migration), and descriptors the registry fixed after a Cyfrin audit (the old version from git history).
- Known-good: Cyfrin-attested descriptors that neither clear-review model flagged.
- A known-good graded F: read the critical. Wrong evidence = a prompt problem; real = a new finding, file it.

## 3. Consistency

Score the same 10 descriptors twice (`--force`). Grades that flip between runs are noise: find which finding
comes and goes and tighten the prompt around it.

## Tuning

- Severity disagreements: change `prompts/truth.md`, never the registry's severity guide.
- Weights and thresholds: `grade.py` (bump `RUBRIC`), then `./score.py grade`. No model calls.
- Every change: rerun the bench, write the catch rate and the date in `bench/REPORT.md`.
