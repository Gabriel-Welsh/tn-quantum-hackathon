# Power plant and demand editor

From this project folder, run `python input_app/server.py`. In qBraid Lab,
open the Lab URL with `/lab` replaced by `/proxy/8000/` (keep any URL prefix
before `/lab`). You can also preview the running app in Agent Canvas with
`qbraid-canvas --port 8000 --title "Plant Scheduling Editor"`.

In Agent Canvas, use the tabs at the top to switch views.

The app has two pages:

- **Power plants**: choose **Use 10 default plants** to edit the starter fleet, or drop a CSV onto the upload area (or click **Add power plant .csv**) to import your own fleet. Review the rows, then click **Save plants.csv** to write `input_app/plants.csv`. Importing alone does not save. The CSV must have the same columns as `input_app/plants.csv`.
- **Demand and reserve**: edit demand for each hour. Use the single reserve
  percentage slider above the chart to set reserve for every hour at once
  (rounded to whole MW). The solid line is demand; the dotted line is demand
  **plus** reserve. Click **Save demand.csv** to write `input_app/demand.csv`.

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
- `navigation.js` switches the two sections by URL fragment. `app.js` builds the demand table and SVG chart. `plants.js` builds plant cards, parses uploaded CSVs, and contains the 10 default plants.
- `server.py` serves known files and the two JSON APIs. Its POST handlers validate all rows before replacing a CSV. The CSV files are data: do not add comments or change headers casually.
- To change plant fields, update `plants.csv`, the `FIELDS` list and import validation in `plants.js`, and `PLANT_NUMBERS` / `save_plants` in `server.py`. Update the 10-plant snapshot in `plants.js` if `data/plants10.csv` changes.
- To change hourly demand fields, update `demand.csv`, the table and `getRows()` in `app.js`, and `save_demand()` in `server.py`. The reserve percentage is calculated in `reserveFor()` and applied by the slider listener. Update the chart and legend if the new field should be plotted.
- To change a page section or its IDs, check selectors in the matching script and styles in `styles.css`. To add a served asset, add it to the GET file map in `server.py`.
