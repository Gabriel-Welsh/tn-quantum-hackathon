# Hourly demand form

From the project folder, run `python input_app/server.py`. In qBraid Lab,
open the Lab URL with `/lab` replaced by `/proxy/8000/` (keep any URL prefix
before `/lab`). If running locally, open <http://127.0.0.1:8000/>.
Change any hourly demand and click
**Save CSV**. The app writes `input_app/demand.csv`; it also includes a starting
`input_app/plants.csv` that you can edit in a spreadsheet.

To load these files in the project notebook or another Python script:

```python
from check import load_plants, load_demand
plants = load_plants("input_app/plants.csv")
demand, reserve = load_demand("input_app/demand.csv")
```

Comments in `app.js` and `server.py` point to where you can add more fields.
The server listens only on this computer. Stop it with Ctrl+C.
