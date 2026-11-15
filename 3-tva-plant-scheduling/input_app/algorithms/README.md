# input_app/algorithms

Scheduling algorithms the web app (`../server.py`) offers in its **Plant schedule** page. The server discovers every `*.py` file here automatically. Files starting with `_` are helpers and are not listed. To add one, see [`../ALGORITHMS_DEVELOPER.md`](../ALGORITHMS_DEVELOPER.md).

| File | Algorithm |
|---|---|
| `classical_baseline.py` | The exact MILP from `scheduling/check.py` (loads first by default) |
| `cheapest_first.py` | Port of the starter notebook's cheapest-first rule |
| `qaoa.py` | Hour-by-hour QAOA schedule from our notebook, on a local statevector simulator (not a real QPU) |
| `quantum_warm_start.py` | Our solution: simulated QAOA samples → repair → warm-started HiGHS. Needs `highspy`. QUBO capped at 16 bits for responsiveness |
| `__init__.py` | Discovers and loads the algorithm files |
