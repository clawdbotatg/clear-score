# clear-score

How truthful and how clear is each [ERC-7730](https://eips.ethereum.org/EIPS/eip-7730) clear-signing descriptor?

A descriptor turns a transaction into the screen you read before you sign. This scores that screen, function by
function: **truth** (does it say what really happens to your wallet?) and **clarity** (does a normal person get
it at a glance, and can they check the details?). Not an audit: a rug that says "rug" scores 100.

For [wedgie.dev](https://wedgie.dev) and Instant Wallet: show the grade next to the screen, or hide the bad ones.

## How

1. **Ground truth from real transactions.** 1,120 of the registry's 2,830 test cases are real mined txs. We read
   each one's receipt and call trace (`effects.py`): every token and ETH movement and approval. That is what
   happened; the test's expected screen is what the wallet showed. The gap is measured, not guessed.
2. **A blind reader.** A separate model sees only the screen and says what it thinks will happen.
   Wrong beliefs from a true screen = a clarity problem.
3. **A truth agent** (`claude -p`, Opus 5.5, high effort, read-only tools) reads the verified source of every
   function, the mined effects and the blind reader's answer, and writes findings with evidence, per function.
4. **Numbers in code** (`grade.py`, [RUBRIC.md](RUBRIC.md)). The model labels; code scores. A rubric change
   regrades everything with no model call.
5. **Checking the checker** (`mutate.py`). Plant a known lie (hide the recipient, swap the token, flip
   "Deposit" to "Withdraw", drop the ETH value) in a good descriptor, re-render the screen with Sourcify's runner,
   and the scorer must catch it.

Keyed by the ERC-8176 descriptor hash, so a descriptor that changes upstream is unscored again on its own.

## Use

```sh
./score.py sync                      # registry + Sourcify's runner
./score.py list                      # work/catalog.json
./score.py run --sample 20           # busiest first; no args = everything not yet scored
./score.py run --workers 10          # 10 agents at once, spread over every plan in TOKENS_ENV
./score.py grade                     # recompute every score from saved answers
./score.py report                    # REPORT.md
./score.py index                     # index.json: chain:address:selector → grade
./mutate.py <registry file> ...      # plant bugs → ./score.py run --bench → ./mutate.py report
```

`.env` (gitignored): `ALCHEMY_API_KEY`; `TOKENS_ENV` = a file with `CLAUDE_TOKEN_<NAME>=` setup-tokens (one per
subscription, `claude setup-token`), or `CLAUDE_CODE_OAUTH_TOKEN`. Optional: `SOURCIFY_TOKEN`, `MODEL`,
`EFFORT`, `READER`, `WORKERS`.

## Output

`scores/<hash>.json`: per function the grade, truth, clarity, findings with evidence, and the full agent answer.
`index.json`: what a wallet looks up when it shows a screen.

## Related

- [clear-review](https://github.com/clawdbotatg/clear-review): pass/fail second look + one signed root per round
  (the wedgie checks it). clear-score's grades can feed its pass line.
- The registry's own [AI review](https://github.com/ethereum/clear-signing-erc7730-registry/tree/master/docs/ai-review)
  (PRs, one call, no tools); we use its severity scale and Sourcify collector.
- [port's clear-signing-helper](https://portdeveloper.github.io/clear-signing-helper/): generates descriptors.

MIT.
