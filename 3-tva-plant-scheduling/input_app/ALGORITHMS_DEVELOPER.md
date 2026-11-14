# Scheduling algorithms: developer guide

This guide describes the algorithms exposed by the Plant schedule page, the shared scheduling script, and the three Jupyter notebooks. Source paths below are relative to this `input_app/` directory.

## Inputs, outputs, and what the page shows

`server.py` reads **saved** `plants.csv` and `demand.csv`. `algorithms.available()` discovers each non-underscore Python file in `algorithms/` with a `solve(plants, demand, reserve)` function. Each solver returns an hours × plants matrix of 0/1 commitments in input order. `build_schedule()` checks its shape and values, then calls `../check.py:check_schedule()` to calculate cost and violations. The browser calls `/api/schedule?algorithm=<module_name>` on page load, algorithm change, or **Generate schedule**.

An on bit means a plant is available, not that it produces its maximum MW. The chart stacks committed `pmax_mw` and plots demand plus reserve. The checker computes actual hourly output separately by starting each committed plant at `pmin_mw`, then allocating the remaining demand in marginal-cost order. Its day cost is startup + no-load + energy. It checks demand, reserve, and minimum up/down times by default; ramp limits require `ramps=True` and are **not** checked by the page. A valid page result is therefore valid for the modeled default rules, not a grid power-flow or ramp-feasibility certificate.

## Algorithms exposed by the app

| Selector | Source | How it chooses commitments | What it optimizes or omits |
| --- | --- | --- | --- |
| Classical baseline | `algorithms/classical_baseline.py` → `../check.py:solve_milp()` | One SciPy/HiGHS mixed-integer model for the entire saved horizon | Minimizes startup + no-load + dispatch energy under modeled demand, reserve, output, and minimum up/down constraints. Optional ramps are off in the app. |
| Cheapest-first rule | `algorithms/cheapest_first.py` | Sorts plants once by `(marginal_cost_per_mwh + no_load_cost_per_h) / pmax_mw`; each hour adds plants in that order until sum of `pmax_mw` covers demand + reserve | A simple capacity rule. It does not optimize the full cost or enforce minimum up/down times, minimum output, or ramps when selecting. The checker reports violations. |
| QAOA | `algorithms/qaoa.py` → `../run_qaoa_schedule.py:schedule_day()` | Builds and samples a one-hour QUBO for each hour, then classically selects and improves a valid commitment | Hybrid heuristic with future-plan look-ahead, classical feasibility checks, local search, and fallback enumeration. It does not solve one joint day-long QUBO. |
| Quantum warm-start MILP | `algorithms/quantum_warm_start.py` → `../quantum_warm_start_milp.py` | Simulated QAOA proposes on/off choices for up to two demand-shaped time blocks; repair creates a feasible full-day start for HiGHS | HiGHS optimizes the full-day MILP after receiving the start. The app caps the QUBO at 16 bits, uses 200 local shots, and does not measure a speedup or run a QPU. Requires `highspy`. |

The MILP uses binary on/off and startup variables plus continuous MW output per plant and hour. It enforces exact demand through dispatch, sufficient committed capacity for reserve, `pmin*u ≤ output ≤ pmax*u`, startup logic, and minimum up/down windows. `solve_milp(..., ramps=True)` adds ramp constraints; the app does not pass that flag. “Exact baseline” means the model is solved as a mixed-integer optimization problem for these rules. It is not a quantum algorithm.

The cheapest-first ranking above follows the **executable cell** in `../starter.ipynb`. That notebook's prose describes a different cost expression, so reproducing the code requires the expression shown here. The rule may even commit so many plants that their combined minimum output exceeds demand.

## How the app's QAOA generator works

`algorithms/qaoa.py` calls `schedule_day(plants, demand, reserve, p=1, shots=200, sampler="qaoa", seed=7, use_credit=True, lookahead=3, use_local_search=True)`. Remaining defaults include 50 MW capacity blocks, three slack bits, penalty factor 2, 60 COBYLA iterations per hour, and the `plan` credit rule. The wrapper rejects more than 13 plants (16 total qubits with the default slack bits) and requires Qiskit. It passes no device runner, so all app samples are drawn **locally** from Qiskit's exact statevector probabilities; no qBraid job or QPU is used.

For each hour, the shared script:

1. Computes a future plan by enumerating all plant on/off sets for each hour and choosing the cheapest valid set **as if startup were free**. If a plant appears in that plan within the next three hours, a credit reduces the cost of keeping it on or starting it now. The credit is `max(0, startup_cost − (k−1) × hold_cost)` for the first planned use `k` hours away. This is a heuristic for later startup costs, not full multi-hour optimization.
2. Uses the already chosen history to lock plants on or off for minimum up/down times. It also keeps a currently on plant running when switching it off would make later capacity impossible during its minimum down period.
3. Builds a one-hour QUBO with a binary variable for each plant and three slack bits. Its approximate energy is plant on-cost plus `A × (committed_capacity_blocks − slack_blocks − required_blocks)^2`, with lock penalties and the future credit. `A = 2 × max(approximate plant cost)` by default. The approximate on-cost includes startup, no-load, and a premium for minimum output above the cheapest marginal cost. It is **not** the checker's exact dispatch cost. The final choice is checked against unrounded MW values, so the block approximation is not treated as proof of feasibility.
4. Maps the QUBO to Ising terms and creates a one-layer QAOA circuit: Hadamards, `RZ`/`RZZ` cost gates, then `RX` mixer gates. COBYLA tunes the angles against the **exact statevector expected QUBO energy**, reusing the previous hour's angles as a warm start. This step scores all `2^(plants + slack bits)` bitstrings classically on the local machine.
5. Draws 200 local samples from the tuned probability distribution and drops the slack bits. It ranks the distinct plant sets with classical `hour_ok`, a future shortfall check, and exact `hour_cost − credit`; valid choices rank before invalid ones. A local search then tries one-plant flips and on/off swaps. If sampling found no valid choice, repair runs even if ordinary local search was disabled; for at most 16 plants it can enumerate all plant sets. It carries the chosen on/off state to the next hour.

