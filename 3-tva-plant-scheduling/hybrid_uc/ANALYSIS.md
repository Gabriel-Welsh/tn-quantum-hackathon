# Hybrid unit commitment: what the benchmark shows

All numbers are from `hybrid_uc/RESULTS.md` (`python -m hybrid_uc.analyze`, noise-free statevector simulator).
Gaps are cost above the MILP optimum from `check.py`, which is the standard throughout.

## The pipeline

1. **Classical incentives.** Lagrangian prices for energy and reserve split the day into one small problem
   per plant (exact dynamic program over on/off and hours held). That gives each plant's priced cost-to-go,
   which is added to each hour's QUBO, plus a lower bound on the optimal cost.
2. **QAOA, hour by hour.** p = 1 QAOA samples each hour's on/off choice. Plants that min up/down already
   force on or off are set classically and are not qubits, so each hour uses at most N + 3 qubits.
3. **Classical repair.** Local search with small moves (shift, drop, bridge, paired swaps) and large moves
   (drop or cut a block, then greedily refill), scored with the exact cost. It reports a certified bound:
   how far above the optimum the result can be at most, with no MILP needed.

## Takeaways

1. **Accuracy target met on toy problems.** After repair, the QAOA hybrid is within **+0.00% to +0.34%** of
   the MILP for 5 to 16 plants (A, C, E), and **+0.00%** on the real fleet across six demand curves (A, B).
   Every repaired day is valid.
2. **The accuracy comes from the classical stages.** The notebook's hour-by-hour loop is +7.06% on the real
   fleet. Lagrangian incentives with every choice enumerated give +0.00% (5 and 8 plants) and +0.13%
   (12 plants) before any repair. The classical-only reference (Lagrangian schedule + repair, no sampler)
   reaches **+0.00% at every size tested** (A, C).
3. **QAOA's contribution is sample efficiency, and it appears from 8 plants up.** Before repair, which
   isolates the sampler (E):

   | plants | shots | QAOA | random |
   |---|---|---|---|
   | 8 | 25 | 3/3 valid, +9.6% | 0/3 valid |
   | 8 | 100 | +3.2% | +5.5% |
   | 8 | 200 | +1.0% | +2.5% |
   | 12 | 25 | 2/3 valid, +18.7% | 0/3 valid |
   | 12 | 100 | +9.6% | +14.0% |
   | 12 | 200 | +7.2% | +10.1% |

   At 12 plants QAOA with 100 shots is about as good as random with 200. At 5 plants there is no advantage:
   only about 8 qubits are left per hour and random sampling already covers almost every choice.
4. **The edge grows with problem size.** The probability QAOA puts on the choice that is kept, relative to
   random: **1.9x at 8 plants, 2.9x at 12, 22.8x at 16** (C, 200 shots; the 16-plant figure is from 2 seeds).
5. **After repair, QAOA and random end up the same** (differences of a few tenths of a percent, either way,
   within seed noise). Repair hides the sampler's quality in the final number.
6. **Repair is the expensive part.** Seconds to a minute per day for 8 to 16 plants, against about 0.1 s
   for the MILP. QAOA starting points need 10 to 50% fewer repair moves, but not less repair time,
   because the search spends most of its time confirming that no larger move helps.
7. **The classical stages scale** (D): Lagrangian schedule + repair is within **0.007% to 0.017%** of the
   MILP from 25 to 200 plants, and the certified bound tightens from 1.22% (10 plants) to **0.06%**
   (200 plants). The MILP is still faster: 14.7 s against about 142 s at 200 plants.

## What this supports, and what it does not

- Supported: a QAOA-based pipeline that takes any fleet and matches the MILP within a fraction of a
  percent on problems small enough for today's quantum hardware, with a QAOA stage that measurably beats
  random sampling and whose edge widens as problems grow.
- Not supported: any speed or cost advantage over the MILP, or any claim that QAOA improves the final
  schedule at these sizes. The classical-only pipeline does as well.

## Limits

- Noise-free simulation. Hardware noise pushes QAOA's output toward random, so the edge measured here is an
  upper bound for current machines. The IonQ run (milestone 5) is the first reality check.
- Small seed counts (2 to 5). Differences under about 0.5% after repair are not meaningful.
- Synthetic fleets are built from the five real plant types.
- Simulation cost doubles per qubit; 16 plants (19 qubits) is the practical ceiling on this instance.
- The baseline sampler is uniform random. Stronger classical samplers (simulated annealing, greedy
  heuristics) are the bar to clear next.

## Pitch line

On problems small enough for today's quantum hardware, our QAOA hybrid matches the MILP optimum within
0 to 0.34%. From 8 plants up, QAOA reaches the same quality as random sampling with about half the shots,
and that edge grows with problem size. The classical stages (incentives, repair, certified bounds) already
scale to 200 plants, so a better quantum sampler can drop in without changing the rest of the pipeline.
