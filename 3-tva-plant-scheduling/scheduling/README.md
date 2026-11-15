# scheduling

The Python modules that build, solve and check schedules. Notebooks and scripts import them by adding this folder to `sys.path`. Each script finds `../data/` on its own, so run them from the project folder: `python scheduling/<script>.py --help`.

| File | What it is |
|---|---|
| `quantum_warm_start_milp.py` | **Our solution.** Exact MILP (`Milp`), block QUBO (`split_into_blocks`, `Qubo`), QAOA / annealing / brute-force solvers, `repair` into a legal day, and HiGHS cold vs warm (`run_highs`). Run `--selftest` to check the pieces against each other |
| `check.py` | Official checker from the organizers: `check_schedule` (cost + broken rules), `check_hour`, `locks`, and the scipy MILP baseline `solve_milp` |
| `run_qaoa_schedule.py` | Hour-by-hour QAOA scheduler with min up/down locks, validity filter, look-ahead credit and local search (the "rule checking" attempt) |
| `block_qubo.py` | One QUBO for the whole day by grouping hours into K blocks, with startups and min up/down inside the QUBO (the "hour grouping" attempt) |
| `run_all_24h_qaoa_schedule.py` | One QUBO for all 24 hours at once (279–701 qubits, so annealed rather than run with QAOA) |

`PRESENTATION_SCRIPT-checkpoint.md` and `TVA_quantum_warm_start-checkpoint.ipynb` are stray Jupyter autosave copies and can be deleted. The real files are in the project folder.
