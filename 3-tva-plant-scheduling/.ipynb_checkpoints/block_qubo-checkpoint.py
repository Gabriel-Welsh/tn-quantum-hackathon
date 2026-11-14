#!/usr/bin/env python3
"""Unit commitment for the whole day as ONE small QUBO, by grouping hours into K blocks.

Inside a block every plant keeps one on/off state, so the day needs n x K on/off bits instead of n x 24.
The hours are grouped so each block's demand is roughly flat (overnight trough, morning ramp, peak, evening).

Qubit-saving steps, all exact except the grouping itself:
  presolve      fix bits no valid schedule can change: a plant the rest of the fleet can't cover for,
                plants min-down times keep on between two such blocks, and plants whose minimum output
                alone would exceed the block's lowest demand. Fixed bits are constants, not qubits.
  startups      x[i,b] * (1 - x[i,b-1]) is already quadratic: no start helper qubits.
  min up/down   only checked where a block is shorter than the plant's min up / min down time.
                A one-block "island" (0 1 0 or 1 0 1) uses the aux-free term (x[b-1]-x[b])(x[b+1]-x[b]);
                longer reaches use one start (or stop) helper qubit with a Rosenberg link.
  capacity      per block: sum a_i x_i >= r_b. Fixed plants are subtracted, coefficients are capped at the
                remaining need (exact: coefficient tightening), so slack only spans the real spare range.
                Blocks the fixed plants already cover need no constraint (and no slack) at all.
                --capacity unbalanced drops the slack qubits (unbalanced penalization, not exact).
  min output    pairs of plants whose pmin together exceed the block's lowest demand get a pair penalty.

The block schedule is expanded back to hours, scored with check.py, and (unless --no-polish) improved by
classical local search that moves block edges hour by hour. Costs are printed before and after polish, so
the quantum (or annealing) step and the classical step are reported separately.

Two references: the MILP optimum (hours free) and the block MILP (same blocks, exact costs), which
shows what the grouping alone costs.

Usage (run from this folder with the qBraid-SDK environment's Python):
  python block_qubo.py                                   # 5 plants, K=5, exact enumeration of the QUBO
  python block_qubo.py --K 4 --solver qaoa --p 2         # QAOA on the statevector
  python block_qubo.py --plants data/plants10.csv --demand data/demand10.csv --solver anneal
  python block_qubo.py --blocks 0-4,5-10,11-15,16-20,21-23
  python block_qubo.py --selftest                        # check the QUBO against check.py's rules
"""
import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import check_schedule, load_demand, load_plants, solve_milp  # noqa: E402
from run_all_24h_qaoa_schedule import (ONE, QuboBuilder, Scorer, bit, const, default_block,  # noqa: E402
                                       hourly_costs, one_minus, polish)


# ------------------------------------------------------------------ linear-form helpers
def sub(f, g):
    (df, cf), (dg, cg) = f, g
    d = dict(df)
    for k, v in dg.items():
        d[k] = d.get(k, 0.0) - v
    return d, cf - cg


def is_const(f):
    return not f[0]


def product_if_linear(fa, fb):
    """fa * fb as a linear form when one factor is a constant, else None (needs a helper qubit)."""
    if is_const(fa):
        return {k: v * fa[1] for k, v in fb[0].items()}, fa[1] * fb[1]
    if is_const(fb):
        return {k: v * fb[1] for k, v in fa[0].items()}, fa[1] * fb[1]
    return None


# ------------------------------------------------------------------ grouping hours
def parse_blocks(spec, T):
    blocks = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        blocks.append((int(a), int(b or a) + 1))
    if blocks[0][0] != 0 or blocks[-1][1] != T or any(blocks[k][1] != blocks[k + 1][0] for k in range(len(blocks) - 1)):
        sys.exit(f"--blocks must cover hours 0..{T - 1} in order without gaps, e.g. 0-4,5-10,11-23")
    return blocks


def segment_dp(need, K, min_len=1, cuts=None):
    """Best split of hours into K contiguous blocks, minimizing the over-commitment
    sum_b sum_{t in b} (max_{b} need - need_t): every hour must carry its block's peak requirement.
    `cuts` (optional) limits where blocks may start."""
    T = len(need)
    allowed = set(range(T + 1)) if cuts is None else set(cuts) | {0, T}
    waste = lambda s, e: float((need[s:e].max() - need[s:e]).sum())
    INF = float("inf")
    dp = [[INF] * (T + 1) for _ in range(K + 1)]
    arg = [[-1] * (T + 1) for _ in range(K + 1)]
    dp[0][0] = 0.0
    for k in range(1, K + 1):
        for e in range(1, T + 1):
            if e not in allowed:
                continue
            for s in range(0, e - min_len + 1):
                if s in allowed and dp[k - 1][s] < INF:
                    v = dp[k - 1][s] + waste(s, e)
                    if v < dp[k][e]:
                        dp[k][e], arg[k][e] = v, s
    if dp[K][T] == INF:
        sys.exit(f"cannot split {T} hours into {K} blocks with these limits")
    blocks, e = [], T
    for k in range(K, 0, -1):
        s = arg[k][e]
        blocks.append((s, e))
        e = s
    return blocks[::-1]


