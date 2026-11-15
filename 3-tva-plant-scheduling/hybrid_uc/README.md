# hybrid_uc

A separate hybrid we tried: classical Lagrangian incentives + hour-by-hour QAOA + classical repair. A Python package; run from the project folder.

```bash
python -m hybrid_uc.run --help        # one fleet and one demand curve, end to end
python -m hybrid_uc.analyze           # the full benchmark behind RESULTS.md (~45 min)
```

| File | What it is |
|---|---|
| `ANALYSIS.md` | **Start here.** What the benchmark shows, in plain words |
| `RESULTS.md` | All benchmark tables (5 to 200 plants, several demand curves, QAOA vs random) |
| `results.json` | The same numbers as data |
| `run.py` | Command-line entry point: load or generate a fleet, schedule it, compare with the MILP |
| `analyze.py` | The benchmark that writes `RESULTS.md` |
| `fleet.py` | Fleet and demand input: CSV, interactive prompt, or synthetic N-plant fleet |
| `incentives.py` | Lagrangian relaxation: prices for energy and reserve, per-plant cost-to-go, a lower bound |
| `qaoa.py` | Hourly QUBO for N plants and a fast QAOA simulator |
| `pipeline.py` | Hour-by-hour scheduling with incentives and a pluggable sampler (QAOA, random, exact) |
| `repair.py` | Local-search repair and a certified bound on the remaining gap |
| `ui.py` | Notebook interface used by `../notebooks/hybrid_uc_interface.ipynb` |
| `__init__.py` | Package marker and overview |

Finding: it reaches +0.00–0.34% of the MILP, but the classical stages alone already reach +0.00% (see `ANALYSIS.md`). That's one reason we moved to the warm start.
