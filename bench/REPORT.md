# Bench: planted bugs

Caught 5 of 6.

| Mutation | Descriptor | Function | Original | Mutant | Caught |
|---|---|---|---|---|---|
| hide-party | `calldata-UniswapV2Router02.mut-hide-party.json` | addLiquidity | A 100 | F 0 | ✅ |
| hide-amount | `calldata-UniswapV2Router02.mut-hide-amount.json` | addLiquidity | A 100 | F 25 | ✅ |
| swap-token | `calldata-UniswapV2Router02.mut-swap-token.json` | addLiquidity | A 100 | F 25 | ✅ |
| flip-intent | `calldata-UniswapV2Router02.mut-flip-intent.json` | addLiquidity | A 100 | F 0 | ✅ |
| min-max | `calldata-UniswapV2Router02.mut-min-max.json` | addLiquidity | A 100 | B 90 | ❌ |
| drop-value | `calldata-UniswapV2Router02.mut-drop-value.json` | addLiquidityETH | A 100 | F 25 | ✅ |
