"""Port of the starter notebook's documented cheapest-first commitment rule.

This is a simple comparison rule, not an optimizer. It ignores startup costs,
minimum on/off times, and ramp limits; the app reports any resulting violations.
"""

NAME = "Cheapest-first rule"
DESCRIPTION = (
    "Rank by marginal cost plus no-load cost per MW at full output; turn on "
    "plants until demand plus reserve is covered. May break operating rules."
)


def cheapest_first(plants, demand, reserve):
    """Return one 0/1 plant-commitment row for each demand hour."""
    order = sorted(
        range(len(plants)),
        key=lambda i: (
            plants[i]["marginal_cost_per_mwh"]
            + plants[i]["no_load_cost_per_h"] / plants[i]["pmax_mw"]
        ),
    )
    schedule = []
    for load, safety_margin in zip(demand, reserve):
        on = [0] * len(plants)
        capacity = 0
        for i in order:
            if capacity >= load + safety_margin:
                break
            on[i] = 1
            capacity += plants[i]["pmax_mw"]
        schedule.append(on)
    return schedule


# The web app calls solve() for every module in this folder.
solve = cheapest_first
