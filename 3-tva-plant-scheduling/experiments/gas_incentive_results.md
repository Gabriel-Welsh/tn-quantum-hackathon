# GAS_CC incentive + QAOA: results

MILP optimum: $327,924. 5 seeds per row. Gap is over valid days only. P(pick) = average probability the sampler gave the choice finally kept.

| config | shots | sampler | valid days | mean gap | best gap | P(pick) |
|---|---|---|---|---|---|---|
| A baseline (no incentive) | 10 | qaoa | 2/5 | +11.82% | +8.42% | 0.065 |
| A baseline (no incentive) | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| A baseline (no incentive) | 20 | qaoa | 4/5 | +8.20% | +6.86% | 0.063 |
| A baseline (no incentive) | 20 | random | 1/5 | +10.75% | +10.75% | 0.031 |
| A baseline (no incentive) | 50 | qaoa | 5/5 | +7.74% | +7.06% | 0.064 |
| A baseline (no incentive) | 50 | random | 5/5 | +9.44% | +7.64% | 0.031 |
| A baseline (no incentive) | 200 | qaoa | 5/5 | +7.06% | +7.06% | 0.064 |
| A baseline (no incentive) | 200 | random | 5/5 | +7.06% | +7.06% | 0.031 |
| B amortized startup | 10 | qaoa | 1/5 | +8.42% | +8.42% | 0.066 |
| B amortized startup | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| B amortized startup | 20 | qaoa | 2/5 | +7.17% | +6.98% | 0.063 |
| B amortized startup | 20 | random | 1/5 | +10.23% | +10.23% | 0.031 |
| B amortized startup | 50 | qaoa | 5/5 | +4.22% | +2.19% | 0.062 |
| B amortized startup | 50 | random | 3/5 | +8.54% | +7.83% | 0.031 |
| B amortized startup | 200 | qaoa | 5/5 | +2.19% | +2.19% | 0.062 |
| B amortized startup | 200 | random | 5/5 | +2.19% | +2.19% | 0.031 |
| C GAS bonus $2k/h | 10 | qaoa | 2/5 | +12.01% | +8.42% | 0.065 |
| C GAS bonus $2k/h | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| C GAS bonus $2k/h | 20 | qaoa | 4/5 | +8.20% | +6.86% | 0.063 |
| C GAS bonus $2k/h | 20 | random | 1/5 | +11.75% | +11.75% | 0.031 |
| C GAS bonus $2k/h | 50 | qaoa | 5/5 | +7.80% | +7.06% | 0.064 |
| C GAS bonus $2k/h | 50 | random | 5/5 | +9.44% | +7.64% | 0.031 |
| C GAS bonus $2k/h | 200 | qaoa | 5/5 | +7.06% | +7.06% | 0.064 |
| C GAS bonus $2k/h | 200 | random | 5/5 | +7.06% | +7.06% | 0.031 |
| D GAS bonus $5k/h | 10 | qaoa | 2/5 | +12.01% | +8.42% | 0.065 |
| D GAS bonus $5k/h | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| D GAS bonus $5k/h | 20 | qaoa | 4/5 | +8.36% | +7.20% | 0.063 |
| D GAS bonus $5k/h | 20 | random | 1/5 | +11.75% | +11.75% | 0.031 |
| D GAS bonus $5k/h | 50 | qaoa | 5/5 | +7.80% | +7.06% | 0.064 |
| D GAS bonus $5k/h | 50 | random | 5/5 | +9.44% | +7.64% | 0.031 |
| D GAS bonus $5k/h | 200 | qaoa | 5/5 | +7.06% | +7.06% | 0.064 |
| D GAS bonus $5k/h | 200 | random | 5/5 | +7.06% | +7.06% | 0.031 |
| E GAS commit pre-pass | 10 | qaoa | 1/5 | +8.72% | +8.72% | 0.065 |
| E GAS commit pre-pass | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| E GAS commit pre-pass | 20 | qaoa | 2/5 | +7.83% | +6.87% | 0.063 |
| E GAS commit pre-pass | 20 | random | 1/5 | +11.75% | +11.75% | 0.031 |
| E GAS commit pre-pass | 50 | qaoa | 5/5 | +2.35% | +1.18% | 0.062 |
| E GAS commit pre-pass | 50 | random | 4/5 | +4.48% | +3.39% | 0.031 |
| E GAS commit pre-pass | 200 | qaoa | 5/5 | +1.18% | +1.18% | 0.062 |
| E GAS commit pre-pass | 200 | random | 5/5 | +1.18% | +1.18% | 0.031 |
| F commit + amortized | 10 | qaoa | 1/5 | +8.72% | +8.72% | 0.066 |
| F commit + amortized | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| F commit + amortized | 20 | qaoa | 2/5 | +7.32% | +5.83% | 0.063 |
| F commit + amortized | 20 | random | 1/5 | +11.23% | +11.23% | 0.031 |
| F commit + amortized | 50 | qaoa | 5/5 | +2.66% | +0.00% | 0.061 |
| F commit + amortized | 50 | random | 3/5 | +6.59% | +5.48% | 0.031 |
| F commit + amortized | 200 | qaoa | 5/5 | +0.00% | +0.00% | 0.061 |
| F commit + amortized | 200 | random | 5/5 | +0.00% | +0.00% | 0.031 |
| G commit + amortized, low penalty | 10 | qaoa | 1/5 | +8.72% | +8.72% | 0.066 |
| G commit + amortized, low penalty | 10 | random | 0/5 | +nan% | +nan% | 0.031 |
| G commit + amortized, low penalty | 20 | qaoa | 3/5 | +6.09% | +5.51% | 0.062 |
| G commit + amortized, low penalty | 20 | random | 1/5 | +11.23% | +11.23% | 0.031 |
| G commit + amortized, low penalty | 50 | qaoa | 5/5 | +2.66% | +0.00% | 0.061 |
| G commit + amortized, low penalty | 50 | random | 3/5 | +6.59% | +5.48% | 0.031 |
| G commit + amortized, low penalty | 200 | qaoa | 5/5 | +0.00% | +0.00% | 0.061 |
| G commit + amortized, low penalty | 200 | random | 5/5 | +0.00% | +0.00% | 0.031 |