def plan_cuts(plants, demand, reserve):
    """Hours where the cheapest single-hour fleet changes (run_qaoa_schedule.future_plan)."""
    from run_qaoa_schedule import future_plan  # noqa: E402  (needs qiskit installed)
    plan = future_plan(plants, demand, reserve)
    return [t for t in range(1, len(plan)) if (plan[t] != plan[t - 1]).any()]


def make_blocks(plants, demand, reserve, K, method, spec=None, min_len=2):
    need = demand + reserve
    if spec:
        return parse_blocks(spec, len(need))
    if method == "plan":
        cuts = plan_cuts(plants, demand, reserve)
        if len(cuts) + 1 <= K:
            return segment_dp(need, len(cuts) + 1, 1, cuts)
        return segment_dp(need, K, 1, cuts)
    return segment_dp(need, K, min_len)


# ------------------------------------------------------------------ presolve
def presolve(plants, demand, reserve, blocks, block_mw):
    """Bits that every valid schedule shares. Returns {(i, b): 0/1} and the reasons (for printing)."""
    n, K = len(plants), len(blocks)
    need = demand + reserve
    a = np.array([p["pmax_mw"] / block_mw for p in plants])
    pmin = np.array([p["pmin_mw"] for p in plants])
    r = [math.ceil(need[s:e].max() / block_mw - 1e-9) for s, e in blocks]
    dmin = [demand[s:e].min() for s, e in blocks]
    fixed, why = {}, {}
    # 1. needed: the rest of the fleet (all of it) can't meet the block's requirement
    for b in range(K):
        for i in range(n):
            if a.sum() - a[i] < r[b] - 1e-9:
                fixed[(i, b)], why[(i, b)] = 1, "needed"
    # 2. min down: a plant needed at blocks b1 < b2 (or on at midnight with min_down beyond b2's start)
    #    can't switch off in between when the gap is shorter than min_down.
    changed = True
    while changed:
        changed = False
        for i, p in enumerate(plants):
            on_blocks = [b for b in range(K) if fixed.get((i, b)) == 1]
            anchors = ([-1] if p["on_at_start"] else []) + on_blocks
            for b1, b2 in zip(anchors, anchors[1:]):
                gap_start = 0 if b1 < 0 else blocks[b1][1]
                if blocks[b2][0] - gap_start < p["min_down_h"]:
                    for b in range(b1 + 1, b2):
                        if (i, b) not in fixed:
                            fixed[(i, b)], why[(i, b)], changed = 1, "min down", True
    # 3. min output: a plant whose pmin plus the fixed plants' pmin exceeds the block's lowest demand
    for b in range(K):
        floor = sum(pmin[i] for i in range(n) if fixed.get((i, b)) == 1)
        for i in range(n):
            if (i, b) not in fixed and floor + pmin[i] > dmin[b] + 1e-9:
                fixed[(i, b)], why[(i, b)] = 0, "min output"
    return fixed, why