The sampled quantum distribution influences which candidates arrive first, but classical validation, exact hourly costing, future-plan enumeration, local search, and possible full enumeration can determine the final answer. Report those contributions when comparing QAOA with random sampling or the MILP. The future-plan credit changes the selection score as well as the QUBO; the reported day cost remains the uncredited physical cost from `check_schedule()`.

The **Quantum warm-start MILP** option uses a different QUBO: it groups the saved day into one or two time blocks, with one bit per plant per block. The wrapper tunes one-layer QAOA on a local NumPy statevector, samples 200 candidates, repairs up to 30, and passes the cheapest feasible candidate as a full MILP start to HiGHS. The final schedule is HiGHS's result. The app does not run a cold-versus-warm timing trial; use `../quantum_warm_start_milp.py` and `../QUANTUM_WARM_START.md` for that experiment. The saved 10-plant fleet uses one block under the app's 16-bit limit, which favors page responsiveness over the script's default research settings.

## Local simulation versus a real device

| Run | Where angles are tuned | Where final shots come from | Cost and output |
| --- | --- | --- | --- |
| App's QAOA selector | Local exact Qiskit statevector | Local random draw from exact probabilities | No remote job or QPU credits; page returns a commitment, cost, and default-rule violations. |
| `../run_qaoa_schedule.py` without `--device` | Local exact statevector | Local random draw | Same hybrid algorithm, with command line options, timing and diagnostic rows. Defaults to `../data/*.csv`, unlike the app's saved `input_app/*.csv`. |
| Script with `--device ionq:ionq:sim:simulator` (or bare `--device`) | Local exact statevector | Remote IonQ simulator, default `forte-1` noise model if offered | qBraid job IDs and measured counts. It is a **simulator**, even though it uses the Jobs service. |
| Script with a QPU device ID | Local exact statevector | Physical device via qBraid | Device noise, finite shots and queue time affect counts. It can spend credits. The script estimates pricing, requests confirmation for a nonzero estimate, and saves job IDs in `qaoa_jobs.json` to resume. |

The script's `--hours` selects which hours use the remote device; other hours still sample locally. A device run does **not** move the COBYLA loop or exact statevector objective onto hardware. Because each hour depends on the previous choice, a changed device outcome can alter later hours, even if only one hour uses the QPU. Its report compares the device's valid-shot share with the ideal local distribution and states whether the **final, possibly locally improved** choice is best. A job ID and device ID are the evidence of an actual remote run; a schedule shown in the app is not evidence of one. Check device availability and current price before a paid run.

## How the Jupyter notebooks differ

| Notebook | Purpose and algorithms | Main difference from the app/shared script |
| --- | --- | --- |
| `../qaoa_primer.ipynb` | Teaching QAOA on Max-Cut, a separate graph-partition problem; compares against brute force and random cuts. Optional qBraid GPU **simulator** cell. | It does not make plant schedules. Its optional GPU job is simulation, not QPU hardware. |
| `../starter.ipynb` | Introductory plant-scheduling workflow: hand schedule, SciPy MILP, cheapest-first rule, one-hour QUBO, whole-day QAOA versus random, and a single-hour hardware comparison cell. | Its day loop has no look-ahead credit, future-capacity lock, or local search. When no valid sample appears, it can relax locks or use a sampled fallback, so a day may violate rules. The hardware cell defaults to IonQ's noisy simulator; QPU lines are commented out and require an explicit edit. |
| `../qaoa_improvements.ipynb` | Experiments with exact per-hour enumeration, shot sweeps, penalty strength, necessity and future-plan credits, credit in the final pick, and INTERP initialization for deeper QAOA. | Its `schedule_day_v2` is experimental and still uses the starter's fallback rather than the shared script's future-feasibility checks, local search, and repair. Its setup has `FIX_TODO2=True` to use the intended plant-cost formula. It studies the future-plan credit with an optional unlimited window; the app caps it at three hours. |

The shared script adopts the improvement notebook's future-plan credit by default, applies it in both the QUBO and candidate score, and adds stricter future feasibility and local repair. It retains a `--credit-rule necessity` option and `--no-credit` comparison, but does not expose the improvement notebook's INTERP initialization; it warm-starts angles hour to hour. The script's `--starter-costs` option exists to reproduce an older starter cost expression. The current executable starter cell in this checkout already shows the corrected `pmin × (marginal − cheapest marginal)` expression, so compare actual cell contents and settings before expecting numerical equality. Notebook results also use their own loaded inputs and settings; the app uses saved editor CSVs.

## Adding or comparing algorithms

Add `algorithms/<id>.py` with `NAME`, optional `DESCRIPTION`, and `solve(plants, demand, reserve)`. Use an underscore-prefixed helper module when it should stay out of the selector. Refresh the page for new files; restart the server after editing an imported module. Keep plant order unchanged, and return one 0/1 row per saved hour. For fair comparisons, use the same plant and demand CSVs, checker options, and random seeds; report validity, total cost, runtime, number of shots, and whether samples were local, remote simulation, or physical QPU measurements. Do not call a lower cost an improvement if the checker found rule violations.
