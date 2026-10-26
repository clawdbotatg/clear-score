---
name: score-one
description: Score or explain one ERC-7730 descriptor by hand with clear-score - why it got its grade, what the real transactions did, what the blind reader understood, and the fix to send upstream. Use when asked about one descriptor's score, "why is X an F", or to write up a fix for the registry.
---

# One descriptor

1. Find it: `./score.py list`, then its hash in `work/catalog.json`.
2. `./score.py prep <file>` (or reuse `work/<hash>/`), `./score.py run <file> --workers 1 --force`.
3. Read `scores/<hash>.json` → `formats` (grade per function) and `answer.formats[].findings`.
4. For each critical: open the case (`work/<hash>/cases/<i>.json`): `screen` vs `mined.effects` (signer = out / in
   / grant). Check the code line the evidence quotes in `work/<hash>/contracts/`.
5. Explain in plain words: what the screen says, what really happens, the fix (descriptor JSON).
6. Upstream: a confirmed critical becomes an issue or a PR on ethereum/clear-signing-erc7730-registry with
   the case, the receipt and the fix. Ask Austin before posting anything there.
