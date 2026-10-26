# Rubric v1.1

Two scores per function (format), 0–100, and a letter. `grade.py` computes all of it from the agent's saved
answer, so a rubric change is `./score.py grade`, no model calls.

We score the **screen**, not the contract. A contract that steals your tokens and says so scores 100.

## Truth: does the screen say what really happens?

Start at 100.

- Each **critical** finding on truth or completeness (an effect on the signer's assets, allowances, positions
  or rights that is missing or shown wrong): truth drops to 25, and 25 more for each further one.
- Each **warning** on truth or completeness: −10.
- **Receipts cap it.** For every test case that is a real mined tx, the agent counts the signer's real effects
  (tokens and ETH out, in, approvals given) and how many the screen states right. Truth is at most that share,
  when a warning or critical backed by a receipt explains the gap. An effect no descriptor can show (the LP
  tokens a pool decides) is an info and costs nothing.
- Info findings cost nothing (nothing a descriptor can fix).

Severity follows the registry's own AI review scale (`.github/scripts/ai-review/prompt.md`: `<severity>`,
`<examples>`, `<not_critical>`), so our critical means what theirs means.

## Clarity: does a normal person get it?

- **Blind reader** (60%): a separate model sees only the screen and says what it thinks will happen. The agent
  marks each real effect right (1), partial (0.5), missed (0), wrong (−0.5). Only on mined cases.
- **Glance and depth** (40%): the agent's 0–100 for the intent line alone, and for all fields together.
- Each clarity warning (raw hex, unreadable number, too much, too little in the intent): −5.
- No mined case: glance and depth only, and `measured: false`.

## Letter

| | |
|---|---|
| **F** | any critical truth/completeness finding: the screen is wrong |
| **A** | truth ≥ 90 and clarity ≥ 80 |
| **B** | truth ≥ 75 and clarity ≥ 60 |
| **C** | truth ≥ 60 |
| **D** | the rest |

A descriptor's grade is its worst function's. Wallets should use the function's grade: a signer signs one
function, and a file with one bad function and 30 good ones is fine for the 30.

## Checking the checker

`mutate.py` plants one known bug (a lie the scale calls critical) in a scored descriptor and re-renders its
screens. The scorer must grade that function F, or drop its truth by 40+. Track the catch rate per rubric.
