"""Starter algorithm: the project's classical unit commitment solver."""

from check import solve_milp

NAME = "Classical baseline"
DESCRIPTION = "The starter notebook's exact mixed-integer baseline for its modeled rules."


def solve(plants, demand, reserve):
    """Return an hours-by-plants 0/1 commitment schedule."""
    # The MILP optimizes dispatch and commitment across the whole horizon.
    # The page needs only on/off choices; server.py evaluates the returned
    # schedule with the shared checker. Ramps use solve_milp's default (off).
    _, schedule, _, _ = solve_milp(plants, demand, reserve)
    return schedule
