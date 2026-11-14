"""Hour-by-hour scheduling with incentives and a pluggable sampler (QAOA, random, or exact enumeration).

Incentive modes:
  none        the notebook's loop: the QUBO and pick step see only this hour's cost
  amortize    startup charged as startup / min_up_h (config B)
  lagrangian  this hour's cost + each plant's priced cost-to-go from incentives.py (the general version)
"""
import itertools

import numpy as np

import check
from .qaoa import QAOASampler, RandomSampler, build_hour_qubo


class Tracker:
    """On/off state of each plant and how long it has been held (for cost-to-go lookups)."""

    def __init__(self, plants):
        self.plants = plants
        self.on = [int(p["on_at_start"]) for p in plants]
        self.held = [10 ** 6] * len(plants)            # the midnight state lasted "long enough"

    def after(self, i, choice_i):
        return (choice_i, self.held[i] + 1 if choice_i == self.on[i] else 1)

    def step(self, choice):
        for i, c in enumerate(choice):
            self.on[i], self.held[i] = self.after(i, c)


def hour_adjustments(plants, inc, mode, t, tracker):
    """Per-plant $ term added to x_i (in the QUBO) and to the pick score, relative to 'off'."""
    n = len(plants)
    if mode == "none":
        return np.zeros(n)
    if mode == "amortize":
        return np.array([-p["startup_cost"] * (1 - 1 / p["min_up_h"]) if not tracker.on[i] else 0.0
                         for i, p in enumerate(plants)])
    if mode == "lagrangian":
        return np.array([inc.future(i, t + 1, *tracker.after(i, 1)) - inc.future(i, t + 1, *tracker.after(i, 0))
                         for i in range(n)])
    raise ValueError(mode)


def run_day(plants, demand, reserve, inc=None, mode="lagrangian", sampler="qaoa", shots=200, seed=7,
            p=1, penalty=None, max_exact=14, fix_locked=True):
    """Returns (schedule [T x N], log). sampler: 'qaoa', 'random' or 'exact' (all 2^N choices).
    fix_locked: plants forced by min up/down are set classically and left out of the QUBO."""
    n, T = len(plants), len(demand)
    rng = np.random.default_rng(seed)
    smp = QAOASampler(p=p) if sampler == "qaoa" else RandomSampler()
    if sampler == "exact" and n > max_exact:
        raise ValueError(f"exact enumeration of 2^{n} choices per hour is too slow; use qaoa or random")
    tracker, history, log = Tracker(plants), [], []
    for t in range(T):
        must_on, must_off = check.locks(plants, history)
        adj = hour_adjustments(plants, inc, mode, t, tracker)
        was = list(tracker.on)
        qubo = build_hour_qubo(plants, demand[t], reserve[t], was, adj, must_on, must_off, penalty, fix_locked)
        mass = None
        if sampler == "exact":
            pool = [tuple(c) for c in itertools.product([0, 1], repeat=n)]
        elif qubo.n_plants == 0:                       # every plant is locked this hour
            pool = [qubo.to_choice(0, n)]
        else:
            samples, probs = smp.sample(qubo, shots, rng)
            m = 2 ** qubo.n_plants
            plant_idx = samples & (m - 1)
            pool = [qubo.to_choice(int(k), n) for k in np.unique(plant_idx)]
            mass = dict(zip((qubo.to_choice(k, n) for k in range(m)), probs.reshape(-1, m).sum(0)))
        fits = lambda c: check.hour_ok(plants, demand[t], reserve[t], c, must_on, must_off)
        ok = [c for c in pool if fits(c)] or \
             [c for c in pool if check.hour_ok(plants, demand[t], reserve[t], c)] or pool
        score = lambda c: check.hour_cost(plants, demand[t], c, was) + float(adj @ np.array(c))
        pick = min(ok, key=score)
        log.append(dict(hour=t, pick=pick, n_unique=len(pool), qubits=qubo.n_qubits,
                        p_pick=None if mass is None else float(mass.get(pick, 0.0)),
                        angles=None if sampler != "qaoa" else (None if smp.angles is None else smp.angles.copy()),
                        qubo=qubo))
        history.append(list(pick))
        tracker.step(pick)
    return np.array(history), log
