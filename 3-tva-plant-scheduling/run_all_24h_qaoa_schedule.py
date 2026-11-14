#!/usr/bin/env python3
"""Unit commitment for the whole day as ONE QUBO (all hours at once), instead of hour by hour.

Variables (all 0/1):
  x[i,t]   plant i is on in hour t                                     (plants x hours)
  v[i,t]   plant i starts in hour t      = x[i,t] * (1 - x[i,t-1])     (plants with min_up > 1)
  s[i,t]   plant i stops in hour t       = x[i,t-1] * (1 - x[i,t])     (plants with min_down > 1)
  σ[k,t]   slack bits: spare capacity in hour t, in blocks, written in binary
Hour 0 uses the plants' on_at_start state, so v[i,0] and s[i,0] are plain functions of x[i,0].

Energy (lower is better):
  cost        sum_t sum_i  c_i x[i,t] + startup_i * v[i,t]
              c_i = no_load_i + pmin_i * (marginal_i - marginal_cheapest)   (the starter's TODO 2 approximation)
              plants with min_up = 1 pay startup through x[i,t](1 - x[i,t-1]) directly (no v variable)
  capacity    A * (sum_i a_i x[i,t] - sum_k 2^k σ[k,t] - r_t)^2    a_i = pmax_i / block, r_t = ceil(need_t / block)
  v, s links  B * (z + a - a b - 2 z a + 2 z b)    zero iff z = a (1 - b)   (Rosenberg penalty)
              v: a = x[i,t], b = x[i,t-1];   s: a = x[i,t-1], b = x[i,t]
  min up      C * v[i,t] * (1 - x[i,τ])   for τ = t+1 .. t+min_up-1      (started: stay on)
  min down    C * s[i,t] * x[i,τ]         for τ = t+1 .. t+min_down-1    (stopped: stay off)
These match check.py's rules exactly. Not in the QUBO: "minimum outputs can't exceed demand"
(checked classically, as in the starter) and the exact dispatch cost (the QUBO uses c_i).

Solvers:
  anneal (default)  simulated annealing on the SAME QUBO a quantum computer would get (classical).
                    It flips on/off bits (single hours or runs of hours) and sets the helper bits
                    (start, stop, slack) to their best values, so the energy it minimizes is exactly
                    the QUBO energy. --anneal-mode full flips any single bit instead (gets stuck).
  qaoa              QAOA on the exact statevector. Only possible for small QUBOs (about 20 qubits),
                    so use --horizon to cut the day down; the full day needs hundreds of qubits.
  none              build the QUBO, print its size, and check it against the MILP's schedule.
After solving, the best schedule is checked with check.py and (unless --no-polish) repaired and
improved by classical local search over whole runs of hours.

Usage (run from this folder, with the qBraid-SDK environment's Python):
  python run_all_24h_qaoa_schedule.py                                   # data/plants.csv, data/demand.csv
  python run_all_24h_qaoa_schedule.py --plants data/plants10.csv --demand data/demand10.csv
  python run_all_24h_qaoa_schedule.py --solver none                     # QUBO size + MILP check only
  python run_all_24h_qaoa_schedule.py --solver qaoa --horizon 1         # small enough for QAOA
  python run_all_24h_qaoa_schedule.py --save-qubo day_qubo.json         # export for other QUBO solvers
"""
import argparse
import csv
import itertools
import json
import math
import sys
import time
from collections import defaultdict
from functools import reduce
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import check_schedule, dispatch_hour, load_demand, load_plants, solve_milp  # noqa: E402


