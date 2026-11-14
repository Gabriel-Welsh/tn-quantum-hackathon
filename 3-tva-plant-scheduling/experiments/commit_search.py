"""Plant-agnostic version of the "commit + amortized" (config F) hybrid.

Config F hard-coded "keep GAS_CC on while COAL alone is short". This program instead *finds*
which plants to commit and for which hours, for any fleet and any demand curve:

  1. Amortized startup (for every plant): when a plant is off, its startup is charged as
     startup / min_up_h in the QUBO and in the pick step, instead of all at once.
  2. Commitment search (classical, plant-agnostic): coordinate descent over one on-window
     [start, end] per plant (length >= min_up_h). A candidate set of windows is scored by running
     the classical hour-by-hour loop with those windows as must-on locks and adding up the exact
     cost. Keep the single best window change, repeat until nothing improves.
  3. QAOA then runs hour by hour with the found windows as locks plus the amortized costs,
     exactly like config F.

Run from 3-tva-plant-scheduling/ with the qBraid kernel's python:
    python experiments/commit_search.py
Writes experiments/commit_search_results.md.
"""
import contextlib, io, os, time

import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _nb import load_notebook

nb = load_notebook()
plants, N, names = nb["plants"], nb["N"], nb["names"]
locks, hour_ok, hour_cost = nb["locks"], nb["hour_ok"], nb["hour_cost"]
check_schedule, solve_milp = nb["check_schedule"], nb["solve_milp"]
build_qubo, add_locks, plant_hour_costs = nb["build_qubo"], nb["add_locks"], nb["plant_hour_costs"]
run_qaoa, choice_probs = nb["run_qaoa"], nb["choice_probs"]
INDEX_BITS, PLANT_INDEX, N_QUBITS = nb["INDEX_BITS"], nb["PLANT_INDEX"], nb["N_QUBITS"]

ALL = [tuple(int(b) for b in INDEX_BITS[k][:N]) for k in range(2 ** N)]
START = tuple(int(p["on_at_start"]) for p in plants)
PMAX = np.array([p["pmax_mw"] for p in plants])
PMIN = np.array([p["pmin_mw"] for p in plants])
MIN_UP = [int(p["min_up_h"]) for p in plants]


class Day:
    """One demand curve, with cached exact costs so the search is fast."""

    def __init__(self, demand, reserve):
        self.D, self.R, self.T = np.asarray(demand), np.asarray(reserve), len(demand)
        self._cost = {}

    def cost(self, t, c, was):
        key = (t, c, was)
        if key not in self._cost:
            self._cost[key] = hour_cost(plants, self.D[t], list(c), list(was))
        return self._cost[key]

    def fits(self, t, c):
        cv = np.array(c)
        return cv @ PMAX >= self.D[t] + self.R[t] and cv @ PMIN <= self.D[t]


def amortize_adj(was):
    """Per-plant $ adjustment: refund the part of the startup that belongs to later hours."""
    return np.array([-p["startup_cost"] * (1 - 1 / p["min_up_h"]) if not was[i] else 0.0
                     for i, p in enumerate(plants)])


def hour_locks(history, t, commit):
    must_on, must_off = locks(plants, [list(h) for h in history])
    must_on = list(must_on)
    for i, hrs in commit.items():
        if t in hrs and i not in must_on and i not in must_off:
            must_on.append(i)
    return must_on, list(must_off)


def run_day(day, commit, candidates=None):
    """Hour-by-hour loop. candidates(t, was, must_on, must_off) -> choices to consider
    (default: all 32, i.e. classical enumeration). Returns (exact cost, schedule)."""
    history, was, total = [], START, 0.0
    for t in range(day.T):
        must_on, must_off = hour_locks(history, t, commit)
        pool = ALL if candidates is None else candidates(t, was, must_on, must_off)
        locked = lambda c: all(c[i] for i in must_on) and not any(c[i] for i in must_off)
        ok = [c for c in pool if day.fits(t, c) and locked(c)] or [c for c in pool if day.fits(t, c)]
        if not ok and candidates is None:
            return np.inf, None
        ok = ok or list(pool)                    # sampled run with nothing valid: keep a rule-breaking pick
        adj = amortize_adj(was)
        pick = min(ok, key=lambda c: day.cost(t, c, was) + adj @ np.array(c))
        total += day.cost(t, pick, was)
        history.append(pick)
        was = pick
    return total, np.array(history)


def find_commitments(day, max_rounds=6, verbose=False):
    """Coordinate descent over one on-window per plant. Returns {plant: set(hours)} and a log."""
    commit, (best, _) = {}, run_day(day, {})
    log = [("none", best)]
    for _ in range(max_rounds):
        move = None
        for i in range(N):
            options = [set()] + [set(range(s, e + 1)) for s in range(day.T)
                                 for e in range(min(s + MIN_UP[i] - 1, day.T - 1), day.T)]
            for window in options:
                if window == commit.get(i, set()):
                    continue
                trial = {**commit, i: window}
                c, _ = run_day(day, trial)
                if c < best - 1e-6:
                    best, move = c, (i, window)
        if move is None:
            break
        commit[move[0]] = move[1]
        log.append((f"{names[move[0]]} hours {describe(move[1])}", best))
        if verbose:
            print(f"  commit {log[-1][0]:<32} -> ${best:,.0f}")
    return {i: w for i, w in commit.items() if w}, log


