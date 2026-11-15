# TN Quantum Hackathon

This repository has our team's work for the TN Quantum Hackathon. Each top-level folder is one hackathon track or award.

| Folder | What's in it |
|---|---|
| [`3-tva-plant-scheduling/`](./3-tva-plant-scheduling/) | **Our main submission (Track 3, TVA plant scheduling).** QAOA warm start for the TVA unit-commitment problem: a 20-qubit QUBO gives a near-optimal day, classical repair makes it legal, and a warm-started HiGHS MILP proves the optimum. |
| [`4-qbraid-award/`](./4-qbraid-award/) | The optional qBraid "most creative use of qBraid" award: rules and entry instructions, the 3-slide template, and a helper script that turns measurement results into a chart. |

## `3-tva-plant-scheduling/`

Start with [`TVA_quantum_warm_start.ipynb`](./3-tva-plant-scheduling/TVA_quantum_warm_start.ipynb). It runs the whole pipeline and has all outputs saved, so you can read it without running anything. The folder's [`README.md`](./3-tva-plant-scheduling/README.md) has the headline results and caveats.

| Path | Contents |
|---|---|
| `README.md` | Overview of our approach, results table and caveats |
| `PROBLEM_README.md` | The original challenge description |
| `PRESENTATION_SCRIPT.md` | Talk track for the pitch |
| `TVA_quantum_warm_start.ipynb` | The submission notebook |
| `background/` | TVA's problem statement in its own words, plus the reading TVA shared on unit commitment and economic dispatch |
| `data/` | Plant and demand CSVs (5- and 10-plant versions) derived from the NREL RTS-GMLC test system, and `make_data.py` that builds them |
| `docs/` | Written explanations of our solution, including `QUANTUM_WARM_START.md` |
| `scheduling/` | Core Python modules: block QUBO, the official rule checker (`check.py`), the warm-started MILP, and QAOA run scripts |
| `hybrid_uc/` | A separate hybrid we tried (Lagrangian incentives + hour-by-hour QAOA + repair), as a Python package with its own results and analysis |
| `notebooks/` | Supporting notebooks: starter, QAOA primer, QAOA improvements, hybrid interface, warm start vs. MILP |
| `experiments/` | Side experiments on the hour-by-hour QAOA loop (commitment search, gas incentive), each with a `*_results.md` table |
| `explanation/` | How we got from pure QAOA to a quantum warm start: scripts, figures and results behind that story |
| `input_app/` | Browser app for editing plants and demand and running the algorithms, plus a hardware-report template |
| `outputs/` | Saved results: warm-start runs (JSON and `warm_start_results/`) and the hybrid schedule CSV and chart |

Most subfolders have their own `README.md` with more detail.

## `4-qbraid-award/`

| File | Contents |
|---|---|
| `README.md` | What the award is, how to enter, deadline and judging criteria |
| `qbraid-award-template.pptx` | The 3-slide template for the entry |
| `make_visual.py` | `make_visual(...)`: turns measurement results into an animated, shareable chart in one call from a notebook |
