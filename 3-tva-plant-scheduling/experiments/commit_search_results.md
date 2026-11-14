# Plant-agnostic commitment search + QAOA: results

Gaps are vs the MILP optimum for each demand curve. QAOA/random cells: valid days out of 3 seeds, mean gap of the valid ones.

| demand curve | MILP $ | commitments found | search s | amortized only | commit + amortized (classical) | QAOA 50 shots | random 50 shots | QAOA 200 shots |
|---|---|---|---|---|---|---|---|---|
| base day | 327,924 | GAS_CC 5-12 | 3.6 | +2.19% | +0.00% | 3/3, +1.40% | 1/3, +5.48% | 3/3, +0.00% |
| demand x0.70 | 229,603 | GAS_CC 8-15 | 3.9 | +3.66% | +0.00% | 2/3, +0.00% | 2/3, +11.21% | 3/3, +0.00% |
| demand x0.85 | 272,844 | GAS_CC 6-13 | 3.7 | +3.12% | +0.00% | 0/3, +nan% | 2/3, +10.23% | 3/3, +0.00% |
| demand x1.05 | 354,772 | GAS_CC 6-13, PEAKER_A 0-10, PEAKER_B 12-14 | 6.6 | +2.45% | +0.78% | 3/3, +1.06% | 1/3, +6.35% | 3/3, +0.78% |
| peak shifted -3 h | 327,924 | GAS_CC 2-9 | 3.5 | +2.19% | +0.00% | 3/3, +1.23% | 3/3, +5.38% | 3/3, +0.00% |
| base +5% noise | 328,461 | PEAKER_A 0-11 | 3.4 | +2.15% | +0.66% | 3/3, +1.31% | 2/3, +10.37% | 3/3, +0.66% |