# ------------------------------------------------------------------ the block QUBO
class BlockQubo:
    def __init__(self, plants, demand, reserve, blocks, block_mw, capacity="slack",
                 penalty_scale=1.0, use_presolve=True, lam=(1.0, 0.1)):
        self.plants, self.demand, self.reserve, self.blocks = plants, demand, reserve, blocks
        n, K = len(plants), len(blocks)
        self.n, self.K = n, K
        L = np.array([e - s for s, e in blocks], dtype=float)
        need = demand + reserve
        c = hourly_costs(plants)
        su = np.array([p["startup_cost"] for p in plants])
        a = np.array([p["pmax_mw"] / block_mw for p in plants])
        pmin = np.array([p["pmin_mw"] for p in plants])
        start = [int(p["on_at_start"]) for p in plants]
        self.fixed, self.why = presolve(plants, demand, reserve, blocks, block_mw) if use_presolve else ({}, {})

        base = L.max() * c.max() + su.max()
        A = 2.0 * base * penalty_scale       # capacity, per block of 50 MW short
        C = 1.0 * base * penalty_scale       # each broken min up / min down requirement, each min-output pair
        qb = QuboBuilder()
        self.qb = qb

        # on/off bits
        self.xvar = {}
        for i, p in enumerate(plants):
            for b in range(K):
                if (i, b) not in self.fixed:
                    self.xvar[(i, b)] = qb.var(f"x[{p['plant_id']},{b}]", "x")

        def xf(i, b):
            if b < 0:
                return const(start[i])
            if (i, b) in self.fixed:
                return const(self.fixed[(i, b)])
            return bit(self.xvar[(i, b)])
        self.xf = xf

        # min up / min down requirements per (plant, block)
        def reach(b, hours):
            return [bb for bb in range(b + 1, K) if blocks[bb][0] < blocks[b][0] + hours]
        reqs = {}
        for i, p in enumerate(plants):
            for b in range(K):
                up = reach(b, p["min_up_h"]) if p["min_up_h"] > 1 else []
                down = reach(b, p["min_down_h"]) if p["min_down_h"] > 1 else []
                reqs[(i, b)] = (up, down)
        wmax = max([len(u) for u, _ in reqs.values()] + [len(d) for _, d in reqs.values()] + [1])
        B = (su.max() + C * wmax) * 1.1      # helper links: cheating must never pay
        self.weights = dict(A=A, B=B, C=C)

        self.aux = []                        # (qubit, form_a, form_b): qubit = a * (1 - b)
        self.island = 0

        def helper(name, fa, fb):
            lin = product_if_linear(fa, one_minus(fb))
            if lin is not None:
                return lin
            z = qb.var(name, "aux")
            for f1, f2, w in [(bit(z), ONE, B), (fa, ONE, B), (fa, fb, -B), (bit(z), fa, -2 * B), (bit(z), fb, 2 * B)]:
                qb.add(f1, f2, w)
            self.aux.append((z, fa, fb))
            return bit(z)

        V = {}
        for i, p in enumerate(plants):
            for b in range(K):
                up, down = reqs[(i, b)]
                cur, prev = xf(i, b), xf(i, b - 1)
                if up and up == down == [b + 1]:
                    qb.add(sub(prev, cur), sub(xf(i, b + 1), cur), C)      # 0 1 0 or 1 0 1 island
                    self.island += 1
                    continue
                if up:
                    V[(i, b)] = helper(f"v[{p['plant_id']},{b}]", cur, prev)
                    for bb in up:
                        qb.add(V[(i, b)], one_minus(xf(i, bb)), C)
                if down:
                    s_form = helper(f"s[{p['plant_id']},{b}]", prev, cur)
                    for bb in down:
                        qb.add(s_form, xf(i, bb), C)

        # cost: hours on x approximate hourly cost, plus startups
        for i, p in enumerate(plants):
            for b in range(K):
                qb.add(xf(i, b), ONE, L[b] * c[i])
                if (i, b) in V:
                    qb.add(V[(i, b)], ONE, su[i])
                else:
                    qb.add(xf(i, b), one_minus(xf(i, b - 1)), su[i])

        # min output pairs
        self.floor_pairs = 0
        for b, (s, e) in enumerate(blocks):
            dmin = demand[s:e].min()
            floor = sum(pmin[i] for i in range(n) if self.fixed.get((i, b)) == 1)
            free = [i for i in range(n) if (i, b) in self.xvar]
            for i in free:                    # (presolve fixes these off; kept for --no-presolve)
                if floor + pmin[i] > dmin + 1e-9:
                    qb.add(xf(i, b), ONE, C)
                    self.floor_pairs += 1
            for x1 in range(len(free)):
                for x2 in range(x1 + 1, len(free)):
                    i, j = free[x1], free[x2]
                    if floor + pmin[i] + pmin[j] > dmin + 1e-9:
                        qb.add(xf(i, b), xf(j, b), C)
                        self.floor_pairs += 1

        # capacity
        self.slack, self.spare_form = [], []
        for b, (s, e) in enumerate(blocks):
            r = math.ceil(need[s:e].max() / block_mw - 1e-9)
            have = sum(a[i] for i in range(n) if self.fixed.get((i, b)) == 1)
            d = r - have
            free = [i for i in range(n) if (i, b) in self.xvar]
            if d <= 1e-9:
                self.slack.append([])
                self.spare_form.append(None)
                continue
            capped = {self.xvar[(i, b)]: min(a[i], d) for i in free}
            spare_form = (capped, -float(d))                              # sum a'_i x_i - d
            self.spare_form.append(spare_form)
            max_spare = sum(capped.values()) - d
            if max_spare < -1e-9:
                print(f"warning: block {b} (hours {s}-{e - 1}) can't meet its requirement even with every plant on.")
            if capacity == "unbalanced":                                  # -l1 h + l2 h^2 (no slack qubits)
                l1, l2 = lam[0] * A, lam[1] * A
                qb.add(spare_form, ONE, -l1)
                qb.add(spare_form, spare_form, l2)
                self.slack.append([])
                continue
            nbits = max(0, int(math.floor(max_spare + 1e-9))).bit_length()
            sig = [qb.var(f"slack[{k},{b}]", "slack") for k in range(nbits)]
            form = (dict(capped), -float(d))
            for k, sk in enumerate(sig):
                form[0][sk] = -(2.0 ** k)
            qb.add(form, form, A)
            self.slack.append(sig)

        self.Q, self.offset = qb.matrix()
        self.N = len(self.Q)
        self.free_keys = sorted(self.xvar, key=self.xvar.get)    # qubit order of the x bits
        self.x_idx = np.array([self.xvar[k] for k in self.free_keys], dtype=int)

    # ---- sizes
    def sizes(self):
        kinds = {k: self.qb.kind.count(k) for k in ("x", "aux", "slack")}
        return dict(qubits=self.N, x=kinds["x"], aux=kinds["aux"], slack=kinds["slack"],
                    fixed=len(self.fixed), island_terms=self.island, floor_pairs=self.floor_pairs,
                    pair_terms=int((np.triu(self.Q, 1) != 0).sum()))

    # ---- encode / decode
    def block_schedule(self, xbits):
        """Block x plant 0/1 array from the free x bits (in qubit order)."""
        S = np.zeros((self.K, self.n), dtype=int)
        for (i, b), v in self.fixed.items():
            S[b, i] = v
        for k, (i, b) in enumerate(self.free_keys):
            S[b, i] = int(xbits[k])
        return S

    def free_bits(self, S):
        return np.array([S[b, i] for (i, b) in self.free_keys], dtype=float)

    def complete(self, X):
        """Full qubit vectors (rows) from free x bits (rows): helpers set to their best values."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        Y = np.zeros((len(X), self.N))
        Y[:, self.x_idx] = X

        def ev(f):
            d, cst = f
            out = np.full(len(X), cst)
            for k, v in d.items():
                out += v * Y[:, k]
            return out
        for z, fa, fb in self.aux:
            Y[:, z] = ev(fa) * (1 - ev(fb))
        for sig, form in zip(self.slack, self.spare_form):
            if sig:
                spare = np.clip(np.round(ev(form)), 0, 2 ** len(sig) - 1).astype(int)
                for k, sk in enumerate(sig):
                    Y[:, sk] = (spare >> k) & 1
        return Y

    def energy(self, Y):
        Y = np.atleast_2d(Y)
        return np.einsum("mi,ij,mj->m", Y, self.Q, Y) + self.offset

    def xenergy(self, X):
        """QUBO energy with the helper bits at their optimum: a function of the on/off bits alone."""
        return self.energy(self.complete(X))

    def hours(self, S):
        """Expand a block schedule to hours x plants."""
        return np.vstack([np.tile(S[b], (e - s, 1)) for b, (s, e) in enumerate(self.blocks)])

    def save(self, path):
        qb = self.qb
        Path(path).write_text(json.dumps({
            "names": qb.names, "offset": self.offset, "blocks": self.blocks,
            "linear": {qb.names[k]: v for k, v in qb.lin.items() if v},
            "quadratic": [[qb.names[k], qb.names[l], v] for (k, l), v in qb.quad.items() if v]}))


# ------------------------------------------------------------------ solvers (all minimize xenergy)
def solve_exact(bq, chunk=1 << 15):
    F = len(bq.x_idx)
    best_E, best_x = np.inf, None
    for lo in range(0, 2 ** F, chunk):
        idx = np.arange(lo, min(2 ** F, lo + chunk))
        X = (idx[:, None] >> np.arange(F)) & 1
        E = bq.xenergy(X)
        k = int(E.argmin())
        if E[k] < best_E:
            best_E, best_x = float(E[k]), X[k].copy()
    return best_x, best_E, {}


def solve_anneal(bq, sweeps=400, chains=8, seed=7):
    """Annealing over the on/off bits (helpers at their optimum). Moves: one plant, a run of 1..K blocks."""
    rng = np.random.default_rng(seed)
    keys = bq.free_keys
    pos = {k: j for j, k in enumerate(keys)}
    F = len(keys)
    if F == 0:
        return np.zeros(0), float(bq.xenergy(np.zeros((1, 0)))[0]), {}
    scale = bq.weights["C"]
    temps = np.geomspace(scale, scale * 1e-4, sweeps)
    best_E, best_x = np.inf, None
    for _ in range(chains):
        x = rng.integers(0, 2, F).astype(float)
        E = float(bq.xenergy(x)[0])
        for temp in temps:
            for _ in range(F):
                i, b0 = keys[rng.integers(F)]
                run = [pos[(i, b)] for b in range(b0, min(bq.K, b0 + int(rng.integers(1, bq.K + 1))))
                       if (i, b) in pos]
                val = 1.0 - x[pos[(i, b0)]]
                old = x[run].copy()
                x[run] = val
                E_new = float(bq.xenergy(x)[0])
                dE = E_new - E
                if dE <= 0 or rng.random() < math.exp(-dE / temp):
                    E = E_new
                    if E < best_E:
                        best_E, best_x = E, x.copy()
                else:
                    x[run] = old
    return best_x, best_E, dict(sweeps=sweeps, chains=chains)


def solve_sampled(bq, probs, shots, seed):
    """Sample whole qubit strings, keep their on/off bits, re-set the helpers, take the lowest energy."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(probs), size=shots, p=probs / probs.sum())
    bits = (np.unique(idx)[:, None] >> np.arange(bq.N)) & 1
    X = np.unique(bits[:, bq.x_idx], axis=0)
    E = bq.xenergy(X)
    k = int(E.argmin())
    return X[k], float(E[k])


