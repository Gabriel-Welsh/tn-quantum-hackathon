"""Use simulated QAOA samples to warm-start the full-day HiGHS MILP.

This wraps the project's quantum_warm_start_milp.py experiment for the webapp.
It uses the plants and demand saved in input_app, returns only the final on/off
schedule, and never submits a QPU job. The full MILP still checks and optimizes
the schedule; this option is not evidence of a runtime speedup by itself.
"""

from importlib.util import find_spec

NAME = "Quantum warm-start MILP"
DESCRIPTION = (
    "Local simulated QAOA proposes block-level commitments; classical repair "
    "gives HiGHS a feasible starting solution for the full-day MILP. "
    "No QPU run or speedup claim."
)


def solve(plants, demand, reserve):
    """Return a full-day commitment matrix from HiGHS with a QAOA warm start."""
    if find_spec("highspy") is None:
        raise RuntimeError(
            "Quantum warm-start MILP needs highspy. Run the app with a qBraid-SDK "
            "Python environment that has highspy installed."
        )
    if len(plants) > 16:
        raise ValueError("Local warm-start QAOA supports at most 16 plants (one block each).")

    # Import lazily so the other webapp algorithms do not require highspy.
    import numpy as np
    from quantum_warm_start_milp import (
        Milp, Qubo, full_solution, repair, run_highs, solve_qaoa,
        split_into_blocks, true_cost,
    )

    model = Milp(plants, demand, reserve)
    # Keep the local simulator responsive: at most 16 QUBO bits, and at most
    # two time blocks. This is a warm-start proposal, not the exact MILP model.
    blocks_count = min(2, len(demand), max(1, 16 // len(plants)))
    blocks = split_into_blocks(demand + reserve, blocks_count)
    qubo = Qubo(plants, demand, reserve, blocks)
    candidates, _ = solve_qaoa(
        qubo, p=1, shots=200, maxiter=20, seed=7, sampler="numpy",
        log=lambda _: None,
    )

    # Repair QUBO proposals against the exact multi-hour constraints. HiGHS
    # receives the cheapest complete, feasible MILP vector as its start.
    best_schedule, best_cost = None, float("inf")
    for bits in candidates[:30]:
        repaired = repair(model, qubo.to_schedule(bits, len(demand)))
        if repaired is None:
            continue
        cost = true_cost(model, repaired)
        if cost is not None and cost < best_cost:
            best_schedule, best_cost = repaired, cost
    if best_schedule is None:
        raise RuntimeError("QAOA samples did not yield a repairable MILP warm start.")
    start = full_solution(model, best_schedule)
    if start is None or model.violations(start):
        raise RuntimeError("The repaired QAOA warm start did not satisfy the MILP rules.")

    result = run_highs(model, start=start, time_limit=20, seed=7, threads=1)
    x = result["x"]
    if len(x) != model.N or model.violations(x):
        raise RuntimeError(f"HiGHS did not return a valid schedule: {result['status']}")
    n, hours = len(plants), len(demand)
    return np.rint(x[:n * hours]).reshape(n, hours).T.astype(int)
