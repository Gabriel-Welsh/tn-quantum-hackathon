"""Discover local scheduling algorithms without editing the web server.

Each .py file in this folder exports NAME and solve(plants, demand, reserve).
The solve function returns one row per hour, with one 0/1 value per plant.
"""

from importlib import import_module, invalidate_caches
from pathlib import Path


def available():
    """Return installed algorithms keyed by their Python filename."""
    invalidate_caches()
    algorithms = {}
    for path in sorted(Path(__file__).parent.glob("*.py")):
        if path.stem == "__init__" or path.stem.startswith("_"):
            continue
        module = import_module(f"algorithms.{path.stem}")
        if not callable(getattr(module, "solve", None)):
            raise ValueError(f"{path.name} must define solve(plants, demand, reserve)")
        algorithms[path.stem] = {
            "name": getattr(module, "NAME", path.stem.replace("_", " ").title()),
            "description": getattr(module, "DESCRIPTION", ""),
            "solve": module.solve,
        }
    return algorithms