def solve_qaoa(bq, p=1, shots=1000, seed=7, maxiter=100):
    from run_qaoa_schedule import QAOA  # noqa: E402  (needs qiskit)
    qa = QAOA(bq.N)
    t0 = time.perf_counter()
    angles, probs, measured = qa.run(bq.Q, bq.offset, p=p, maxiter=maxiter)
    tune = time.perf_counter() - t0
    x, E = solve_sampled(bq, probs, shots, seed)
    Eall = qa.energies(bq.Q, bq.offset)
    p_gs = float(probs[np.isclose(Eall, Eall.min())].sum())
    two_q = sum(1 for g in measured.data if g.operation.num_qubits == 2)
    return x, E, dict(p=p, shots=shots, tune_s=tune, p_ground=p_gs, two_qubit_gates=two_q,
                      depth=measured.depth(), angles=list(map(float, angles)))


def solve_random(bq, shots=1000, seed=7):
    return solve_sampled(bq, np.ones(2 ** bq.N), shots, seed) + ({"shots": shots},)


# ------------------------------------------------------------------ block MILP: exact costs, same blocks
def solve_block_milp(plants, demand, reserve, blocks):
    """check.solve_milp's formulation plus u[i,t] = u[i,start of t's block]: the best the grouping allows."""
    n, T = len(plants), len(demand)
    U = lambda i, t: i * T + t
    Vv = lambda i, t: n * T + i * T + t
    P = lambda i, t: 2 * n * T + i * T + t
    cost = np.zeros(3 * n * T)
    for i, p in enumerate(plants):
        for t in range(T):
            cost[U(i, t)], cost[Vv(i, t)], cost[P(i, t)] = (p["no_load_cost_per_h"], p["startup_cost"],
                                                           p["marginal_cost_per_mwh"])
    rows, lo, hi = [], [], []

    def add(terms, low, high):
        rows.append(terms); lo.append(low); hi.append(high)
    for t in range(T):
        add([(P(i, t), 1) for i in range(n)], demand[t], demand[t])
        add([(U(i, t), p["pmax_mw"]) for i, p in enumerate(plants)], demand[t] + reserve[t], np.inf)
    for i, p in enumerate(plants):
        up, down, u0 = int(p["min_up_h"]), int(p["min_down_h"]), int(p["on_at_start"])
        for t in range(T):
            add([(P(i, t), 1), (U(i, t), -p["pmin_mw"])], 0, np.inf)
            add([(P(i, t), 1), (U(i, t), -p["pmax_mw"])], -np.inf, 0)
            before = [(U(i, t - 1), 1)] if t > 0 else []
            add([(Vv(i, t), 1), (U(i, t), -1)] + before, -u0 if t == 0 else 0, np.inf)
            add([(Vv(i, s), 1) for s in range(max(0, t - up + 1), t + 1)] + [(U(i, t), -1)], -np.inf, 0)
            window = [(Vv(i, s), 1) for s in range(max(0, t - down + 1), t + 1)]
            if t - down >= 0:
                add(window + [(U(i, t - down), 1)], -np.inf, 1)
            else:
                add(window, -np.inf, 1 - u0)
        for s, e in blocks:
            for t in range(s + 1, e):
                add([(U(i, t), 1), (U(i, s), -1)], 0, 0)
    A = lil_matrix((len(rows), 3 * n * T))
    for k, terms in enumerate(rows):
        for j, v in terms:
            A[k, j] += v
    integrality = np.r_[np.ones(2 * n * T), np.zeros(n * T)]
    upper = np.r_[np.ones(2 * n * T), [p["pmax_mw"] for p in plants for _ in range(T)]]
    t0 = time.perf_counter()
    res = milp(cost, constraints=LinearConstraint(A.tocsr(), lo, hi), integrality=integrality,
               bounds=Bounds(0, upper))
    secs = time.perf_counter() - t0
    if res.x is None:
        return None, None, secs
    sched = np.array([[round(res.x[U(i, t)]) for i in range(n)] for t in range(T)])
    return res.fun, sched, secs


