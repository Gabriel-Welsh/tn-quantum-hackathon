# experiments

Side experiments built on the starter notebook's hour-by-hour QAOA loop. Each writes a `*_results.md` table. Run from the project folder, e.g. `python experiments/gas_incentive.py`.

| File | What it is |
|---|---|
| `_nb.py` | Helper: loads the functions defined in `../notebooks/starter.ipynb` (up to `schedule_day`) so the scripts can reuse them |
| `gas_incentive.py` | Adds classical GAS_CC incentives (amortized startup, an hourly bonus) to the hour-by-hour QAOA loop |
| `gas_incentive_results.md` | Its results: valid days and gap vs the MILP, QAOA vs random, by shots |
| `commit_search.py` | Plant-agnostic "commit + amortized" hybrid: classically search for which plant runs to commit, then QAOA hour by hour |
| `commit_search_results.md` | Its results across six demand curves |
