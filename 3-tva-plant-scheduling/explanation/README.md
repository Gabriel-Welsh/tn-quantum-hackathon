# How we got from pure QAOA to a quantum warm start for the MILP

This folder explains our path through the TVA plant-scheduling problem in four steps:

1. Pure QAOA scaled badly against the MILP.
2. We added rule checking.
3. We grouped hours together, up to one QUBO for the whole day.
4. We gave up on QAOA *replacing* the MILP and used it to *warm-start* the MILP instead.

Every number below comes from `results/*.json`. Every figure comes from `make_figures.py`. Every experiment was re-run with `run_experiments.py`, which only *calls* the project's existing code in `../scheduling/` (`check.py`, `run_qaoa_schedule.py`, `block_qubo.py`, `run_all_24h_qaoa_schedule.py`, `quantum_warm_start_milp.py`) and changes none of it.

**Everything quantum here is simulated** on an exact statevector on this Lab instance. No jobs were submitted and no credits were used.

---

## The test fleets

To vary the number of plants we take the **first N plants of `data/plants10.csv`** (N = 3 … 10). Demand is `data/demand10.csv` scaled by the capacity of those N plants divided by the capacity of all 10, and the reserve is 10% of demand. N = 5 reproduces `data/plants.csv` + `data/demand.csv` exactly (MILP optimum $327,924). N = 10 is the 10-plant file itself. Every fleet has a valid schedule.

The warm-start experiment needs bigger MILPs, so it uses `quantum_warm_start_milp.bigger_fleet` instead: 1, 2, 4, 8 and 16 copies of the 5-plant fleet, giving 5 to 80 plants. Each copy's costs are jittered by up to ±8%, and demand is multiplied by the number of copies.

"Gap" always means (daily cost − MILP optimum) / MILP optimum. The MILP is the exact optimum from HiGHS (`check.solve_milp`).

---

## 1. Pure QAOA vs the MILP — `figures/01_pure_qaoa_vs_milp.png`

**What "pure" means:** each hour gets its own one-hour QUBO: plant costs plus a capacity penalty with slack qubits, the starter's formulation, built by `run_qaoa_schedule.build_qubo`. QAOA p=1 is tuned on the statevector, then sampled 200 times, and the lowest-energy sample is kept. There is **no** classical help: no min up/down locks, no validity check and no repair.

| Plants | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|
| Qubits per hour | 7 | 8 | 9 | 10 | 11 | 13 | 14 | 15 |
| Gap vs MILP (mean of 3 seeds) | +17.8% | +3.3% | +10.1% | +29.7% | +39.3% | +46.5% | +41.4% | **+48.1%** |
| Rules broken per day | 9.7 | 2.0 | 2.7 | 12.3 | 16.3 | 22.0 | 22.0 | **28.0** |

**What it shows:** as the fleet grows, pure QAOA's schedules get both more expensive and less valid. Two reasons, both diagnosed in `../notebooks/qaoa_improvements.ipynb`:

- The capacity penalty dominates the energy, so QAOA learns "have enough capacity" much better than "be cheap".
- One hour at a time, it cannot see the min up/down rules or a startup that pays off later.

---

## 2. Adding rule checking — `figures/02_rule_checking.png`

**What "rule checking" means:** `run_qaoa_schedule.schedule_day` with the look-ahead credit off (`use_credit=False`) and local search on. Each hour it:

1. adds penalties for plants that min up/down times force on or off (`check.locks`);
2. adds a feasibility lock: a running plant stays on if switching it off would leave a later hour short of capacity;
3. only picks a sample that passes `hour_ok` and the look-ahead, choosing the cheapest by exact cost;
4. improves or repairs that pick by classical local search.

| Plants | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|
| Pure QAOA gap | +17.8% | +3.3% | +10.1% | +29.7% | +39.3% | +46.5% | +41.4% | +48.1% |
| **+ rule checking gap** | +2.1% | +1.9% | +7.1% | +5.4% | +4.7% | +5.2% | +5.5% | **+7.5%** |
| Rules broken, + rule checking | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**What it shows:** rule checking makes every day valid and cuts the 10-plant gap from 48% to 7.5%. A 2–7% gap remains, and it does not shrink with size. That gap belongs to the hour-by-hour structure, not to QAOA: even a perfect per-hour solver leaves 7.06% on the 5-plant day (`qaoa_improvements.ipynb` §4a). At hour 5 the loop won't pay GAS_CC's startup, because it can't see that GAS_CC will be needed anyway from hour 8. Much of the work is also now classical (locks, validity checks, local search).

---

## 3. Grouping hours together — `figures/03_hour_grouping.png`

To let the QUBO see across hours, we grouped the 24 hours into **K blocks** of roughly flat demand (`block_qubo.py`). Each plant gets one on/off bit per block, and startups and min up/down rules go *inside* the QUBO. In the limit, the **full 24-hour QUBO** (`run_all_24h_qaoa_schedule.py`) has one bit per plant per hour, plus start, stop and slack helper bits: the whole day as one problem.