# ------------------------------------------------------------------ QUBO builder
class QuboBuilder:
    """Collects linear, quadratic and constant terms. A 'form' is a linear expression ({var: coef}, const)."""

    def __init__(self):
        self.names, self.kind = [], []
        self.lin, self.quad, self.const = defaultdict(float), defaultdict(float), 0.0

    def var(self, name, kind):
        self.names.append(name)
        self.kind.append(kind)
        return len(self.names) - 1

    def add(self, fa, fb, w):
        """Add w * fa * fb, where fa and fb are linear forms (products of 0/1 bits: y*y = y)."""
        (da, ca), (db, cb) = fa, fb
        self.const += w * ca * cb
        for k, a in da.items():
            self.lin[k] += w * a * cb
        for k, b in db.items():
            self.lin[k] += w * b * ca
        for k, a in da.items():
            for l, b in db.items():
                if k == l:
                    self.lin[k] += w * a * b
                else:
                    self.quad[(min(k, l), max(k, l))] += w * a * b

    def matrix(self):
        """Upper-triangular Q (diagonal = linear terms) and the constant offset."""
        N = len(self.names)
        Q = np.zeros((N, N))
        for k, c in self.lin.items():
            Q[k, k] += c
        for (k, l), c in self.quad.items():
            Q[k, l] += c
        return Q, self.const


ONE = ({}, 1.0)


def bit(k):
    return ({k: 1.0}, 0.0)


def const(c):
    return ({}, float(c))


def one_minus(f):
    d, c = f
    return ({k: -v for k, v in d.items()}, 1.0 - c)


def hourly_costs(plants):
    m = min(p["marginal_cost_per_mwh"] for p in plants)
    return np.array([p["no_load_cost_per_h"] + p["pmin_mw"] * (p["marginal_cost_per_mwh"] - m) for p in plants])


def default_block(plants):
    pmax = [p["pmax_mw"] for p in plants]
    if all(float(v).is_integer() for v in pmax):
        return float(reduce(math.gcd, [int(v) for v in pmax]))
    return 50.0


def build_day_qubo(plants, demand, reserve, block_mw, penalty_scale=1.0):
    n, T = len(plants), len(demand)
    qb = QuboBuilder()
    c = hourly_costs(plants)
    start = [int(p["on_at_start"]) for p in plants]
    base = c.max() + max(p["startup_cost"] for p in plants)
    A = 2.0 * base * penalty_scale                     # capacity (per block^2)
    C = 1.0 * base * penalty_scale                     # min up / min down (per broken hour)
    wmax = max(min(T, int(max(p["min_up_h"], p["min_down_h"]))) for p in plants)
    B = (max(p["startup_cost"] for p in plants) + C * wmax) * 1.1   # v/s links: cheating must never pay
    weights = dict(A=A, B=B, C=C)

    X = [[qb.var(f"x[{p['plant_id']},{t}]", "x") for t in range(T)] for p in plants]

    def xf(i, t):
        return const(start[i]) if t < 0 else bit(X[i][t])

    V: list[list[tuple | None]] = [[None] * T for _ in range(n)]     # start indicator (form) per plant, hour
    S: list[list[tuple | None]] = [[None] * T for _ in range(n)]     # stop indicator (form) per plant, hour
    for i, p in enumerate(plants):
        for t in range(T):
            a_on, a_prev = xf(i, t), xf(i, t - 1)
            if t == 0:                                  # hour 0: on_at_start is a constant
                V[i][0] = ({X[i][0]: 1.0 - start[i]}, 0.0)
                S[i][0] = ({X[i][0]: -float(start[i])}, float(start[i]))
                continue
            if p["min_up_h"] > 1:
                z = qb.var(f"v[{p['plant_id']},{t}]", "v")
                V[i][t] = bit(z)
                for fa, fb, w in [(bit(z), ONE, B), (a_on, ONE, B), (a_on, a_prev, -B),
                                  (bit(z), a_on, -2 * B), (bit(z), a_prev, 2 * B)]:
                    qb.add(fa, fb, w)
            if p["min_down_h"] > 1:
                z = qb.var(f"s[{p['plant_id']},{t}]", "s")
                S[i][t] = bit(z)
                for fa, fb, w in [(bit(z), ONE, B), (a_prev, ONE, B), (a_prev, a_on, -B),
                                  (bit(z), a_prev, -2 * B), (bit(z), a_on, 2 * B)]:
                    qb.add(fa, fb, w)

    # cost
    for i, p in enumerate(plants):
        for t in range(T):
            qb.add(xf(i, t), ONE, c[i])
            if V[i][t] is not None:
                qb.add(V[i][t], ONE, p["startup_cost"])
            else:                                       # no v variable: startup = x_t (1 - x_{t-1})
                qb.add(xf(i, t), one_minus(xf(i, t - 1)), p["startup_cost"])

    # min up / min down
    for i, p in enumerate(plants):
        for t in range(T):
            for tau in range(t + 1, min(T, t + int(p["min_up_h"]))):
                if V[i][t] is not None:
                    qb.add(V[i][t], one_minus(xf(i, tau)), C)
            for tau in range(t + 1, min(T, t + int(p["min_down_h"]))):
                if S[i][t] is not None:
                    qb.add(S[i][t], xf(i, tau), C)

    # capacity, with slack bits sized to the most spare capacity possible that hour
    a = np.array([p["pmax_mw"] / block_mw for p in plants])
    total_blocks = a.sum()
    slack, r_all = [], []
    for t in range(T):
        r = math.ceil((demand[t] + reserve[t]) / block_mw - 1e-9)
        r_all.append(r)
        max_spare = int(math.floor(total_blocks - r + 1e-9))
        if max_spare < 0:
            print(f"warning: hour {t} needs {r} blocks but the fleet only has {total_blocks:g}: no valid schedule.")
        K = max(0, max_spare).bit_length()
        sig = [qb.var(f"slack[{k},{t}]", "slack") for k in range(K)]
        slack.append(sig)
        form = ({X[i][t]: a[i] for i in range(n)}, -float(r))
        for k, sk in enumerate(sig):
            form[0][sk] = -(2.0 ** k)
        qb.add(form, form, A)

    info: dict = dict(X=X, V=V, S=S, slack=slack, r=r_all, a=a, c=c, weights=weights, start=start)
    return qb, info


