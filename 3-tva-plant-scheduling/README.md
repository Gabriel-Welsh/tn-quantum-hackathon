# Quantum warm start for TVA plant scheduling

**QAOA finds a near-optimal day → classical repair makes it legal → the exact MILP solver starts from it and proves the perfect answer.**

Our submission is one notebook: **[`TVA_quantum_warm_start.ipynb`](./TVA_quantum_warm_start.ipynb)**. It walks through the whole pipeline with every output already saved, so you can read it without running anything.

The original challenge description is in [`PROBLEM_README.md`](./PROBLEM_README.md). Our talk track is [`PRESENTATION_SCRIPT.md`](./PRESENTATION_SCRIPT.md).

---

## The problem in one paragraph

Every day TVA decides which power plants are **on** for each hour of tomorrow. Output must meet demand every hour. The plants that are on must be able to cover demand plus a safety **reserve**. A plant that starts must stay on for its **minimum up time**, and one that stops must stay off for its **minimum down time**. Cost is startups + hourly running (no-load) cost + fuel. Big plants are cheap to run but expensive to start; small peakers are the opposite. Utilities solve this today with a **MILP** (mixed-integer linear program), an exact solver that finds the cheapest legal day and proves nothing cheaper exists.

## Our solution in one paragraph

We don't ask quantum to replace the MILP. We ask it to give the MILP a **head start**. A 20-qubit QUBO covers the whole day by grouping the 24 hours into 4 blocks, one qubit per plant per block. QAOA samples cheap schedules from it. A classical repair step turns the best samples into a legal day, and that day is handed to HiGHS as its starting solution (a *MIP warm start*). HiGHS then closes the remaining gap and **proves the optimum**. A bad quantum start can waste a little time, but it can never make the final answer wrong.

```
 plants.csv, demand.csv
        │
        ▼
 group 24 h into 4 blocks ──► QUBO (5 plants × 4 blocks = 20 qubits)
        │
        ▼
 QAOA (p=2, trained on simulator, 4,000 shots)      ◄── compared against random guessing
        │
        ▼
 repair the 50 cheapest samples ──► legal day = START STATE (+1.12%)
        │
        ▼
 HiGHS MILP, warm-started ──► PROVEN OPTIMUM ($327,924, 0 rules broken)
```

---

## Headline results (5 plants × 24 hours)

All rule checks use the official checker, `check.check_schedule`.

| Method | Daily cost | vs optimum | Rules broken |
|---|---|---|---|
| Exact MILP (basic, no start) | $327,924 | 0.00% | 0 |
| Cheapest-first rule | $330,594 | +0.81% | 1 |
| QAOA's best raw sample | $313,517 | −4.39% (cheap because illegal) | 7 |
| QAOA + repair = **start state** | $331,596 | +1.12% | 0 |
| **Warm-started MILP (our answer)** | **$327,924** | **0.00%, proven** | **0** |

| Question | Answer |
|---|---|
| Does QAOA beat random guessing? | Yes. 69% of QAOA shots land in the cheapest 5% of all 2²⁰ schedules, against 6% for random |
| How often are answers valid? | 2.4% of raw QAOA shots are legal days, against 0.1% for random. After repair, 100% (random too) |
| What does the warm start do for the MILP? | A legal, near-optimal day at **0 ms**. Cold, the solver has none for 14 ms (5 plants) to 245 ms (40 plants). The primal-dual integral drops 4–37% |
| Hardware vs simulator (10 qubits, 50 CX, 200 shots) | Cheapest-5% share: 34% noiseless, **22% with the IonQ Forte-1 noise model**, 4% random. All three lead to the same proven optimum |

