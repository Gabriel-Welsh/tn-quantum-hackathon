"""Fleet and demand input: CSV (same columns as data/plants.csv), interactive prompt, or synthetic."""
import csv

import numpy as np

import check

REQUIRED = ["plant_id", "pmin_mw", "pmax_mw", "marginal_cost_per_mwh", "no_load_cost_per_h",
            "startup_cost", "min_up_h", "min_down_h", "on_at_start"]
PROMPTS = {
    "plant_id": "name",
    "type": "type (free text)",
    "pmin_mw": "minimum output when on (MW)",
    "pmax_mw": "maximum output (MW)",
    "marginal_cost_per_mwh": "fuel cost per extra MWh ($)",
    "no_load_cost_per_h": "cost per hour of just being on ($)",
    "startup_cost": "startup cost ($)",
    "min_up_h": "minimum hours on once started",
    "min_down_h": "minimum hours off once stopped",
    "ramp_mw_per_h": "ramp limit (MW per hour)",
    "on_at_start": "running at midnight? (1 = yes, 0 = no)",
}
# The 5 plants of data/plants.csv, used as defaults in the prompt and as templates for synthetic fleets.
TEMPLATES = [
    dict(type="coal steam", pmin_mw=140, pmax_mw=350, marginal_cost_per_mwh=21.69, no_load_cost_per_h=546,
         startup_cost=36750, min_up_h=24, min_down_h=48, ramp_mw_per_h=240, on_at_start=1),
    dict(type="gas combined cycle", pmin_mw=168, pmax_mw=350, marginal_cost_per_mwh=26.84, no_load_cost_per_h=206,
         startup_cost=27650, min_up_h=8, min_down_h=5, ramp_mw_per_h=245, on_at_start=0),
    dict(type="gas combustion turbine", pmin_mw=20, pmax_mw=50, marginal_cost_per_mwh=28.89, no_load_cost_per_h=443,
         startup_cost=5150, min_up_h=3, min_down_h=3, ramp_mw_per_h=202, on_at_start=0),
    dict(type="gas combustion turbine (older)", pmin_mw=20, pmax_mw=50, marginal_cost_per_mwh=39.51,
         no_load_cost_per_h=749, startup_cost=5150, min_up_h=3, min_down_h=3, ramp_mw_per_h=202, on_at_start=0),
    dict(type="oil combustion turbine", pmin_mw=20, pmax_mw=50, marginal_cost_per_mwh=101.02, no_load_cost_per_h=694,
         startup_cost=130, min_up_h=1, min_down_h=1, ramp_mw_per_h=450, on_at_start=0),
]
SHORT = ["COAL", "GAS_CC", "PEAKER_A", "PEAKER_B", "OIL"]


def validate(plants):
    """Check required fields and fill optional ones. Raises ValueError with a clear message."""
    if not plants:
        raise ValueError("The fleet is empty.")
    seen = set()
    for k, p in enumerate(plants):
        missing = [f for f in REQUIRED if f not in p or p[f] in ("", None)]
        if missing:
            raise ValueError(f"Plant {k} ({p.get('plant_id', '?')}) is missing: {', '.join(missing)}")
        for f in REQUIRED[1:]:
            p[f] = float(p[f])
        p.setdefault("type", "unspecified")
        if p.get("ramp_mw_per_h") in ("", None):
            p["ramp_mw_per_h"] = p["pmax_mw"]
        p["ramp_mw_per_h"] = float(p["ramp_mw_per_h"])
        if p["plant_id"] in seen:
            raise ValueError(f"Duplicate plant_id {p['plant_id']}")
        seen.add(p["plant_id"])
        if not 0 <= p["pmin_mw"] <= p["pmax_mw"] or p["pmax_mw"] <= 0:
            raise ValueError(f"{p['plant_id']}: need 0 <= pmin <= pmax and pmax > 0")
        if p["min_up_h"] < 1 or p["min_down_h"] < 1:
            raise ValueError(f"{p['plant_id']}: min_up_h and min_down_h must be at least 1")
        if p["on_at_start"] not in (0.0, 1.0):
            raise ValueError(f"{p['plant_id']}: on_at_start must be 0 or 1")
    return plants


def load_fleet(path):
    return validate(check.load_plants(path))


def save_fleet(plants, path):
    cols = REQUIRED[:1] + ["type"] + REQUIRED[1:] + ["ramp_mw_per_h"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(plants)


def prompt_fleet(ask=input):
    """Ask for the number of plants, then each plant's details. Enter keeps the [default]."""
    n = int(ask("How many plants? "))
    plants = []
    for k in range(n):
        default = dict(TEMPLATES[k % len(TEMPLATES)], plant_id=f"{SHORT[k % 5]}_{k}")
        print(f"\nPlant {k + 1} of {n}  (Enter keeps the value in brackets)")
        p = {}
        for field, text in PROMPTS.items():
            got = ask(f"  {text} [{default[field]}]: ").strip()
            p[field] = got if got else default[field]
        plants.append(p)
    return validate(plants)


def load_demand(path, reserve_pct=None):
    """Hourly demand (and reserve) from a CSV with demand_mw and optionally reserve_mw columns."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    demand = np.array([float(r["demand_mw"]) for r in rows])
    if reserve_pct is not None or "reserve_mw" not in rows[0]:
        reserve = demand * (reserve_pct if reserve_pct is not None else 0.10)
    else:
        reserve = np.array([float(r["reserve_mw"]) for r in rows])
    return demand, reserve


def synthetic_fleet(n, seed=0):
    """n plants built from the 5 templates (2 large : 3 small, like the real fleet), costs jittered +-15%.
    Large units are 300 or 350 MW, small ones 50 MW, so capacity is a whole number of 50 MW blocks."""
    rng = np.random.default_rng(seed)
    order = [0, 1, 2, 3, 4]
    plants = []
    for k in range(n):
        t = order[k % 5] if k < 5 else int(rng.choice([0, 1, 1, 2, 2, 3, 3, 4]))
        p = dict(TEMPLATES[t])
        j = lambda: float(rng.uniform(0.85, 1.15))
        p.update(plant_id=f"{SHORT[t]}_{k}",
                 marginal_cost_per_mwh=round(p["marginal_cost_per_mwh"] * j(), 2),
                 no_load_cost_per_h=round(p["no_load_cost_per_h"] * j()),
                 startup_cost=round(p["startup_cost"] * j()))
        if t < 2 and k >= 5:
            p["pmax_mw"] = float(rng.choice([300, 350]))
            p["pmin_mw"] = round(p["pmax_mw"] * (0.4 if t == 0 else 0.48))
        p["on_at_start"] = 1 if t == 0 else 0
        plants.append(p)
    return validate(plants)


def scaled_demand(plants, base_demand, base_reserve, peak_share=0.9):
    """Scale a demand curve so peak demand + reserve is `peak_share` of the fleet's capacity."""
    cap = sum(p["pmax_mw"] for p in plants)
    k = peak_share * cap / (base_demand + base_reserve).max()
    return np.round(base_demand * k), np.round(base_reserve * k)
