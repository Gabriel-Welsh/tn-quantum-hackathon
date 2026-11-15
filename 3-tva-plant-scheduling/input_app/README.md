# Power plant and demand editor

## Open in qBraid Lab

1. In a Lab terminal, change to this `input_app` directory and start the server:

   ```bash
   python server.py
   ```

   The **Quantum warm-start MILP** option also needs `highspy`. On this Lab
   instance it is installed in the qBraid-SDK environment, so start the app
   with that environment's Python to use this option. Find its path with
   `qbraid envs list`, then run `<env-path>/pyenv/bin/python server.py`.
   Other app algorithms continue to work without `highspy`.

2. In another Lab terminal, open it in Agent Canvas:

   ```bash
   qbraid-canvas --port 8000 --title "Plant Scheduling Editor"
   ```

   Alternatively, replace `/lab` in your Lab URL with `/proxy/8000/`, keeping
   any URL prefix before `/lab`. Keep the server terminal running while you use
   the app; press Ctrl+C there to stop it.

In Agent Canvas, use the tabs at the top to switch views.

The app has four pages:

- **Power plants**: choose **Use 10 default plants** to edit the starter fleet, or drop a CSV onto the upload area (or click **Add power plant .csv**) to import your own fleet. Use **Remove plant** on any card to take it out of the editor; at least one plant must remain. Click **Save plants.csv** to write the edited list to `input_app/plants.csv`. Importing or removing alone does not save. The CSV must have the same columns as `input_app/plants.csv`.
- **Demand and reserve**: edit demand for each hour. Use the single reserve
  percentage slider above the chart to set reserve for every hour at once
  (rounded to whole MW). The solid line is demand; the dotted line is demand
  **plus** reserve. Click **Save demand.csv** to write `input_app/demand.csv`.
- **Plant schedule**: see which plants should be on for each saved hour. The
  classical baseline runs when the page loads; choosing another algorithm runs
  it immediately. Click **Generate schedule** to recalculate after saving changes
  to either CSV. The page
  shows a stacked hourly capacity chart, with one color per online plant and
  a line for demand plus reserve. The bars show available capacity, not actual
  generation. The page also shows rule violations if an algorithm returns an
  invalid schedule. Its QAOA option uses a local statevector simulator, **not an
  actual quantum computer**. The Quantum computing outlook is developer-maintained
  text in `index.html`; visitors cannot edit it.
- **Quantum hardware report**: charts the existing local HiGHS solve-time and
  primal-dual-integral medians from the warm-start experiments.

## Add a scheduling algorithm

For implementation details, QAOA's local and device execution paths, and
notebook differences, see [Scheduling algorithms: developer guide](ALGORITHMS_DEVELOPER.md).

Add a Python file to `input_app/algorithms/`. It appears in the algorithm
selector after a page refresh. Each file exports `NAME`, optionally
`DESCRIPTION`, and `solve(plants, demand, reserve)`. The arguments are the
saved plants as a list of dictionaries and demand/reserve as NumPy arrays.
Return a matrix with one row per hour and one column per plant, in the same
order as the inputs; use `1` for on and `0` for off.

For example, `input_app/algorithms/quantum_trial.py` can call a function in
another Python file:

```python
from algorithms._quantum_solver import schedule_day

NAME = "Quantum trial"
DESCRIPTION = "Experimental commitment schedule"

def solve(plants, demand, reserve):
    return schedule_day(plants, demand, reserve)
```

Put helper code in `algorithms/_quantum_solver.py`: files starting with `_`
are not listed as algorithms. The server discovers new algorithm files
automatically; restart it after editing an already loaded module. The app
checks the returned shape and on/off values, then uses `check.py` to report
demand, reserve, and minimum on/off time violations, matching the notebooks'
default checker. Ramp checking is a separate notebook stretch goal. The included
`classical_baseline.py` calls the project's SciPy mixed-integer solver, so the
server environment needs NumPy and SciPy for that algorithm. The included
`cheapest_first.py` follows the notebook's executable code cell: rank plants
by `(marginal_cost_per_mwh + no_load_cost_per_h) / pmax_mw`, then add plants
until capacity covers demand plus reserve. The cell's formula differs from its
markdown description; the app uses the code formula for reproducibility. This
comparison rule can break minimum on/off times, and the page reports those
violations.

`qaoa.py` calls the reusable notebook-derived `run_qaoa_schedule.py` with its
local statevector simulator, one QAOA layer, 200 shots per hour, look-ahead
credit, and local search. **QAOA credit: Gabe.** It requires Qiskit in the
server's Python environment and does not submit hardware jobs or spend QPU
credits. The web app limits local QAOA to 13 plants to keep statevector runs
responsive.

`quantum_warm_start.py` wraps the project's `quantum_warm_start_milp.py`: a
small, locally simulated QAOA proposes block-level on/off decisions, classical
repair turns the best candidate into a feasible full-day MILP starting
solution, and HiGHS solves the MILP. It uses the saved editor CSVs and does not
submit QPU jobs. The webapp caps the local QUBO at 16 bits for responsiveness;
this selector reports the final schedule, not a cold-versus-warm speedup test.
See `../docs/QUANTUM_WARM_START.md` for the benchmark script and its limits.

The source examples in `data/` stay unchanged. To use the edited files in a
notebook or Python script run from this project folder:

```python
from check import load_plants, load_demand
plants = load_plants("input_app/plants.csv")
demand, reserve = load_demand("input_app/demand.csv")
```

Comments in `plants.js`, `app.js`, and `server.py` mark where to add more
input fields and validation. The server listens only on this computer. Stop it
with Ctrl+C.

## For future maintainers

- `index.html` is the maintained page. `plants.html` redirects old bookmarks to its Power plants tab. The scripts in `index.html` are modules so page-local variables do not collide.
- `navigation.js` switches the four sections by URL fragment. `app.js` builds the demand table and SVG chart. `plants.js` builds plant cards, parses uploaded CSVs, and contains the 10 default plants. `schedule.js` renders algorithm results. `hardware_report.js` loads the SVGs generated by `hardware_report.R` when available.
- `server.py` serves known files and the plant, demand, algorithm, and schedule APIs. Its POST handlers validate all rows before replacing a CSV. The CSV files are data: do not add comments or change headers casually.
- To change plant fields, update `plants.csv`, the `FIELDS` list and import validation in `plants.js`, and `PLANT_NUMBERS` / `save_plants` in `server.py`. Update the 10-plant snapshot in `plants.js` if `data/plants10.csv` changes.
- To change hourly demand fields, update `demand.csv`, the table and `getRows()` in `app.js`, and `save_demand()` in `server.py`. The reserve percentage is calculated in `reserveFor()` and applied by the slider listener. Update the chart and legend if the new field should be plotted.
- To change a page section or its IDs, check selectors in the matching script and styles in `styles.css`. To add a served asset, add it to the GET file map in `server.py`.