def encode(schedule, info, n_vars):
    """Full bit vector for a 0/1 schedule: aux bits set consistently, slack set to the best value."""
    X, V, S, slack, r, a, start = (info[k] for k in ("X", "V", "S", "slack", "r", "a", "start"))
    sch = np.asarray(schedule, dtype=int)
    T, n = sch.shape
    y = np.zeros(n_vars)
    for i in range(n):
        for t in range(T):
            y[X[i][t]] = sch[t, i]
            prev = start[i] if t == 0 else sch[t - 1, i]
            if t > 0 and V[i][t] is not None:
                y[next(iter(V[i][t][0]))] = sch[t, i] * (1 - prev)
            if t > 0 and S[i][t] is not None:
                y[next(iter(S[i][t][0]))] = prev * (1 - sch[t, i])
    for t in range(T):
        spare = int(round(float(a @ sch[t]) - r[t]))
        spare = min(max(spare, 0), 2 ** len(slack[t]) - 1)
        for k, sk in enumerate(slack[t]):
            y[sk] = (spare >> k) & 1
    return y


def decode(y, info, T, n):
    return np.array([[int(round(y[info["X"][i][t]])) for i in range(n)] for t in range(T)])


def qubo_energy(Q, offset, y):
    return float(y @ Q @ y + offset)


