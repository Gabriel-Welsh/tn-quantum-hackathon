# Quantum Warm Start for the Plant-Scheduling MILP

Script: [`quantum_warm_start_milp.py`](./quantum_warm_start_milp.py). It is standalone and needs no other file in this folder except the CSVs in `data/`.

This page explains what the script does and why, for teammates who know some Python but have not met MILP, branch-and-bound, QUBO or QAOA before. The script may still change a little while it is being debugged, so treat function details here as a guide and the code as the final word.

---

## 1. The idea in one paragraph

A quantum algorithm (QAOA) proposes a good on/off schedule for the plants. A short classical "repair" step fixes it so it obeys every rule. We then hand that legal schedule to HiGHS, the classical solver, as its **starting solution** (a "MIP warm start"). HiGHS still finds the true optimum on its own. The quantum guess is only there to help it finish sooner.

**Analogy.** Think of a sudoku contest where you must prove your answer is the best possible, not just find one. If a friend hands you a nearly finished grid at the start, you can ignore every line of attack that obviously can't beat it. You spend your time checking the few attacks that might, instead of wandering the whole puzzle. Branch-and-bound works the same way. A good answer in hand from the first second lets it throw away ("prune") large parts of its search early.

---

## 2. Background: MILP and branch-and-bound

### What the MILP is here

A **MILP** (mixed-integer linear program) is a list of variables, a cost to minimize, and rules written as linear inequalities. Some variables must be whole numbers (here: 0 or 1).

For every plant `i` and hour `t` (24 hours) there are three variables:

| Variable | Type | Meaning |
|---|---|---|
| `u[i,t]` | 0/1 | plant is **on** this hour |
| `v[i,t]` | 0/1 | plant was **started** this hour (off last hour, on now) |
| `p[i,t]` | number (MW) | how much the plant **produces** |

**Cost to minimize** = no-load cost × `u` + startup cost × `v` + marginal cost × `p`, summed over all plants and hours.

**Rules** (each is a group of rows in class `Milp`, one per plant and/or hour):

| Rule name in code | Plain words |
|---|---|
| `demand` | Total output each hour equals demand exactly. |
| `reserve` | The plants that are on could together make at least demand + reserve (spinning reserve). |
| `pmin` / `pmax` | An on plant makes between its minimum and maximum. An off plant makes 0. |
| `startup` | If a plant is on now and was off last hour, `v` must be 1. Hour 0 compares with the midnight state (`on_at_start`). |
| `min-up` | If it started in the last `min_up_h` hours, it must still be on. |
| `min-down` | If it was on and then switched off, it cannot start again until `min_down_h` hours have passed. |

On the 5-plant data this is 360 variables (240 of them 0/1). The script prints the exact numbers of variables and rules when it starts.

### What branch-and-bound does

If you **drop** the "must be 0 or 1" requirement and let `u` be any fraction like 0.37, the problem becomes an ordinary LP (linear program). LPs are very fast to solve. This relaxed problem is called the **LP relaxation**. Its answer is never worse than the true answer, because it is allowed more freedom. So it gives a **lower bound**: "the real optimum costs at least this much".

Branch-and-bound uses that trick over and over:

1. Solve the LP relaxation. If some `u` comes out fractional (say 0.37), **branch**: make two smaller problems, one with `u = 0` and one with `u = 1`.
2. Each smaller problem is a **node** in a search **tree**. Solve its LP relaxation too.
3. If a node's lower bound is already worse than the best legal schedule found so far, **prune** it. Nothing below it can win.
4. Repeat until every node is solved or pruned.

**Why it can be slow:** with 240 on/off variables the tree could in principle have 2^240 leaves. **Why it is usually fast:** LP relaxations are cheap and prune huge branches at once. The better the best-known answer, the more branches get pruned. That is exactly where a warm start helps.

### Words you'll see in the output

