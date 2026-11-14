"""Local web form that saves hourly demand to demand.csv.

From the project folder: python input_app/server.py
Then visit the Lab URL's /proxy/8000/ path, or localhost when running locally.
"""

import csv
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


FOLDER = Path(__file__).resolve().parent
DEMAND_CSV = FOLDER / "demand.csv"
RESERVE_FRACTION = 0.10  # Change this if the reserve rule changes.
PORT = 8000


def read_demand():
    with DEMAND_CSV.open(newline="") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, content, content_type="text/plain; charset=utf-8"):
        body = content if isinstance(content, bytes) else content.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/demand":
            _, rows = read_demand()
            self.respond(200, json.dumps(rows), "application/json; charset=utf-8")
            return
        # Only serve these known files; no user-supplied filesystem paths.
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/demand.csv": ("demand.csv", "text/csv; charset=utf-8"),
            "/plants.csv": ("plants.csv", "text/csv; charset=utf-8"),
        }
        if self.path not in files:
            self.respond(404, "Not found")
            return
        name, content_type = files[self.path]
        self.respond(200, (FOLDER / name).read_bytes(), content_type)

    def do_POST(self):
        if self.path != "/api/demand":
            self.respond(404, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 100_000:
                raise ValueError("Invalid request size")
            submitted = json.loads(self.rfile.read(length))
            columns, rows = read_demand()
            existing = {int(row["hour"]): row for row in rows}
            if not isinstance(submitted, list) or len(submitted) != len(rows):
                raise ValueError("Submit one value for every hour")
            seen = set()
            for item in submitted:
                hour = item["hour"]
                demand = item["demand_mw"]
                if type(hour) is not int or hour not in existing or hour in seen:
                    raise ValueError("Invalid or repeated hour")
                if type(demand) is not int or demand < 0:
                    raise ValueError("Demand must be a nonnegative whole number")
                seen.add(hour)
                existing[hour]["demand_mw"] = str(demand)
                existing[hour]["reserve_mw"] = str(round(demand * RESERVE_FRACTION))
                # Add validation and assignment for new CSV fields here.
            if seen != set(existing):
                raise ValueError("A demand hour is missing")
            with DEMAND_CSV.open("w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=columns)
                writer.writeheader()
                writer.writerows(rows)
            self.respond(200, "Saved")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self.respond(400, str(error))


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Open the Lab URL's /proxy/{PORT}/ path (or http://127.0.0.1:{PORT}/ locally). Ctrl+C to stop.")
    server.serve_forever()