# ------------------------------------------------------------------ the QUBO energy as a function of x alone
class XEnergy:
    """E*(x) = min over the helper bits (v, s, slack) of the QUBO energy, for an on/off schedule x.
    The helpers are fully determined by x (v, s follow from x; the best slack is the spare capacity,
    clipped to what the bits can hold), so E*(x) == qubo_energy(Q, offset, encode(x)) exactly.
    Split into per-plant and per-hour parts so a one-bit change in x is cheap to re-score."""

    def __init__(self, plants, info, T):
        self.T, self.n = T, len(plants)
        self.c, self.a, self.r = info["c"], info["a"], np.array(info["r"], dtype=float)
        self.A, self.C = info["weights"]["A"], info["weights"]["C"]
        self.start = np.array(info["start"], dtype=float)
        self.su = np.array([p["startup_cost"] for p in plants])
        self.smax = np.array([2 ** len(sl) - 1 for sl in info["slack"]], dtype=float)
        self.up = [self._band(int(p["min_up_h"])) if p["min_up_h"] > 1 else None for p in plants]
        self.down = [self._band(int(p["min_down_h"])) if p["min_down_h"] > 1 else None for p in plants]

    def _band(self, L):
        M = np.zeros((self.T, self.T))                  # M[t, τ] = 1 for τ = t+1 .. t+L-1
        for t in range(self.T):
            M[t, t + 1 : min(self.T, t + L)] = 1
        return M

    def plant(self, i, col):
        prev = np.concatenate([[self.start[i]], col[:-1]])
        v, s = col * (1 - prev), prev * (1 - col)
        e = self.c[i] * col.sum() + self.su[i] * v.sum()
        if self.up[i] is not None:
            e += self.C * v @ (self.up[i] @ (1 - col))
        if self.down[i] is not None:
            e += self.C * s @ (self.down[i] @ col)
        return e

    def hours(self, X, t0=0):                           # X: rows for hours t0.. -> capacity penalty per hour
        r, smax = self.r[t0 : t0 + len(X)], self.smax[t0 : t0 + len(X)]
        b = X @ self.a - r                              # spare capacity in blocks
        gap = np.where(b < 0, b, np.where(b > smax, b - smax, b - np.round(b)))
        return self.A * gap ** 2

    def total(self, X):
        return sum(self.plant(i, X[:, i]) for i in range(self.n)) + self.hours(X).sum()


# ------------------------------------------------------------------ simulated annealing
def anneal_x(xe, sweeps, chains, seed, t_hot, t_cold, block_moves=True):
    """Annealing over the on/off bits x only (helpers at their optimum). Returns (best X, best E*).
    Each move sets one plant on or off for a run of hours (length 1 = a single bit flip). Runs matter:
    min up / min down make most single-hour changes expensive, so one-bit moves alone get stuck."""
    rng = np.random.default_rng(seed)
    T, n = xe.T, xe.n
    lengths = np.array(sorted({1, 2, 3, 4, 6, 8, 12, T})) if block_moves else np.array([1])
    best_X, best_E = np.zeros((T, n), dtype=int), np.inf
    temps = np.geomspace(t_hot, t_cold, sweeps)
    for _ in range(chains):
        X = rng.integers(0, 2, size=(T, n)).astype(float)
        pe = np.array([xe.plant(i, X[:, i]) for i in range(n)])
        he = xe.hours(X)
        E = pe.sum() + he.sum()
        for temp in temps:
            for _ in range(T * n):
                i, t0 = rng.integers(n), rng.integers(T)
                t1 = min(T, t0 + int(rng.choice(lengths)))
                val = 1.0 - X[t0, i]                       # set the run to the opposite of its first hour
                old = X[t0:t1, i].copy()
                if (old == val).all():
                    continue
                X[t0:t1, i] = val
                new_p = xe.plant(i, X[:, i])
                new_h = xe.hours(X[t0:t1], t0)
                dE = (new_p - pe[i]) + (new_h.sum() - he[t0:t1].sum())
                if dE <= 0 or rng.random() < math.exp(-dE / temp):
                    pe[i], E = new_p, E + dE
                    he[t0:t1] = new_h
                    if E < best_E:
                        best_E, best_X = E, X.astype(int)
                else:
                    X[t0:t1, i] = old
    return best_X, best_E