| Word | Meaning |
|---|---|
| **Incumbent** | The best legal schedule found so far (an upper bound on the optimum). |
| **Bound** | The best lower bound proven so far: "no schedule can cost less than this". |
| **Gap** | (incumbent − bound) / incumbent. 0% means the incumbent is proven optimal. |
| **Nodes** | How many tree nodes branch-and-bound explored. Fewer means less searching. |
| **Time to first incumbent** | How long before the solver had *any* legal answer. A warm start makes this almost zero. |
| **Primal-dual integral** | The area under the "gap over time" curve. It is small if the solver gets a good answer early *and* closes the gap quickly. It is the fairest single number for "how much did the start help over the whole run". |

---

## 3. The pipeline

```
 plants.csv, demand.csv
          |
          v
 load_plants / load_demand  --(--copies N)-->  bigger_fleet
          |
          +------------------------------+
          v                              v
 split_into_blocks (K blocks)          Milp  (exact u, v, p model)
          |                              |
          v                              |
 Qubo  (plants x K bits)                 |
          |                              |
          v                              |
 solve_qaoa | solve_anneal | solve_exact |
   (ranked candidate bitstrings)         |
          |                              |
          v                              |
 to_schedule -> repair -> full_solution  |
   (legal schedule + dispatch = x)       |
          |                              |
          v                              v
        run_highs(model, start=x)   vs   run_highs(model, start=None)
              "warm"                          "cold"
                        \                 /
                         comparison table
```

### Step 0: load the data (`load_plants`, `load_demand`, `bigger_fleet`)

`load_plants` reads each plant's size (`pmin_mw`, `pmax_mw`), costs, minimum up/down times and its midnight state. `load_demand` reads 24 hourly demand and reserve values.

`bigger_fleet` (used with `--copies N`) makes N copies of every plant, each with its costs nudged by up to ±8% so the copies are not identical, and multiplies demand by N. Many near-identical plants make branch-and-bound much harder, because there are lots of almost equally good branches to tell apart. That is the regime where a warm start has something to help with.

### Step 1: build the exact MILP (`Milp`)

`Milp` builds the model from section 2 as a sparse matrix: minimize `c·x` subject to `row_lo ≤ A x ≤ row_hi`. Helper methods `U(i,t)`, `V(i,t)`, `P(i,t)` give the position of each variable in the long vector `x`. `violations(x)` lists the names of every rule a candidate `x` breaks (an empty list means it is legal). `to_highs()` converts the model to HiGHS's format.

### Step 2: group hours into blocks (`split_into_blocks`)

A full-day QUBO would need one qubit per plant per hour: 5 × 24 = 120 qubits, far too many to simulate. So we group the 24 hours into **K blocks** of consecutive hours, and give each plant **one bit per block**: "on for the whole block" or "off for the whole block".