def describe(window):
    return f"{min(window)}-{max(window)}" if window else "none"


def qaoa_candidates(day, shots, sampler, seed):
    rng, state = np.random.default_rng(seed), {"angles": None}

    def candidates(t, was, must_on, must_off):
        Q, offset = build_qubo(plants, day.D[t], day.R[t], list(was))
        Q[np.arange(N), np.arange(N)] += amortize_adj(was)
        Q, offset = add_locks(Q, offset, must_on, must_off, weight=2 * plant_hour_costs(plants, list(was)).max())
        if sampler == "qaoa":
            state["angles"], probs = run_qaoa(Q, offset, p=1, start=state["angles"])
        else:
            probs = np.full(2 ** N_QUBITS, 1 / 2 ** N_QUBITS)
        samples = rng.choice(2 ** N_QUBITS, size=shots, p=probs / probs.sum())
        return [ALL[k] for k in np.unique(PLANT_INDEX[samples])]
    return candidates


def evaluate(day, schedule, milp_cost):
    with contextlib.redirect_stdout(io.StringIO()):
        r = check_schedule(plants, day.D, day.R, schedule, milp_cost=milp_cost, verbose=False)
    return r["gap_pct"], len(r["violations"])


if __name__ == "__main__":
    base_d, base_r = nb["demand"], nb["reserve"]
    noise = np.random.default_rng(3).normal(0, 0.05, len(base_d))
    VARIANTS = {
        "base day":               (base_d, base_r),
        "demand x0.70":           (base_d * 0.70, base_r * 0.70),
        "demand x0.85":           (base_d * 0.85, base_r * 0.85),
        "demand x1.05":           (base_d * 1.05, base_r * 1.05),
        "peak shifted +6 h":      (np.roll(base_d, 6), np.roll(base_r, 6)),
        "peak shifted -3 h":      (np.roll(base_d, -3), np.roll(base_r, -3)),
        "base +5% noise":         (base_d * (1 + noise), base_r * (1 + noise)),
    }
    SEEDS = range(3)
    out = []
    t0 = time.time()
    for vname, (D, R) in VARIANTS.items():
        day = Day(D, R)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                milp_cost, milp_sched, _, _ = solve_milp(plants, D, R)
        except RuntimeError as err:
            print(f"\n== {vname}: skipped, the MILP says it is infeasible ({err})")
            continue
        ts = time.time()
        commit, log = find_commitments(day)
        search_s = time.time() - ts
        found = ", ".join(f"{names[i]} {describe(w)}" for i, w in sorted(commit.items())) or "nothing"
        _, plain = run_day(day, {})                  # amortized only, no commitments
        _, classical = run_day(day, commit)          # commitments + classical enumeration
        row = dict(variant=vname, milp=milp_cost, found=found, search_s=search_s,
                   amort_only=evaluate(day, plain, milp_cost), classical=evaluate(day, classical, milp_cost))
        for shots, sampler in [(50, "qaoa"), (50, "random"), (200, "qaoa")]:
            res = [evaluate(day, run_day(day, commit, qaoa_candidates(day, shots, sampler, s))[1], milp_cost)
                   for s in SEEDS]
            row[f"{sampler}{shots}"] = res
        out.append(row)
        fmt = lambda rs: f"{sum(v == 0 for _, v in rs)}/{len(rs)} valid, mean {np.mean([g for g, v in rs if v == 0] or [np.nan]):+.2f}%"
        print(f"\n== {vname}: MILP ${milp_cost:,.0f}  (search {search_s:.1f} s)")
        print(f"   found commitments: {found}")
        print(f"   amortized only (classical): {row['amort_only'][0]:+.2f}%  broken {row['amort_only'][1]}")
        print(f"   commit + amortized (classical): {row['classical'][0]:+.2f}%  broken {row['classical'][1]}")
        for k in ["qaoa50", "random50", "qaoa200"]:
            print(f"   {k:<9}: {fmt(row[k])}")
    print(f"\ndone in {time.time() - t0:.0f} s")

    fmt = lambda rs: f"{sum(v == 0 for _, v in rs)}/{len(rs)}, {np.mean([g for g, v in rs if v == 0] or [np.nan]):+.2f}%"
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "commit_search_results.md"), "w") as f:
        f.write("# Plant-agnostic commitment search + QAOA: results\n\n"
                "Gaps are vs the MILP optimum for each demand curve. QAOA/random cells: valid days out of "
                f"{len(SEEDS)} seeds, mean gap of the valid ones.\n\n"
                "| demand curve | MILP $ | commitments found | search s | amortized only | commit + amortized "
                "(classical) | QAOA 50 shots | random 50 shots | QAOA 200 shots |\n"
                "|---|---|---|---|---|---|---|---|---|\n")
        for r in out:
            f.write(f"| {r['variant']} | {r['milp']:,.0f} | {r['found']} | {r['search_s']:.1f} | "
                    f"{r['amort_only'][0]:+.2f}% | {r['classical'][0]:+.2f}% | {fmt(r['qaoa50'])} | "
                    f"{fmt(r['random50'])} | {fmt(r['qaoa200'])} |\n")
