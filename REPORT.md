# Report

10 descriptors scored. Rubric v1.1.

A: 2 · B: 1 · C: 2 · F: 5

| Grade | Truth | Clarity | File | Worst finding |
|---|---|---|---|---|
| F | 25 | 71 | `registry/uniswap/calldata-UniswapV3Router02.json` | exactInput is payable but no field shows the native ETH sent with the call. |
| F | 50 | 49 | `registry/ethena/calldata-ethena.json` | cooldownShares restarts the cooldown timer for USDe already in cooldown, and the screen does not say so. |
| F | 62 | 34 | `registry/safe/calldata-SafeMigration-1.4.1.json` | migrateWithFallbackHandler replaces the Safe's fallback handler, but its screen is the same as migrateSingleton's. |
| F | 75 | 49 | `registry/1inch/calldata-AggregationRouterV3.json` | swap is payable and has no @.value field; with REQUIRES_EXTRA_ETH, ETH beyond the shown amount leaves |
| F | 86 | 26 | `registry/1inch/calldata-AggregationRouterV4.json` | swap is payable, and with the _REQUIRES_EXTRA_ETH flag any extra native value leaves, never shown |
| C | 97 | 56 | `registry/paraswap/calldata-AugustusSwapper-v5.json` | simpleBuy hides partner and feePercent, which decide the fee cut from what the beneficiary receives. |
| A | 100 | 92 | `registry/consensus-specs/calldata-DepositContract.json` |  |
| A | 100 | 90 | `registry/kiln/calldata-kiln-batch-exit.json` |  |
| C | 100 | 55 | `registry/threshold/calldata-TBTCVault.json` |  |
| B | 100 | 87 | `registry/uniswap/calldata-UniswapV2Router02.json` | swapExactTokensForETHSupportingFeeOnTransferTokens sentence omits the recipient; in case 13 the ETH went elsewhere. |

Model cost (list price, from the CLI): $5.08.