# ------------------------------------------------------------------ self test
def selftest(plants, demand, reserve, blocks, block_mw, samples=4000, seed=0):
    """For many block schedules: penalty part of the QUBO == 0  <=>  check.py finds no broken rule
    (min up/down, reserve, and min output for pairs). Also: the cost part == block cost formula."""
    bq = BlockQubo(plants, demand, reserve, blocks, block_mw, use_presolve=False)
    bq0 = BlockQubo(plants, demand, reserve, blocks, block_mw, use_presolve=False, penalty_scale=0.0)
    rng = np.random.default_rng(seed)
    F = len(bq.x_idx)
    if 2 ** F <= max(samples, 1 << 16):
        X = (np.arange(2 ** F)[:, None] >> np.arange(F)) & 1
    else:
        X = rng.integers(0, 2, size=(samples, F))
        _, sched, _ = solve_block_milp(plants, demand, reserve, blocks)   # a valid schedule, then flip 1-3 bits
        if sched is not None:
            x0 = bq.free_bits(np.array([sched[s] for s, _ in blocks]))
            near = np.tile(x0.astype(int), (samples, 1))
            for row in near:
                row[rng.choice(F, size=rng.integers(0, 4), replace=False)] ^= 1
            X = np.vstack([X, near])
    E, E0 = bq.xenergy(X), bq0.xenergy(X)
    pen = E - E0
    bad_rules = ("min up broken", "min down broken", "reserve not met")
    mismatches, n_valid = 0, 0
    for k in range(len(X)):
        S = bq.block_schedule(X[k])
        res = check_schedule(plants, demand, reserve, bq.hours(S), verbose=False)
        rule_ok = not any(v[2] in bad_rules for v in res["violations"])
        # pairs only: triples of min outputs aren't in the QUBO, so ignore schedules where only a triple breaks it
        floor_ok = all(pair_floor_ok(plants, demand, s, e, S[b]) for b, (s, e) in enumerate(blocks))
        ok = rule_ok and floor_ok
        n_valid += ok
        if ok != (pen[k] < 1e-6):
            mismatches += 1
            if mismatches <= 5:
                print("  mismatch:", S.tolist(), "penalty", pen[k], "check.py:", res["violations"][:3])
    print(f"selftest: {len(X)} schedules ({n_valid} follow the rules), {mismatches} mismatches")
    return mismatches == 0


