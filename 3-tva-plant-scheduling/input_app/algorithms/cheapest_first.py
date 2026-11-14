"""Port of the starter notebook's executable cheapest_first code cell.

This is a simple comparison rule, not an optimizer. It ignores startup costs,
minimum on/off times, and ramp limits; the app reports any resulting violations.
The notebook markdown gives a different cost expression; this follows the code.
"""

NAME = "Cheapest-first rule"
DESCRIPTION = (
    "Notebook cheapest_first: rank by (marginal cost + no-load cost) / maximum MW; "
    "add plants until demand plus reserve is covered. May break operating rules."
)


def cheapest_first(plants, demand, reserve):
    """Return one 0/1 plant-commitment row for each demand hour."""
    # This notebook score is only a fixed ranking, not a dispatch cost.
    # It intentionally reproduces the executable cell even though its units
    # and expression differ from the notebook's written description.
    order = sorted(
        range(len(plants)),
        key=lambda i: (
            (plants[i]["marginal_cost_per_mwh"] + plants[i]["no_load_cost_per_h"])
            / plants[i]["pmax_mw"]
        ),
    )
    schedule = []
    for load, safety_margin in zip(demand, reserve):
        # Each hour starts from zero independently; operating rules are checked
        # afterward by server.py rather than enforced by this comparison rule.
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