- QAOA p=1 (1000 shots) was used whenever the block QUBO had ≤ 16 qubits. Larger ones used simulated annealing on the *same* QUBO (the `solver` field in `results/blocks.json` records which). The full-day QUBO has 279–701 qubits, so it can only be annealed.
- "Polish" is the classical local search in `block_qubo.run`, which moves block edges hour by hour.

10-plant results (all valid after polish):

| Method | Qubits | Solver | Gap as solved | Gap after polish |
|---|---|---|---|---|
| Hour by hour + rule checking | 15 × 24 runs | QAOA | — | +7.51% |
| K = 2 blocks | 20 | anneal | +6.41% | +1.21% |
| K = 3 blocks | 34 | anneal | +4.37% | +0.85% |
| K = 4 blocks | 53 | anneal | +3.20% | +0.85% |
| K = 6 blocks | 86 | anneal | +2.56% | +0.85% |
| Full 24-hour QUBO | 701 | anneal | +0.48% | **+0.24%** |

**What it shows:** the more of the day one QUBO sees, the better the schedule. Grouping beats hour-by-hour at every fleet size after polish, and the full-day QUBO is within 0–1% of the MILP everywhere. 7 of the 40 raw block answers broke a rule before polish, all at K ≤ 4.

The catch is that the good results need far more qubits than QAOA can handle. Only the small block QUBOs (≤ 16 qubits, mostly 3–8 plants) were actually run with QAOA. Everything better was annealing, a classical stand-in for what a quantum annealer would do.

---

## 4. Qubits grow with every plant — `figures/04_qubit_growth.png`

Counts come from the project's own QUBO builders, with no solving involved.

| Plants | 3 | 5 | 8 | 10 |
|---|---|---|---|---|
| One hour (24 separate runs) | 7 | 9 | 13 | 15 |
| K = 2 blocks | 1 | 8 | 16 | 20 |
| K = 4 blocks | 3 | 15 | 43 | 53 |
| K = 6 blocks | 11 | 30 | 72 | 86 |
| K = 12 blocks | 21 | 63 | 178 | 207 |
| Full 24-hour QUBO | 279 | 377 | 605 | 701 |

**How to read it:** each plant adds a fixed number of qubits *per time step*. So qubits grow with plants × time steps, about linearly in each. What explodes is the **search space**: a QAOA circuit on q qubits works over all 2^q bitstrings at once, so every extra plant multiplies the state space by 2^(time steps). The full day for 10 plants is 2^701 ≈ 10^211 bitstrings. Exact simulation stops near 20–30 qubits (2^30 amplitudes is a 16 GB statevector). Today's QPUs can't run hundreds of high-quality qubits with the very many two-qubit gates these QUBOs need: even the 5-plant, 2-block QUBO in `../docs/QUANTUM_WARM_START.md` §4b already has 25 RZZ gates per layer. Block counts can dip, as from 5 to 6 plants at K=2, because presolve fixes bits no valid schedule can change.

**The dilemma:** the formulations that give good schedules (whole day, many blocks) need the most qubits, and the ones that fit on a quantum computer (one hour, two blocks) leave the biggest gaps.

---

## 5. Why we ended up warm-starting the MILP — `figures/05_warm_start_timeline.png`, `figures/06_warm_start_metrics.png`

Steps 1–4 point to one conclusion. A QAOA-sized QUBO can produce a *good* schedule, but it can't produce a *proven optimal* one, and it can't scale to a whole day. The MILP is exact and fast, but it starts from nothing. So we combined them (`../scheduling/quantum_warm_start_milp.py`, explained in `../docs/QUANTUM_WARM_START.md`):

1. A small block QUBO (QAOA when ≤ 20 qubits, annealing above that) proposes on/off schedules.
2. Classical `repair` makes them legal, and the cheapest one becomes a full MILP solution vector.
3. HiGHS gets that vector as its starting incumbent (a MIP start), then solves the exact MILP as usual.

The final answer is always the true optimum. A bad start can't make it wrong; a good start lets HiGHS discard ("prune") worse branches from the first moment, and it means a near-optimal schedule exists at t = 0.

Measured (HiGHS 1.16, 1 thread, median of 3 seeds):

| Plants | Qubits / solver | Warm start vs optimum | Time to proven optimum, cold → warm | Primal-dual integral, cold → warm | Time until a schedule ≤ 2.5% from optimal, cold → warm |
|---|---|---|---|---|---|
| 5 | 20 / QAOA | +1.12% | 0.039 → 0.036 s (−7%) | 0.019 → 0.015 (−18%) | 19 → **0** ms |
| 10 | 20 / QAOA | +1.82% | 0.051 → 0.046 s (−10%) | 0.032 → 0.024 (−26%) | 50 → **0** ms |
| 20 | 80 / anneal | +1.78% | 0.111 → 0.086 s (−23%) | 0.070 → 0.043 (−39%) | 70 → **0** ms |
| 40 | 160 / anneal | +2.19% | 0.527 → 0.526 s (0%) | 0.242 → 0.232 (−4%) | 238 → **0** ms |
| 80 | 320 / anneal | +2.24% | 0.529 → 0.527 s (0%) | 0.246 → 0.227 (−8%) | 243 → **0** ms |