- Qubits = plants × K instead of plants × 24. With 5 plants and K = 4 that is 20 qubits.
- `split_into_blocks` picks the cut points so demand is as flat as possible inside each block (a small dynamic-programming search minimizing the spread of demand around each block's average). Night hours end up together, the morning ramp together, and so on.
- By default K = `max_qubits // plants` (20 // 5 = 4) for QAOA and brute force. The annealer has no qubit limit, so it (and any fleet too big for 2 QAOA blocks) gets K = 4. `--blocks` overrides both.

Blocks lose detail (a plant cannot switch mid-block). That is acceptable: the result is only a starting guess, and HiGHS fixes the details later.

### Step 3: write the problem as a QUBO (`Qubo`)

A **QUBO** is a cost function over 0/1 bits that has only single-bit terms and pair terms:

```
Energy(x) = offset + sum_k Q[k,k] x_k + sum_{k<l} Q[k,l] x_k x_l
```

That shape is what QAOA (and quantum annealers) can handle directly. Bit `k = i*K + b` means "plant `i` is on during block `b`". The energy has three parts:

1. **Running cost** (single-bit term). If plant `i` is on in block `b`, it costs about
   `hours_in_block × (no_load + marginal_cost × rho × pmax)`,
   where `rho` = demand / (demand + reserve), the average fraction of its size a plant is assumed to run at. This is an estimate. The true output depends on which other plants are on.

2. **Startup cost** (pair term). A start in block `b` happens when the plant is on now and was off in the previous block, which is `x_b · (1 − x_{b−1})`. Multiplied out, that is `+startup × x_b` (single) and `−startup × x_b x_{b−1}` (pair). For block 0 the "previous block" is the plant's known midnight state, so it is just a single-bit term (zero if the plant was already on).

3. **Capacity penalty** (single and pair terms). Each block must have enough capacity on to cover its worst hour: `need = max(demand + reserve)` in the block. With `h = (sum of pmax of on plants − need) / need`, we add
   `A × (h − target)^2`, with `target = 0.5`.
   This squared term is smallest when the capacity on is about 1.5 × need. It grows quickly if there is too little capacity, and it also discourages switching on far too much. Squaring a sum produces pair terms between every two plants in the same block. `A` is scaled to the block's typical dollar cost, times `--penalty`. This is a "penalty-only" (unbalanced) formulation: it uses **no slack/helper qubits**, unlike the starter notebook's one-hour QUBO.

Min up/down times are **not** in the QUBO. Blocks are several hours long, which already handles much of that, and repair (step 5) handles the rest.

`energy(x)` scores one bitstring. `all_energies()` scores all 2^N bitstrings at once (used by QAOA simulation and brute force). `to_schedule(x, T)` expands bits back into a 24 × plants on/off table.

### Step 4: solve the QUBO

The script has three interchangeable solvers. Each returns a **ranked list of candidate bitstrings** (best energy first), not just one answer, plus how long it took.

#### `solve_qaoa`: the quantum one

**QAOA** (Quantum Approximate Optimization Algorithm) prepares a quantum state in which low-energy bitstrings are more likely to be measured. With N qubits, the state holds a probability for each of the 2^N bitstrings at once.

1. **Start** in an equal mix of all bitstrings (a Hadamard gate on every qubit).
2. Repeat `p` **layers** (`--p`, default 2):
   - **Cost layer** `exp(−i γ E)`: gives each bitstring a phase proportional to its energy. It does not change probabilities by itself.
   - **Mixer** `exp(−i β ΣX)`: lets bitstrings "leak" into neighbours that differ by a bit flip. Phases from the cost layer then interfere, so amplitude builds up on low-energy strings.
3. **Train the angles.** The 2p numbers γ₁..γₚ, β₁..βₚ are tuned by a classical optimizer (COBYLA from scipy) to make the measured energies as low as possible. Training starts from a "linear ramp" (γ growing, β shrinking), which mimics a slow anneal and is a reliable starting point. The search is capped at `--maxiter` steps (default 60). Each step is one full circuit simulation.
4. **Sample.** Measure the trained circuit `--shots` times (default 4000) and collect the distinct bitstrings that appear.

**CVaR in simple words.** Instead of training to minimize the *average* energy of all shots, we minimize the average of the *best `alpha` fraction* (default `alpha = 0.25`, the best quarter). We only ever keep the best few samples anyway, so we don't care whether the bad shots are bad. We care that the good tail is very good. `alpha = 1` gives back the plain average.

The energies are shifted and rescaled (`Ehat = (E − mean) / std`) before training so that sensible angles are around 0 to 1 whatever the dollar scale.

Where the pieces live:

- `qaoa_state(Ehat, gammas, betas, N)` is a fast **numpy statevector simulation** of the circuit, used during training. Because the energy table is known for all 2^N strings, the cost layer is just multiplying by phases. The mixer applies an X-rotation to every qubit, 5 qubits at a time as one small 32×32 matrix for speed.
- `qaoa_circuit(...)` builds the **same** circuit in Qiskit. This is what would run on real hardware. Each QUBO term becomes a gate, using `x_k = (1 − Z_k)/2`:

  | QUBO term | Gate(s) |
  |---|---|
  | start | `H` on every qubit |
  | linear `w · x_k` | `RZ(−γ w / scale)` on qubit k |
  | pair `w · x_k x_l` | `RZ(−γ w / (2·scale))` on k and on l, plus `RZZ(γ w / (2·scale))` on (k, l) |
  | mixer | `RX(2β)` on every qubit |

  (Constant terms only add a global phase, which cannot be measured, so they are dropped.) In the code, the RZ angles from all terms touching a qubit are added together into one RZ gate per qubit per layer.
- After training, the script samples the Qiskit circuit on **Qiskit Aer** (a simulator) if Qiskit is installed, otherwise it samples from the numpy statevector. `--sampler` forces one or the other. `--selftest` checks that both give identical probabilities.

The log line reports how often the QUBO's true best bitstring was measured, next to the chance of hitting it by random guessing (1 / 2^N). That ratio shows QAOA is doing real work, not just luck.

QAOA simulation is limited to 24 qubits here, because the statevector has 2^N entries.

#### `solve_anneal`: classical stand-in for larger sizes

**Simulated annealing**: start from random bits and flip bits one at a time. Always accept a flip that lowers energy. Accept one that raises it with a probability that shrinks as a "temperature" cools. It runs 20 restarts × 1000 sweeps, all restarts moving together as numpy arrays. It works for any number of bits and plays the role a quantum annealer could play. It is chosen automatically when the QUBO has more than `--max-qubits` bits (for example with `--copies`).

#### `solve_exact`: brute force, for checking

Scores all 2^N bitstrings and returns the best 200. Use it to see whether QAOA's samples are close to the QUBO's true best.

### Step 5: make it legal (`repair`, `dispatch`, `full_solution`)

A QUBO sample is just block-level on/off bits. It can break rules: maybe a block has too little capacity in its peak hour, or a plant starts and stops too quickly. `repair(model, schedule)` fixes it with simple, local rules, repeating until nothing changes:

| Problem | Fix |
|---|---|
| Too little capacity in an hour (on-capacity < demand + reserve) | Switch on the cheapest plant that is off (cheapest by average cost per MW at full output). |
| Too much minimum output in an hour (sum of on-plants' `pmin` > demand) | Switch off the most expensive on plant, as long as capacity still covers demand + reserve. |
| A plant started but would stop before its `min_up_h` | Keep it on for its full minimum up time. If that would push the hour's total minimum output above demand, drop that short run instead. |
| A plant stops and restarts before its `min_down_h` | Keep it on through the gap. If that would push total minimum output above demand, keep it off for its full minimum rest instead. |

The "or instead" choice matters. Without it, the hourly fix and the up/down fix can undo each other round after round, for example at night when demand is low.

After each round it checks the result with `Milp.violations`. If the schedule is legal it is returned. If repair gets stuck it returns `None` and the candidate is skipped.

`dispatch(plants, on, demand)` sets each on plant's output for one hour: everyone starts at `pmin`, then the rest of demand is filled cheapest-first ("merit order"). For a fixed on/off pattern with these rules, this is the cheapest possible output split.

`full_solution(model, schedule)` turns a 24 × plants on/off table into the full MILP vector `x`: `u` from the table, `v` wherever a plant switches on, `p` from `dispatch`. This vector is the warm start.

`main` repairs the top `--candidates` samples (default 50), scores each with its **true** cost (`true_cost`, the real MILP cost, not the QUBO estimate) and keeps the cheapest. For small fleets it prints the best raw QUBO sample and the repaired warm start side by side (`#` = on, `.` = off).

### Step 6: HiGHS cold vs warm (`run_highs`)

`run_highs(model, start)` solves the exact MILP with HiGHS (1 thread, a time limit, a fixed random seed):

- **cold**: `start=None`. HiGHS finds its own first answer.
- **warm**: `start=x`. Before searching, HiGHS is given the quantum-repaired schedule as its first incumbent (`setSolution`).

A callback records the time and cost each time HiGHS finds a better answer, giving the time to first incumbent and the number of improvements. At the end it reads status, objective, nodes, final gap and primal-dual integral from HiGHS.

Each mode runs `--repeats` times with different seeds (solver timing is noisy). The table shows the **median** of each metric and the best cost found.

### `main` and `selftest`

`main` parses the options and runs steps 0 to 6 in order. `--selftest` checks the pieces against each other instead:

1. The HiGHS optimum passes our own rule checker, and merit-order dispatch reproduces its cost.
2. `repair` leaves an already legal schedule unchanged, and tries to fix an "everything off" schedule.
3. The QUBO energy formula matches the brute-force table, and the numpy QAOA simulation matches the Qiskit circuit exactly.
4. HiGHS accepts a warm start and reaches the same optimum.

---

## 4. How to run it

Use the qBraid-SDK environment's Python (the same one as the **qBraid-SDK (v0.12.2)** notebook kernel). HiGHS's Python package must be installed once:

```bash
PY=/home/jovyan/.qbraid/environments/qbraid_r7ts/pyenv/bin/python
$PY -m pip install highspy          # once
cd /home/jovyan/tn-quantum-hackathon/3-tva-plant-scheduling

$PY quantum_warm_start_milp.py --selftest                 # check everything first
$PY quantum_warm_start_milp.py                            # 5 plants, QAOA, 4 blocks = 20 qubits
$PY quantum_warm_start_milp.py --blocks 3 --p 3           # 15 qubits, deeper circuit
$PY quantum_warm_start_milp.py --plants data/plants10.csv --demand data/demand10.csv --blocks 2
$PY quantum_warm_start_milp.py --copies 6 --solver anneal # 30 plants: hard enough for HiGHS to need a tree
$PY quantum_warm_start_milp.py --copies 6 --solver anneal --out results_c6.json
```

From a notebook with that kernel: `!python -m pip install highspy`, then `%run quantum_warm_start_milp.py --selftest` (and so on).

Qiskit and qiskit-aer are optional. Without them, QAOA samples from the numpy simulation, and the circuit check in `--selftest` is skipped.

### Options

| Option | Default | What it does |
|---|---|---|
| `--plants` | `data/plants.csv` | Plant data file |
| `--demand` | `data/demand.csv` | Hourly demand and reserve file |
| `--copies` | 1 | Make the fleet N times bigger (costs jittered ±8%, demand × N). Makes the MILP harder |
| `--blocks` | `max-qubits // plants` (4 for anneal) | Number of time blocks K. Qubits = plants × K |
| `--solver` | auto | `qaoa`, `anneal` or `exact`. Auto picks `qaoa` if it fits in `--max-qubits`, else `anneal` |
| `--max-qubits` | 20 | Largest QUBO handed to QAOA automatically (QAOA itself refuses more than 24) |
| `--p` | 2 | QAOA layers |
| `--maxiter` | 60 | QAOA optimizer steps for training the angles |
| `--shots` | 4000 | QAOA measurements |
| `--alpha` | 0.25 | CVaR fraction for training (1 = plain average energy) |
| `--sampler` | auto | `qiskit` (Aer circuit), `numpy` (statevector) or `auto` (Qiskit if installed) |
| `--penalty` | 1.0 | Weight of the capacity penalty in the QUBO |
| `--candidates` | 50 | How many of the best samples to repair and score |
| `--time-limit` | 60 | HiGHS time limit per run, in seconds |
| `--repeats` | 3 | HiGHS runs per mode, with different seeds (median reported) |
| `--seed` | 0 | Random seed (fleet jitter, QAOA sampling, annealing, HiGHS) |
| `--out` | none | Save a JSON summary to this path |
| `--selftest` | off | Run the consistency checks instead of the experiment |

### Reading the output

The run prints three steps:

- **Step 1. QUBO**: the blocks chosen (for example `0-5`, `6-10`, ...), the number of bits, the solver. For QAOA it also prints the trained CVaR value next to the value for uniform random guessing (lower is better), and how often the QUBO's best bitstring was sampled compared with random chance.
- **Step 2. Repair**: how many candidates could be made legal, the warm start's real cost, and (for small fleets) the raw and repaired schedules.
- **Step 3. HiGHS**: the comparison table:

```
          time (s)  B&B nodes  final gap  P-D integral         cost status
  cold       ...        ...       ...%        ...          $...   Optimal
  warm       ...        ...       ...%        ...          $...   Optimal
```

| Column | How to read it |
|---|---|
| `time (s)` | Median wall-clock time for HiGHS. Lower is better |
| `B&B nodes` | Median branch-and-bound nodes. Fewer means the start helped prune |
| `final gap` | 0% means proven optimal. Above 0% means it hit the time limit |
| `P-D integral` | Median primal-dual integral. Lower means good answers came earlier |
| `cost` | Best final cost. Cold and warm should match when both reach `Optimal` |
| `status` | HiGHS status, such as `Optimal` or `Time limit reached` |

Below the table: how far the warm start was from the best cost found (in %), the cold → warm speed ratio, the node counts, and the quantum and repair times.

---

## 5. Honest caveats

- **The quantum step is simulated on a normal computer.** Its wall-clock time is simulation time, not QPU time, and the two cannot be compared. Training also scores all 2^N bitstrings classically, which a real QPU run would not do. Report HiGHS's time separately from the quantum step.
- **On the 5-plant case HiGHS already takes milliseconds.** There is almost no tree to prune, so a "speedup" there is noise. Any claim that the warm start helps should use the larger `--copies` fleets and look at **nodes**, **time to first incumbent** and **primal-dual integral** over several seeds (`--repeats`), not just one timing.
- **For larger fleets the "quantum" step is simulated annealing,** because the QUBO is too big to simulate as QAOA. Say clearly which solver produced each result.
- **The QUBO is an approximation.** Blocks force a plant to stay on or off for a whole block, the running cost assumes a typical output level, and min up/down rules are left out. That is fine. The QUBO only has to point in the right direction: repair makes the schedule legal, and HiGHS guarantees that the final answer is exact and optimal, whatever the start. A bad start can waste a little time but cannot make the final answer wrong.
- **A warm start mainly helps the "find a good answer" half.** HiGHS still has to prove no better answer exists, and that work only gets smaller if pruning improves.
- **Running on real hardware via qBraid** would mean sending the circuit from `qaoa_circuit` (with trained angles) to a device such as `ionq:ionq:qpu:forte-1` through `QbraidProvider`, and feeding its measured bitstrings into the same repair → HiGHS steps. Two cautions: (1) a 20-qubit, p = 2 circuit with all-to-all pair terms has far more two-qubit gates than IonQ's advice of a few dozen, so use fewer blocks and `p = 1`; (2) hardware runs cost credits and queue time. Tune on Aer and IonQ's free noisy simulator first, estimate the cost, and confirm with the team before any paid run. Hardware shot counts should be far below the 4000 used on the simulator.

---

## 6. Results

Measured on this qBraid instance (shared machine, so timings are noisy; HiGHS medians over 3 runs, 2 for 40 plants, 1 thread).

| Case | Command flags | Qubits / solver | Warm-start gap to optimum | HiGHS time cold → warm (s) | Nodes cold → warm | P-D integral cold → warm |
|---|---|---|---|---|---|---|
| 5 plants, K=4 | *(defaults)* | 20 / QAOA p=2 | +1.12% | 0.202 → 0.195 | 1 → 1 | 0.097 → 0.086 |
| 10 plants, K=2 | `--plants data/plants10.csv --demand data/demand10.csv --blocks 2` | 20 / QAOA p=2 | +1.62% | 0.198 → 0.187 | 1 → 1 | 0.121 → 0.098 |
| 20 plants, K=4 | `--copies 4 --solver anneal` | 80 / annealing | +1.78% | 0.607 → 0.505 | 1 → 1 | 0.400 → 0.260 |
| 40 plants, K=4 | `--copies 8 --solver anneal --repeats 2` | 160 / annealing | +2.19% | 3.081 → 3.021 | 1 → 1 | 1.468 → 1.347 |

Quantum-step quality (QAOA, 20 qubits): the trained CVaR was −2.40 against −1.24 for random guessing (5 plants), and the QUBO's exact best bitstring turned up in about 0.1% of shots (10 plants) against 0.0001% by chance. 49 to 50 of the top 50 samples could be repaired into legal schedules.

**What this shows.**

- The pipeline works end to end. Quantum samples become legal schedules within 1–2% of the optimum, HiGHS accepts them (its log reports "MIP start solution is feasible"), and the final answer is always the true optimum.
- On this data the warm start **does not speed up HiGHS much**. Every instance, even 40 plants, is solved at the root node (1 node), so there is no search tree to prune.
- What the start does improve is the **primal-dual integral**: 8–35% lower in every case, because a good answer exists from second zero. HiGHS time improved about 1.2× at 20 plants and was within noise elsewhere.
- To show a real speed-up you need a MILP that HiGHS can't close at the root, such as one with ramp limits, a longer horizon, or a larger or more symmetric fleet. That is the honest next step for a speed claim.