def anneal(Q, offset, sweeps, chains, seed, t_hot, t_cold, init=None):
    """Single-bit-flip Metropolis annealing, `chains` independent runs in parallel. Returns (best y, best E)."""
    rng = np.random.default_rng(seed)
    N = len(Q)
    W = Q + Q.T
    d = np.diag(Q).copy()
    np.fill_diagonal(W, 0.0)                           # W = symmetric couplings, d = linear terms
    y = rng.integers(0, 2, size=(chains, N)).astype(float) if init is None else np.tile(init, (chains, 1))
    h = y @ W                                          # h[c, k] = sum_j W[k, j] y[c, j]
    E = np.einsum("ck,ck->c", y, d + 0.5 * h) + offset
    best_E, best_y = E.min(), y[E.argmin()].copy()
    for temp in np.geomspace(t_hot, t_cold, sweeps):
        for k in rng.permutation(N):
            dy = 1.0 - 2.0 * y[:, k]
            dE = dy * (d[k] + h[:, k])
            acc = (dE <= 0) | (rng.random(chains) < np.exp(-np.clip(dE, 0, None) / temp))
            if acc.any():
                y[acc, k] += dy[acc]
                h[acc] += dy[acc, None] * W[k][None, :]
                E[acc] += dE[acc]
        if E.min() < best_E:
            best_E, best_y = E.min(), y[E.argmin()].copy()
    return best_y, best_E


# ------------------------------------------------------------------ exact schedule scoring (fast, cached)
class Scorer:
    """Exact day cost (startup + no-load + dispatch energy) and rule-violation count, same rules as check.py."""

    def __init__(self, plants, demand, reserve):
        self.plants, self.demand, self.reserve = plants, demand, reserve
        self.start = np.array([int(p["on_at_start"]) for p in plants])
        self.su = np.array([p["startup_cost"] for p in plants])
        self.cache = {}

    def hour(self, t, on):
        key = (t, on)
        if key not in self.cache:
            out, short = dispatch_hour(self.plants, self.demand[t], on)
            cap = sum(p["pmax_mw"] * u for p, u in zip(self.plants, on))
            bad = int(short > 1e-6) + int(short < -1e-6) + int(cap < self.demand[t] + self.reserve[t] - 1e-6)
            cost = sum(p["no_load_cost_per_h"] + p["marginal_cost_per_mwh"] * mw
                       for p, u, mw in zip(self.plants, on, out) if u)
            self.cache[key] = (bad, cost)
        return self.cache[key]

    def __call__(self, s):
        s = np.asarray(s, dtype=int)
        bad, cost = 0, 0.0
        for t in range(len(s)):
            b, c = self.hour(t, tuple(s[t]))
            bad += b
            cost += c
        prev = np.vstack([self.start, s[:-1]])
        cost += float((self.su * (s * (1 - prev))).sum())
        for i, p in enumerate(self.plants):                         # min up / min down (check.py's rule)
            pv, since = self.start[i], None
            for t in range(len(s)):
                if s[t, i] != pv:
                    if since is not None:
                        held = t - since
                        bad += int(pv == 1 and held < p["min_up_h"]) + int(pv == 0 and held < p["min_down_h"])
                    pv, since = s[t, i], t
        return bad, cost


def polish(s, score, max_rounds=60):
    """Local search over whole schedules: set a run of hours of one plant on or off; keep the best
    improvement in (rules broken, cost). Repairs broken rules first, then lowers cost."""
    s = np.array(s, dtype=int)
    T, n = s.shape
    lengths = sorted({1, 2, 3, 4, 5, 6, 8, 12, T})
    cur = score(s)
    for _ in range(max_rounds):
        best, best_s = cur, None
        for i in range(n):
            for t0 in range(T):
                for L in lengths:
                    t1 = min(T, t0 + L)
                    for val in (0, 1):
                        if (s[t0:t1, i] == val).all():
                            continue
                        cand = s.copy()
                        cand[t0:t1, i] = val
                        k = score(cand)
                        if k < best:
                            best, best_s = k, cand
        if best_s is None:
            break
        s, cur = best_s, best
    return s


