# Power plant and demand editor

From this project folder, run `python input_app/server.py`. In qBraid Lab,
open the Lab URL with `/lab` replaced by `/proxy/8000/` (keep any URL prefix
before `/lab`). You can also preview the running app in Agent Canvas with
`qbraid-canvas --port 8000 --title "Plant Scheduling Editor"`.

In Agent Canvas, use the tabs at the top to switch views.

The app has two pages:

- **Power plants**: choose **Use 10 default plants** to edit the starter fleet, or drop a CSV onto the upload area (or click **Add power plant .csv**) to import your own fleet. Review the rows, then click **Save plants.csv** to write `input_app/plants.csv`. Importing alone does not save. The CSV must have the same columns as `input_app/plants.csv`.
- **Demand and reserve**: edit demand and reserve for each hour. The solid
  line is demand, and the dotted line is demand **plus** reserve, the capacity
  the schedule must cover. Click **Save demand.csv** to write
  `input_app/demand.csv`.

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
