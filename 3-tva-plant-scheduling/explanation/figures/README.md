# explanation/figures

Charts for [`../README.md`](../README.md), drawn by `../make_figures.py` from `../results/*.json`. Re-make them with `python explanation/make_figures.py`.

| File | Shows |
|---|---|
| `01_pure_qaoa_vs_milp.png` | Pure hour-by-hour QAOA: cost gap and rules broken as the fleet grows (3–10 plants) |
| `02_rule_checking.png` | The same with rule checking: every day valid, gap about 2–7.5% |
| `03_hour_grouping.png` | Grouping hours into blocks, and the full-day QUBO, vs hour by hour |
| `04_qubit_growth.png` | Qubits needed by each formulation as plants are added |
| `05_warm_start_timeline.png` | Cold vs warm HiGHS: best answer found over time |
| `06_warm_start_metrics.png` | Cold vs warm HiGHS: time, primal-dual integral, time to a near-optimal day |
| `07_summary.png` | The whole path on 10 plants, from pure QAOA (+48%) to the warm-started MILP (0%) |
| `08_why_pure_qaoa_breaks_rules.png` | Why pure QAOA breaks rules: QUBO flaw vs QAOA sampling (`../diagnose_pure_qaoa.py`) |