def pair_floor_ok(plants, demand, s, e, on):
    """True unless two plants (or one) that are on have pmin summing above the block's lowest demand."""
    dmin = demand[s:e].min()
    idx = [i for i, u in enumerate(on) if u]
    pm = [plants[i]["pmin_mw"] for i in idx]
    return all(pm[x] <= dmin + 1e-9 for x in range(len(pm))) and \
        all(pm[x] + pm[y] <= dmin + 1e-9 for x in range(len(pm)) for y in range(x + 1, len(pm)))


# ------------------------------------------------------------------ main
def run(plants, demand, reserve, blocks, block_mw, solver="exact", capacity="slack", penalty_scale=1.0,
        use_presolve=True, do_polish=True, p=1, shots=1000, seed=7, sweeps=400, chains=8, maxiter=100,
        max_exact=24, max_qaoa=22, milp_ref=True, verbose=True):
    """Build, solve, expand, polish. Returns a dict of results (used by the scaling study too)."""
    out = dict(n=len(plants), K=len(blocks), blocks=blocks, solver=solver, capacity=capacity)
    t0 = time.perf_counter()
    bq = BlockQubo(plants, demand, reserve, blocks, block_mw, capacity, penalty_scale, use_presolve)
    out["build_s"] = time.perf_counter() - t0
    out.update(bq.sizes())
    if verbose:
        sz = bq.sizes()
        print(f"{bq.n} plants, {bq.K} blocks: " + ", ".join(f"{s}-{e - 1}" for s, e in blocks))
        print(f"QUBO: {sz['qubits']} qubits ({sz['x']} on/off, {sz['aux']} helper, {sz['slack']} slack); "
              f"{sz['fixed']} bits fixed by presolve; {sz['island_terms']} aux-free island terms, "
              f"{sz['floor_pairs']} min-output pairs; {sz['pair_terms']} pair terms (ZZ gates per QAOA layer)")
        w = bq.weights
        print(f"penalty weights: capacity A={w['A']:,.0f}, min up/down C={w['C']:,.0f}, links B={w['B']:,.0f}")

    if milp_ref:
        out["milp_cost"], _, _, out["milp_s"] = solve_milp(plants, demand, reserve)
        out["block_milp_cost"], _, out["block_milp_s"] = solve_block_milp(plants, demand, reserve, blocks)
    milp_cost = out.get("milp_cost")
    gap = lambda c: None if milp_cost is None else 100 * (c - milp_cost) / milp_cost

    t0 = time.perf_counter()
    F = len(bq.x_idx)
    if solver == "exact":
        if F > max_exact:
            sys.exit(f"exact: {F} on/off bits = 2^{F} schedules; too many (limit {max_exact}). Use --solver anneal.")
        x, E, info = solve_exact(bq)
    elif solver == "anneal":
        x, E, info = solve_anneal(bq, sweeps, chains, seed)
    elif solver in ("qaoa", "random"):
        if bq.N > max_qaoa:
            sys.exit(f"{solver}: {bq.N} qubits is too many to simulate here (limit {max_qaoa}). "
                     f"Use fewer blocks (--K) or --solver anneal.")
        x, E, info = solve_qaoa(bq, p, shots, seed, maxiter) if solver == "qaoa" else solve_random(bq, shots, seed)
    else:
        sys.exit(f"unknown solver {solver}")
    out["solve_s"] = time.perf_counter() - t0
    out["energy"], out["info"] = E, info

    S = bq.block_schedule(x)
    raw = bq.hours(S)
    score = Scorer(plants, demand, reserve)
    r0 = check_schedule(plants, demand, reserve, raw, milp_cost=milp_cost, verbose=False)
    out.update(raw_cost=r0["total_cost"], raw_broken=len(r0["violations"]), raw_gap=gap(r0["total_cost"]))
    final = raw
    if do_polish:
        t0 = time.perf_counter()
        final = polish(raw, score)
        out["polish_s"] = time.perf_counter() - t0
    r1 = check_schedule(plants, demand, reserve, final, milp_cost=milp_cost, verbose=False)
    out.update(cost=r1["total_cost"], broken=len(r1["violations"]), gap=gap(r1["total_cost"]),
               schedule=final, violations=r1["violations"])

    if verbose:
        extra = ""
        if solver == "qaoa":
            extra = (f" (p={p}, {shots} shots, P(ground state)={info['p_ground']:.3f}, "
                     f"{info['two_qubit_gates']} two-qubit gates, angle tuning {info['tune_s']:.1f} s)")
        print(f"\nSolver {solver}{extra}: {out['solve_s']:.2f} s, QUBO energy {E:,.0f}")
        if milp_cost is not None:
            bm = out["block_milp_cost"]
            print(f"MILP optimum          ${milp_cost:>10,.0f}  ({out['milp_s']:.3f} s)")
            if bm is not None:
                print(f"block MILP (same blocks) ${bm:>7,.0f}  gap {gap(bm):+.2f}%  <- what the grouping alone costs")
        print(f"QUBO schedule          ${out['raw_cost']:>10,.0f}  gap {_g(out['raw_gap'])}  "
              f"{out['raw_broken']} rule(s) broken")
        if do_polish:
            print(f"after local search     ${out['cost']:>10,.0f}  gap {_g(out['gap'])}  "
                  f"{out['broken']} rule(s) broken  ({out['polish_s']:.1f} s)")
        names = [p_["plant_id"] for p_ in plants]
        print("\nBlock schedule from the QUBO (1 = on):")
        print("  hours  " + " ".join(f"{nm[:8]:>8}" for nm in names))
        for b, (s, e) in enumerate(blocks):
            print(f"  {s:>2}-{e - 1:<3} " + " ".join(f"{int(u):>8}" for u in S[b]))
        for v in r1["violations"]:
            print("  broken:", v)
    return out


