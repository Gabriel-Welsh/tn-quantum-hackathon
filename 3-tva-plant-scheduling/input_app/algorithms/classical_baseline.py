"""Starter algorithm: the project's classical unit commitment solver."""

from check import solve_milp

NAME = "Classical baseline"
DESCRIPTION = "Mixed-integer optimization with demand, reserve, plant limits and ramps."


def solve(plants, demand, reserve):
    """Return an hours-by-plants 0/1 commitment schedule."""
    _, schedule, _, _ = solve_milp(plants, demand, reserve, ramps=True)
    return schedule