**How it shortens the time to the optimum:**

- **A good answer immediately.** Cold, HiGHS has nothing for the first 19–243 ms, and at 5 and 10 plants its first schedule is 18% and 28% too expensive (figure 05). Warm, a schedule within 1–2.3% of optimal is known at 0 ms.
- **Less total waiting for good answers.** The primal-dual integral (the area under the "gap over time" curve) drops 4–39%.
- **Faster proof at small and medium sizes.** Time to a proven optimum drops 7–23% up to 20 plants.

**Honest caveat:** on this data HiGHS proves optimality at the root node (1 branch-and-bound node) for every fleet, so there is almost no search tree to prune. That's why total time barely moves at 40–80 plants. The warm start's main value here is being near-optimal from second zero. A real total-time speedup needs MILPs that HiGHS has to branch on, such as ones with ramp limits, longer horizons or larger symmetric fleets. Timings are on a shared instance and are noisy at the millisecond level.

---

## 6. Summary — `figures/07_summary.png`

The path on the 10-plant fleet:

| Pure QAOA | + rule checking | K=3 blocks, polished | Full-day QUBO, polished | Quantum start | HiGHS from quantum start |
|---|---|---|---|---|---|
| +48.13%, 28 rules broken | +7.51% | +0.85% (34 qubits, anneal) | +0.24% (701 qubits, anneal) | +1.82% (20 qubits, QAOA) | **0.00%, proven optimal** |

---

## What was run to make what

All commands run from `3-tva-plant-scheduling/`, with the qBraid-SDK environment's Python, which has Qiskit, highspy and matplotlib:

```bash
PY=~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python

$PY explanation/run_experiments.py qubits   # -> results/qubits.json   (~1 min)
$PY explanation/run_experiments.py warm     # -> results/warm.json     (~3 min; run alone, it times HiGHS)
$PY explanation/run_experiments.py blocks   # -> results/blocks.json   (~25 min, log in results/blocks.log)
$PY explanation/run_experiments.py pure     # -> results/pure.json     (~20 min, log in results/pure.log)
#   (or: $PY explanation/run_experiments.py all)

$PY explanation/make_figures.py             # -> figures/*.png (reads only results/*.json, a few seconds)
```

`warm` was run on its own. `blocks` and `pure` then ran in parallel in the background (the `.log` files are their output).

| Figure | Data | Experiment function in `run_experiments.py` | Project code it calls |
|---|---|---|---|
| `01_pure_qaoa_vs_milp.png` | `pure.json` | `exp_pure` → `pure_qaoa_day` | `run_qaoa_schedule.QAOA`, `build_qubo`, `plant_hour_costs`; `check.check_schedule`, `solve_milp` |
| `02_rule_checking.png` | `pure.json` | `exp_pure` (`method="rules"`) | `run_qaoa_schedule.schedule_day(use_credit=False, use_local_search=True)` |
| `03_hour_grouping.png` | `blocks.json` (+ `pure.json` for the dashed line) | `exp_blocks` | `block_qubo.make_blocks`, `BlockQubo`, `run`; `run_all_24h_qaoa_schedule.build_day_qubo`, `anneal_x`, `polish` |
| `04_qubit_growth.png` | `qubits.json` | `exp_qubits` | `block_qubo.BlockQubo` (sizes only), `run_all_24h_qaoa_schedule.build_day_qubo` |
| `05_warm_start_timeline.png` | `warm.json` | `exp_warm` → `highs_with_timeline` | `quantum_warm_start_milp.bigger_fleet`, `Milp`, `split_into_blocks`, `Qubo`, `solve_qaoa`, `solve_anneal`, `repair`, `true_cost`, `full_solution` |
| `06_warm_start_metrics.png` | `warm.json` | `exp_warm` | same as 05 |
| `07_summary.png` | `pure.json`, `blocks.json`, `warm.json` | — | — |

Settings worth knowing when reading the numbers:

- **Hour-by-hour (pure and rule checking):** QAOA p=1, COBYLA maxiter 60, 200 shots, 3 sampling seeds (0, 1, 2). The capacity penalty is A = 2 × max(c) with 50 MW blocks. Slack qubits are sized so the penalty can reach zero every hour, so 5 plants use 9 qubits rather than the starter's 8.
- **Blocks:** K ∈ {2, 3, 4, 6}, demand-flattening DP split, QAOA p=1 with 1000 shots and maxiter 100 when ≤ 16 qubits, otherwise annealing (400 sweeps × 8 chains). Seed 7.
- **Full day:** `anneal_x`, 300 sweeps × 8 chains, seed 7, then `polish`.
- **Warm start:** K = 4 blocks for 5 plants, 2 for 10, 4 for 20+. QAOA p=2 with 4000 shots (numpy statevector sampler, CVaR α = 0.25), or annealing. The top 50 candidates are repaired. HiGHS runs 3 seeds per mode with a 120 s limit.

Re-running gives the same results except for HiGHS wall-clock times, which vary with machine load.
