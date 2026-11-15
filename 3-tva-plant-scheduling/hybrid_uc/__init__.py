"""Hybrid unit commitment: classical incentives (Lagrangian prices + cost-to-go) + QAOA + classical repair.

Works for any number of plants. Exact costs, rules and the MILP baseline come from ../scheduling/check.py.
Entry points:
    python -m hybrid_uc.run --help        one fleet + one demand curve, end to end
    python -m hybrid_uc.analyze           the benchmark behind hybrid_uc/RESULTS.md
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scheduling"))