def _g(x):
    return "   n/a" if x is None else f"{x:+.2f}%"


def refine(plants, demand, reserve, blocks, block_mw, K, rounds, verbose=True, **kw):
    """Coarse-to-fine: solve, then put the block edges at the hours where the (polished) schedule switches,
    keeping at most K blocks, and solve again. Uses no MILP information. Returns the best round's result,
    with the per-round history in res["rounds"]."""
    need = demand + reserve
    best, history, seen = None, [], set()
    for rnd in range(rounds + 1):
        if verbose:
            print(f"\n=== round {rnd} ===")
        res = run(plants, demand, reserve, blocks, block_mw, verbose=verbose, **kw)
        total_s = res["build_s"] + res["solve_s"] + res.get("polish_s", 0.0)
        history.append(dict(round=rnd, blocks=blocks, qubits=res["qubits"], cost=res["cost"], gap=res["gap"],
                            broken=res["broken"], seconds=total_s))
        if best is None or (res["broken"], res["cost"]) < (best["broken"], best["cost"]):
            best = res
        seen.add(tuple(blocks))
        s = best["schedule"]
        cuts = [t for t in range(1, len(s)) if (s[t] != s[t - 1]).any()]
        new = segment_dp(need, min(K, len(cuts) + 1), 1, cuts)
        if tuple(new) in seen:
            break
        blocks = new
    best["rounds"] = history
    if verbose:
        print("\nRefinement summary:")
        for h in history:
            print(f"  round {h['round']}: {len(h['blocks'])} blocks, {h['qubits']:>3} qubits, "
                  f"${h['cost']:,.0f}  gap {_g(h['gap'])}  {h['broken']} broken  ({h['seconds']:.1f} s)  "
                  + ",".join(f"{a}-{b - 1}" for a, b in h["blocks"]))
    return best