**Honest caveats** (notebook section 10):
- On this data HiGHS proves optimality without branching (1 node), so time to the proven optimum changes within noise. The simulated quantum step (≈8 s) costs far more than the MILP alone (≈30 ms).
- The QUBO's own best answer breaks rules (blocks are coarse and the capacity penalty is soft), so repair is essential.
- The real IonQ QPU has not been run yet. See [Hardware](#hardware) below.

---

## How to view everything

### Option A: just read it

Open `TVA_quantum_warm_start.ipynb` in qBraid Lab or on GitHub. All outputs, tables and charts are saved in the file.

### Option B: run it yourself (about 35 seconds)

1. Open `TVA_quantum_warm_start.ipynb` in qBraid Lab.
2. Select the kernel **qBraid-SDK (v0.12.2)**.
3. **Run → Run All Cells.**

The only extra package is **`highspy`**, the Python API for the HiGHS MILP solver, which the qBraid-SDK environment doesn't include. You don't need to install it: the first time `scheduling/quantum_warm_start_milp.py` is imported (by the notebook, the command line or the web app), it installs `highspy>=1.16` into the running Python environment if it's missing. If that fails (for example with no network), it prints the exact `pip install` command to run, then restart the kernel. Set `QWS_NO_AUTO_INSTALL=1` to turn the automatic install off.

Run it from this folder (`3-tva-plant-scheduling/`). The notebook imports `scheduling/check.py` and `scheduling/quantum_warm_start_milp.py`, and reads `data/` and `explanation/figures/`. Costs and counts reproduce exactly; millisecond timings vary with machine load.

### What each section shows, and what to look at

| § | Section | Look at |
|---|---|---|
| 1 | The problem and the data | Plant table and demand chart |
| 2 | Classical baselines | Exact MILP cost, cheapest-first cost and its broken rule |
| 3 | What we tried before this | Table of attempts (pure QAOA +48% → rule checking +7.5% → blocks +0.85% → full-day QUBO 701 qubits), plus summary and qubit-growth figures |
| 4 | Step 1: the whole day on 20 qubits | Block chart, and the **honest check**: brute force shows the QUBO's own optimum is illegal |
| 5 | Step 2: QAOA vs random guessing | Histogram: QAOA's shots sit far left (cheap) of random's |
| 6 | Step 3: repair → start state | Three schedule strips: raw sample (red ✕ = broken rule), repaired start, MILP optimum |
| 7 | Step 4: MILP cold vs warm | Table plus three timeline charts. The shaded area is the time the cold solver has no legal day; the warm line starts near 0% at 0 ms |
| 8 | Step 5: hardware vs simulator | Backend table with job IDs, and the curves: noisy sim between ideal and random |
| 9 | All results on one page | Everything a judge asked for, printed together |
| 10 | Honest verdict | What works, what doesn't, what would have to change |

### Hardware

Section 8 has three switches at the top of the notebook (section 1 code cell):

| Switch | Device | Cost |
|---|---|---|
| `RUN_NOISY_SIM = True` | `ionq:ionq:sim:simulator` with the `forte-1` noise model | free |
| `RUN_QPU = False` | `QPU_DEVICE = "aws:ionq:qpu:forte-1"` | about 30 credits + 8 per shot (200 shots ≈ 1,630 credits = $16.30) |
| `MAX_CREDITS = 0` | cost guard | the QPU cell refuses to submit if its estimate is above this |

Every job is cached in `outputs/warm_start_results/hardware_runs.json` (job ID, device, shots, status, raw counts, time from submission to result), so re-running never resubmits a finished job. Jobs also appear in the qBraid **Quantum Jobs** panel. The IonQ noisy-simulator job is `ionq:ionq:sim:simulator-842a-qjob-6af901e4c8f5265fb3f21de4` (16 s including queue).

To run the real QPU: check `qbraid account credits`, then set `RUN_QPU = True` and set `MAX_CREDITS` above the printed estimate. Lower `HW_SHOTS` if needed (≤ 200 by the hardware rules). Re-run sections 1 and 8.

---

## Folder map

| Path | What it is |
|---|---|
| **`TVA_quantum_warm_start.ipynb`** | **The submission: the full walk-through** |
| `PRESENTATION_SCRIPT.md` | Speaking script with on-screen cues, Q&A prep and a "where to verify" table |
| `PROBLEM_README.md` | The original challenge description |
| `scheduling/quantum_warm_start_milp.py` | The pipeline: `Milp`, `split_into_blocks`, `Qubo`, `solve_qaoa`, `solve_anneal`, `repair`, `full_solution`, `run_highs`. Also runs from the command line (`--help`, `--selftest`) |
| `scheduling/check.py` | Official checker (`check_schedule`) and scipy MILP baseline (`solve_milp`) |
| `docs/QUANTUM_WARM_START.md` | Plain-language explanation of the pipeline: MILP, branch-and-bound, QUBO, QAOA, CVaR, repair |
| `notebooks/warm_start_vs_milp.ipynb` | Deeper benchmark: shots × seeds sweep, 10-plant case, random-start control |
| `notebooks/starter.ipynb` | The organizers' starter, with our TODOs (hour-by-hour QAOA, +7.06%) |
| `explanation/` | The history: pure QAOA → rule checking → hour grouping → warm start. `README.md`, `figures/01–08`, `results/*.json` |
| `hybrid_uc/` | The Lagrangian-incentives experiment (`ANALYSIS.md`, `RESULTS.md`) |
| `experiments/` | Commitment-search and gas-incentive experiments |
| `input_app/` | Interactive plant/demand editor and solver comparison (what-if tool) |
| `outputs/` | Saved results, including the hardware job cache |
| `data/` | 5- and 10-plant fleets and demand, from RTS-GMLC (`data/README.md`) |
| `background/` | TVA's overview of unit commitment and economic dispatch |

### Command-line use of the pipeline

```bash
PY=~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python
$PY scheduling/quantum_warm_start_milp.py --selftest                    # consistency checks
$PY scheduling/quantum_warm_start_milp.py                               # 5 plants, QAOA, 20 qubits
$PY scheduling/quantum_warm_start_milp.py --copies 8 --solver anneal    # 40 plants, annealing stand-in
```

---

## What we learned

Formulations small enough for QAOA give rough schedules, and formulations that give great schedules need hundreds of qubits (701 for the full 10-plant day). So the most useful role we found for quantum today is **helping the exact solver, not replacing it**. On this toy problem the help is real but small: a good legal answer from time zero. A real speed-up would need problems that force the MILP to branch (ramp limits, multi-day horizons, many similar units, network constraints), plus quantum hardware big and clean enough for finer QUBOs, with short queues.
