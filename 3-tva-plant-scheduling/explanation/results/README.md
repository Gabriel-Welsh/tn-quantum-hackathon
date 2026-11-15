# explanation/results

Raw numbers behind `../figures/` and `../README.md`. `.json` = data read by `../make_figures.py`; `.log` = console output of the run.

| File | Written by | Contents |
|---|---|---|
| `pure.json`, `pure.log` | `run_experiments.py pure` | Pure QAOA and rule-checked QAOA, hour by hour, 3–10 plants × 3 seeds |
| `blocks.json`, `blocks.log` | `run_experiments.py blocks` | Block QUBOs (K = 2, 3, 4, 6) and the full-day QUBO, before and after polish |
| `qubits.json` | `run_experiments.py qubits` | Qubit counts for each formulation and fleet size (no solving) |
| `warm.json` | `run_experiments.py warm` | Cold vs warm HiGHS for 5–80 plants, with incumbent timelines |
| `diagnose.json`, `diagnose.log` | `diagnose_pure_qaoa.py` | The four-way breakdown of why pure QAOA breaks rules |

Older runs, kept for comparison:

| Folder | What it is |
|---|---|
| `no_locks/` | `pure.json`, `pure.log`: the first, incorrect "pure QAOA" run. Figure 01 draws it faintly as "before" |
| `before_slack_fix/` | `diagnose`, `pure`, `qubits` and `variants` (`.json` + `.log`): runs from before the slack-qubit fix, which added slack bits until the penalty could reach zero. That made the QUBO bigger and weakened its push against over-commitment. The current code always uses the starter's 3 slack bits |
