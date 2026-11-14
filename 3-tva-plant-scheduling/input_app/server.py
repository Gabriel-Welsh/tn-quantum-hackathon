"""Local web app for editing plants.csv and hourly demand.csv.

From the project folder: python input_app/server.py
In qBraid Lab, open the Lab URL's /proxy/8000/ path or use Agent Canvas.
"""

import csv
import json
import math
import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit


FOLDER = Path(__file__).resolve().parent
DEMAND_CSV = FOLDER / "demand.csv"
PLANTS_CSV = FOLDER / "plants.csv"
PORT = 8000

# Add validation here when you add new numeric plant fields to plants.csv.
PLANT_NUMBERS = (
    "pmin_mw", "pmax_mw", "marginal_cost_per_mwh", "no_load_cost_per_h",
    "startup_cost", "min_up_h", "min_down_h", "ramp_mw_per_h", "on_at_start", "scale",
)
PLANT_INTEGERS = {"min_up_h", "min_down_h", "on_at_start"}


def read_csv(path):
    with path.open(newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def write_csv(path, columns, rows):
    """Replace the CSV only after a complete new copy has been written."""
    with tempfile.NamedTemporaryFile("w", newline="", dir=FOLDER, delete=False) as file:
        temp_path = Path(file.name)
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def nonnegative_number(value, name, integer=False):
    if integer:
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative whole number")
    elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a nonnegative number")
    return value


def save_demand(submitted):
    columns, rows = read_csv(DEMAND_CSV)
    if not isinstance(submitted, list) or len(submitted) != len(rows):
        raise ValueError("Submit one value for every hour")
    existing = {int(row["hour"]): row for row in rows}
    seen = set()
    for item in submitted:
        if not isinstance(item, dict):
            raise ValueError("Each hour must be an object")
        hour = item.get("hour")
        if type(hour) is not int or hour not in existing or hour in seen:
            raise ValueError("Invalid or repeated hour")
        seen.add(hour)
        demand = nonnegative_number(item.get("demand_mw"), "Demand", integer=True)
        reserve = nonnegative_number(item.get("reserve_mw"), "Reserve", integer=True)
        existing[hour]["demand_mw"] = str(demand)
        existing[hour]["reserve_mw"] = str(reserve)
        # To add hourly fields, validate and assign them here and in app.js.
    if seen != set(existing):
        raise ValueError("A demand hour is missing")
    write_csv(DEMAND_CSV, columns, rows)


def save_plants(submitted):
    columns, previous = read_csv(PLANTS_CSV)
    required = {"plant_id", "type", "rts_gen_uid", *PLANT_NUMBERS}
    if not required.issubset(columns):
        raise ValueError("plants.csv is missing a required column")
    if not isinstance(submitted, list) or not submitted:
        raise ValueError("Submit at least one power plant")
    old_by_id = {row["plant_id"]: row for row in previous}
    seen = set()
    rows = []
    for item in submitted:
        if not isinstance(item, dict):
            raise ValueError("Each plant must be an object")
        plant_id = item.get("plant_id")
        plant_type = item.get("type")
        uid = item.get("rts_gen_uid")
        if not isinstance(plant_id, str) or not plant_id.strip():
            raise ValueError("Every plant needs a plant ID")
        plant_id = plant_id.strip()
        if plant_id in seen:
            raise ValueError(f"Repeated plant ID: {plant_id}")
        if not isinstance(plant_type, str) or not plant_type.strip():
            raise ValueError(f"{plant_id} needs a plant type")
        if not isinstance(uid, str):
            raise ValueError(f"{plant_id} has an invalid RTS generator ID")
        seen.add(plant_id)

        # Keep extra CSV columns for existing plants. Add their inputs and
        # validation here and in plants.js when expanding the starter.
        row = {name: old_by_id.get(plant_id, {}).get(name, "") for name in columns}
        row.update(plant_id=plant_id, type=plant_type.strip(), rts_gen_uid=uid.strip())
        values = {}
        for name in PLANT_NUMBERS:
            value = nonnegative_number(item.get(name), f"{plant_id}: {name}",
                                       integer=name in PLANT_INTEGERS)
            values[name] = value
            row[name] = str(value)
        if values["pmax_mw"] <= 0 or values["pmin_mw"] > values["pmax_mw"]:
            raise ValueError(f"{plant_id}: maximum output must exceed zero and minimum output")
        if values["scale"] <= 0:
            raise ValueError(f"{plant_id}: scale must exceed zero")
        if values["on_at_start"] not in (0, 1):
            raise ValueError(f"{plant_id}: on_at_start must be 0 or 1")
        rows.append(row)
    write_csv(PLANTS_CSV, columns, rows)


class Handler(BaseHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        # Do not print qBraid URL query strings, which can contain a token.
        self.log_message("%s %s -> %s", self.command, urlsplit(self.path).path, code)

    def respond(self, code, content, content_type="text/plain; charset=utf-8"):
        body = content if isinstance(content, bytes) else content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # qBraid may append a query string. Route using just the path.
        path = urlsplit(self.path).path
        if path in ("/api/demand", "/api/plants"):
            csv_path = DEMAND_CSV if path == "/api/demand" else PLANTS_CSV
            _, rows = read_csv(csv_path)
            self.respond(200, json.dumps(rows), "application/json; charset=utf-8")
            return
        # Only serve these known files; no user-supplied filesystem paths.
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/plants.html": ("plants.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/navigation.js": ("navigation.js", "text/javascript; charset=utf-8"),
            "/plants.js": ("plants.js", "text/javascript; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/demand.csv": ("demand.csv", "text/csv; charset=utf-8"),
            "/plants.csv": ("plants.csv", "text/csv; charset=utf-8"),
        }
        if path not in files:
            self.respond(404, "Not found")
            return
        name, content_type = files[path]
        self.respond(200, (FOLDER / name).read_bytes(), content_type)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/demand", "/api/plants"):
            self.respond(404, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 100_000:
                raise ValueError("Invalid request size")
            submitted = json.loads(self.rfile.read(length))
            if path == "/api/demand":
                save_demand(submitted)
            else:
                save_plants(submitted)
            self.respond(200, "Saved")
        except (ValueError, KeyError, TypeError) as error:
            self.respond(400, str(error))


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Open the Lab URL's /proxy/{PORT}/ path (or http://127.0.0.1:{PORT}/ locally). Ctrl+C to stop.")
    server.serve_forever()