def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plants", default=here / "data" / "plants.csv")
    ap.add_argument("--demand", default=here / "data" / "demand.csv")
    ap.add_argument("--K", type=int, default=5, help="number of blocks (default 5)")
    ap.add_argument("--segment", choices=["dp", "plan"], default="dp",
                    help="dp (default): flattest demand per block; plan: cut where the cheapest fleet changes")
    ap.add_argument("--min-len", type=int, default=2, help="shortest block in hours for --segment dp (default 2)")
    ap.add_argument("--blocks", help="explicit blocks, e.g. 0-4,5-10,11-15,16-20,21-23 (overrides --K)")
    ap.add_argument("--solver", choices=["exact", "anneal", "qaoa", "random"], default="exact")
    ap.add_argument("--capacity", choices=["slack", "unbalanced"], default="slack")
    ap.add_argument("--penalty-scale", type=float, default=1.0)
    ap.add_argument("--no-presolve", action="store_true")
    ap.add_argument("--no-polish", action="store_true")
    ap.add_argument("--p", type=int, default=1)
    ap.add_argument("--shots", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--sweeps", type=int, default=400)
    ap.add_argument("--chains", type=int, default=8)
    ap.add_argument("--maxiter", type=int, default=100, help="COBYLA iterations for QAOA angles")
    ap.add_argument("--max-qaoa", type=int, default=22, help="largest QUBO to simulate with QAOA")
    ap.add_argument("--block-mw", type=float, default=None)
    ap.add_argument("--no-milp", action="store_true")
    ap.add_argument("--save-qubo")
    ap.add_argument("--out", help="write the hourly schedule to this CSV")
    ap.add_argument("--refine", type=int, default=0,
                    help="rounds of re-blocking: cut blocks where the last schedule switches, solve again (default 0)")
    ap.add_argument("--selftest", action="store_true", help="check QUBO penalties against check.py, then exit")
    a = ap.parse_args()

    plants = load_plants(a.plants)
    demand, reserve = load_demand(a.demand)
    block_mw = a.block_mw or default_block(plants)
    blocks = make_blocks(plants, demand, reserve, a.K, a.segment, a.blocks, a.min_len)

    if a.selftest:
        ok = selftest(plants, demand, reserve, blocks, block_mw)
        sys.exit(0 if ok else 1)
    if a.save_qubo:
        BlockQubo(plants, demand, reserve, blocks, block_mw, a.capacity, a.penalty_scale,
                  not a.no_presolve).save(a.save_qubo)
        print(f"QUBO written to {a.save_qubo}")

    kw = dict(solver=a.solver, capacity=a.capacity, penalty_scale=a.penalty_scale, use_presolve=not a.no_presolve,
              do_polish=not a.no_polish, p=a.p, shots=a.shots, seed=a.seed, sweeps=a.sweeps, chains=a.chains,
              maxiter=a.maxiter, max_qaoa=a.max_qaoa, milp_ref=not a.no_milp)
    if a.refine:
        res = refine(plants, demand, reserve, blocks, block_mw, a.K, a.refine, **kw)
    else:
        res = run(plants, demand, reserve, blocks, block_mw, **kw)
    if a.out:
        with open(a.out, "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["hour"] + [p["plant_id"] for p in plants])
            for t, row in enumerate(res["schedule"]):
                wr.writerow([t] + [int(u) for u in row])
        print(f"Schedule written to {a.out}")


if __name__ == "__main__":
    main()