# ------------------------------------------------------------------ main
def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plants", default=here / "data" / "plants.csv", help="plants CSV (default: data/plants.csv)")
    ap.add_argument("--demand", default=here / "data" / "demand.csv", help="demand CSV (default: data/demand.csv)")
    ap.add_argument("--horizon", type=int, default=None, help="only the first H hours (default: all)")
    ap.add_argument("--solver", choices=["anneal", "qaoa", "none"], default="anneal",
                    help="anneal (default), qaoa (small QUBOs only), or none (build + check the QUBO only)")
    ap.add_argument("--anneal-mode", choices=["x", "full"], default="x",
                    help="x (default): flip on/off bits, helper bits follow at their optimum; "
                         "full: flip any of the QUBO's bits one at a time (gets stuck: see docs)")
    ap.add_argument("--sweeps", type=int, default=300, help="annealing sweeps (default 300)")
    ap.add_argument("--chains", type=int, default=8, help="annealing runs (default 8)")
    ap.add_argument("--seed", type=int, default=7, help="random seed (default 7)")
    ap.add_argument("--p", type=int, default=1, help="QAOA layers (default 1)")
    ap.add_argument("--shots", type=int, default=1000, help="QAOA samples (default 1000)")
    ap.add_argument("--max-sim-qubits", type=int, default=20, help="largest QUBO QAOA will simulate (default 20)")
    ap.add_argument("--block-mw", type=float, default=None, help="capacity block in MW (default: gcd of pmax values)")
    ap.add_argument("--penalty-scale", type=float, default=1.0, help="multiply all penalty weights (default 1)")
    ap.add_argument("--no-polish", action="store_true", help="report the solver's schedule without local search")
    ap.add_argument("--no-milp", action="store_true", help="skip the MILP comparison")
    ap.add_argument("--save-qubo", help="write the QUBO to this JSON file (names, linear, quadratic, offset)")
    ap.add_argument("--out", help="write the schedule to this CSV")
    a = ap.parse_args()

    plants = load_plants(a.plants)
    demand, reserve = load_demand(a.demand)
    if a.horizon:
        demand, reserve = demand[: a.horizon], reserve[: a.horizon]
    n, T = len(plants), len(demand)
    names = [p["plant_id"] for p in plants]
    block = a.block_mw or default_block(plants)

    t0 = time.perf_counter()
    qb, info = build_day_qubo(plants, demand, reserve, block, a.penalty_scale)
    Q, offset = qb.matrix()
    N = len(Q)
    kinds = {k: qb.kind.count(k) for k in ("x", "v", "s", "slack")}
    n_pairs = int((np.triu(Q, 1) != 0).sum())
    w = info["weights"]
    print(f"{n} plants x {T} hours as one QUBO: {N} qubits "
          f"({kinds['x']} on/off, {kinds['v']} start, {kinds['s']} stop, {kinds['slack']} slack), "
          f"{n_pairs} pair terms (= two-qubit gates per QAOA layer); built in {time.perf_counter() - t0:.1f} s")
    print(f"block {block:g} MW; penalty weights: capacity A={w['A']:,.0f}, links B={w['B']:,.0f}, "
          f"min up/down C={w['C']:,.0f}")

    if a.save_qubo:
        Path(a.save_qubo).write_text(json.dumps({
            "names": qb.names, "offset": offset,
            "linear": {qb.names[k]: v for k, v in qb.lin.items() if v},
            "quadratic": [[qb.names[k], qb.names[l], v] for (k, l), v in qb.quad.items() if v]}))
        print(f"QUBO written to {a.save_qubo}")

    score = Scorer(plants, demand, reserve)
    milp_cost, milp_sched = None, None
    if not a.no_milp:
        try:
            milp_cost, milp_sched, _, milp_secs = solve_milp(plants, demand, reserve)
            y_m = encode(milp_sched, info, N)
            print(f"MILP optimum ${milp_cost:,.0f} ({milp_secs:.3f} s). Its QUBO energy: "
                  f"{qubo_energy(Q, offset, y_m):,.0f}  (penalties should be 0 for a valid schedule)")
        except RuntimeError as e:
            print(f"MILP: {e}")

    if a.solver == "none":
        return

    t0 = time.perf_counter()
    if a.solver == "anneal":
        scale = info["c"].max() + max(p["startup_cost"] for p in plants)
        if a.anneal_mode == "x":
            xe = XEnergy(plants, info, T)
            raw, E = anneal_x(xe, a.sweeps, a.chains, a.seed, t_hot=scale, t_cold=1.0)
            E = qubo_energy(Q, offset, encode(raw, info, N))          # same number, from the full QUBO
            how = f"simulated annealing on the on/off bits ({a.chains} runs x {a.sweeps} sweeps)"
        else:
            y, E = anneal(Q, offset, a.sweeps, a.chains, a.seed, t_hot=2 * scale, t_cold=0.5)
            how = f"simulated annealing on all {N} bits ({a.chains} runs x {a.sweeps} sweeps)"
            raw = decode(y, info, T, n)
    else:
        if N > a.max_sim_qubits:
            print(f"\nQAOA: this QUBO needs {N} qubits. Simulating that takes a 2^{N} statevector, which no "
                  f"computer can hold, and no quantum computer today runs {N} high-quality qubits with "
                  f"{n_pairs} two-qubit gates per layer.\nUse --horizon to shrink it (e.g. --horizon 1), "
                  f"or --solver anneal for the full day.")
            sys.exit(2)
        from run_qaoa_schedule import QAOA  # pyright: ignore[reportMissingImports]  (same folder; same circuit)
        qa = QAOA(N)
        angles, probs, _ = qa.run(Q, offset, p=a.p)
        rng = np.random.default_rng(a.seed)
        samples = rng.choice(len(probs), size=a.shots, p=probs / probs.sum())
        cands = {tuple(map(tuple, decode(qa.bits[k], info, T, n))) for k in np.unique(samples)}
        raw = min((np.array(c) for c in cands), key=score)
        y = encode(raw, info, N)
        E = qubo_energy(Q, offset, y)
        best_k = int(np.argmin(qa.energies(Q, offset)))
        how = f"QAOA p={a.p}, {a.shots} shots (P(QUBO minimum) = {probs[best_k]:.3f})"
    secs = time.perf_counter() - t0

    bad_raw, cost_raw = score(raw)
    print(f"\nSolver: {how}, {secs:.1f} s. Best QUBO energy {E:,.0f}")
    print(f"  its schedule: ${cost_raw:,.0f}, {bad_raw} rule(s) broken"
          + (f", gap {100 * (cost_raw - milp_cost) / milp_cost:+.2f}%" if milp_cost else ""))
    final = raw
    if not a.no_polish:
        t1 = time.perf_counter()
        final = polish(raw, score)
        b, cst = score(final)
        print(f"  after local search ({time.perf_counter() - t1:.1f} s): ${cst:,.0f}, {b} rule(s) broken"
              + (f", gap {100 * (cst - milp_cost) / milp_cost:+.2f}%" if milp_cost else ""))

    res = check_schedule(plants, demand, reserve, final, milp_cost=milp_cost, verbose=False)
    print("\nSchedule (1 = on):")
    print("  hour  " + " ".join(f"{nm[:8]:>8}" for nm in names))
    for t in range(T):
        print(f"  {t:>4}  " + " ".join(f"{int(u):>8}" for u in final[t]))
    print(f"\nTotal cost ${res['total_cost']:,.0f}" + (f"   MILP ${milp_cost:,.0f}   gap {res['gap_pct']:+.2f}%"
                                                     if milp_cost else ""))
    violations = list(res["violations"])
    print("All rules satisfied." if not violations else f"{len(violations)} rule(s) broken:")
    for v in violations:
        print("  ", v)

    if a.out:
        with open(a.out, "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["hour"] + names)
            for t in range(T):
                wr.writerow([t] + [int(u) for u in final[t]])
        print(f"Schedule written to {a.out}")


if __name__ == "__main__":
    main()
