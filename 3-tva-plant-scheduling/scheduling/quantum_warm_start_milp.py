#!/usr/bin/env python3
"""Quantum warm start for the unit-commitment MILP (standalone: needs no other script in this folder).

Idea in one sentence: a quantum algorithm (QAOA) proposes a good on/off schedule, we make it obey every
rule, and hand it to the classical MILP solver (HiGHS) as its starting solution, so the solver begins
branch-and-bound with a good answer already in hand and can throw away more of its search tree.

Pipeline
  1. Read plants + demand (CSV).
  2. Build the exact MILP (on/off u, startup v, output p for every plant and hour).
  3. Group the 24 hours into K blocks of similar demand. One on/off bit per plant per block
     -> plants x K qubits instead of plants x 24.
  4. Write the commitment problem as a QUBO (cost + penalties, all in 0/1 bits).
  5. Solve the QUBO: QAOA (simulated statevector, sampled with a Qiskit circuit), or simulated annealing
     when there are too many qubits to simulate, or brute force for checking.
  6. Repair the best samples so they obey every rule, and add the cheapest dispatch -> a full MILP solution.
  7. Run HiGHS twice: cold (no start) and warm (with the quantum start). Compare time, nodes, gap.

Usage (qBraid-SDK kernel's Python; needs numpy, scipy, highspy, optionally qiskit + qiskit-aer):
  python scheduling/quantum_warm_start_milp.py                                # 5 plants, QAOA, 20 qubits
  python scheduling/quantum_warm_start_milp.py --blocks 3 --p 3               # fewer qubits, deeper circuit
  python scheduling/quantum_warm_start_milp.py --plants data/plants10.csv --demand data/demand10.csv --blocks 2
  python scheduling/quantum_warm_start_milp.py --copies 8 --solver anneal     # 40 plants, 160-bit QUBO (bigger MILP)
  python scheduling/quantum_warm_start_milp.py --selftest                     # check the pieces against each other
  python scheduling/quantum_warm_start_milp.py --sampler qbraid --p 1 --shots 1000            # free qBraid cloud simulator
  python scheduling/quantum_warm_start_milp.py --sampler qbraid --device aws:ionq:qpu:forte-1 --p 1 --shots 200 \
         --max-credits 1700                                        # real IonQ QPU, ~1,630 credits (~$16)
"""
import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

# The QAOA simulation multiplies many small (32 x 32) matrices; multi-threaded BLAS only adds overhead
# there (and is badly hurt on a busy shared machine). Must be set before numpy is imported.
for _var in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np
from scipy.optimize import minimize
from scipy.sparse import csc_matrix, csr_matrix

HIGHSPY_REQUIREMENT = "highspy>=1.16"     # the HiGHS MILP solver's Python API (tested with 1.16.0)


def ensure_highspy():
    """Import highspy, installing it first into the running Python environment if it is missing.

    qBraid's qBraid-SDK environment doesn't ship highspy, so a fresh kernel or Lab instance needs it once.
    The install goes into the same environment as this Python (`sys.executable -m pip`), so the notebook
    kernel, the command line and the web app each get it where they run. If the install fails (no network,
    or an externally managed system Python), raises ImportError with the command to run by hand.
    Set QWS_NO_AUTO_INSTALL=1 to turn the automatic install off.
    """
    import importlib
    try:
        return importlib.import_module("highspy")
    except ImportError:
        pass
    how = f'{sys.executable} -m pip install "{HIGHSPY_REQUIREMENT}"'
    if os.environ.get("QWS_NO_AUTO_INSTALL") != "1":
        import subprocess
        print(f"highspy (the HiGHS MILP solver) is not installed in this environment; installing it:\n  {how}",
              file=sys.stderr, flush=True)
        done = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", HIGHSPY_REQUIREMENT])
        if done.returncode == 0:
            importlib.invalidate_caches()
            try:
                return importlib.import_module("highspy")
            except ImportError:
                pass
    raise ImportError("This code needs highspy (the HiGHS Python API), and it could not be installed "
                      f"automatically. Install it into this environment, then restart the kernel:\n  {how}")


try:
    highspy = ensure_highspy()
except ImportError as _err:
    if __name__ == "__main__":
        sys.exit(str(_err))
    raise

HERE = Path(__file__).resolve().parent.parent


# =====================================================================================================
# 1. Data
# =====================================================================================================
def load_plants(path):
    """Plants as a list of dicts with float fields (plant_id stays a string)."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    keep = ["pmin_mw", "pmax_mw", "marginal_cost_per_mwh", "no_load_cost_per_h", "startup_cost",
            "min_up_h", "min_down_h", "on_at_start"]
    return [{"plant_id": r["plant_id"], **{k: float(r[k]) for k in keep}} for r in rows]


def load_demand(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return (np.array([float(r["demand_mw"]) for r in rows]),
            np.array([float(r["reserve_mw"]) for r in rows]))


def bigger_fleet(plants, demand, reserve, copies, seed=0):
    """`copies` copies of every plant (costs jittered +-8% so copies differ), demand x copies.

    Many near-identical plants give branch-and-bound lots of equally good branches, which is where a good
    starting solution should help most (with this data HiGHS still closes the gap at the root node, even for
    copies=8; the bigger model mainly costs more LP time).
    """
    if copies <= 1:
        return plants, demand, reserve
    rng = np.random.default_rng(seed)
    fleet = []
    for c in range(copies):
        for p in plants:
            q = dict(p)
            q["plant_id"] = f"{p['plant_id']}_{c + 1}"
            for k in ("marginal_cost_per_mwh", "no_load_cost_per_h", "startup_cost"):
                q[k] = round(p[k] * rng.uniform(0.92, 1.08), 2)
            fleet.append(q)
    return fleet, demand * copies, reserve * copies


# =====================================================================================================
# 2. The exact MILP
# =====================================================================================================
class Milp:
    """The unit-commitment MILP, stored as   min c.x   s.t.  row_lo <= A x <= row_hi,  lb <= x <= ub.

    Variables, for plant i and hour t:  u (1 = on), v (1 = started this hour), p (MW produced).
    Rules: output = demand, on-capacity >= demand + reserve, pmin*u <= p <= pmax*u, startup logic,
    minimum up and down times.
    """

    def __init__(self, plants, demand, reserve):
        self.plants, self.demand, self.reserve = plants, demand, reserve
        n, T = self.n, self.T = len(plants), len(demand)
        self.N = 3 * n * T
        c = np.zeros(self.N)
        for i, p in enumerate(plants):
            for t in range(T):
                c[self.U(i, t)] = p["no_load_cost_per_h"]
                c[self.V(i, t)] = p["startup_cost"]
                c[self.P(i, t)] = p["marginal_cost_per_mwh"]
        rows, lo, hi, names = [], [], [], []

        def add(terms, low, high, name):
            rows.append(terms), lo.append(low), hi.append(high), names.append(name)

        for t in range(T):
            add([(self.P(i, t), 1) for i in range(n)], demand[t], demand[t], f"demand h{t}")
            add([(self.U(i, t), p["pmax_mw"]) for i, p in enumerate(plants)], demand[t] + reserve[t],
                np.inf, f"reserve h{t}")
        for i, p in enumerate(plants):
            up, down, u0 = int(p["min_up_h"]), int(p["min_down_h"]), int(p["on_at_start"])
            nm = p["plant_id"]
            for t in range(T):
                add([(self.P(i, t), 1), (self.U(i, t), -p["pmin_mw"])], 0, np.inf, f"pmin {nm} h{t}")
                add([(self.P(i, t), 1), (self.U(i, t), -p["pmax_mw"])], -np.inf, 0, f"pmax {nm} h{t}")
                prev = [(self.U(i, t - 1), 1)] if t > 0 else []                  # v_t >= u_t - u_(t-1)
                add([(self.V(i, t), 1), (self.U(i, t), -1)] + prev, -u0 if t == 0 else 0, np.inf,
                    f"startup {nm} h{t}")
                # min up: a start in the last `up` hours means the plant is still on
                add([(self.V(i, s), 1) for s in range(max(0, t - up + 1), t + 1)] + [(self.U(i, t), -1)],
                    -np.inf, 0, f"min-up {nm} h{t}")
                # min down: no start in the last `down` hours if the plant was on just before them
                window = [(self.V(i, s), 1) for s in range(max(0, t - down + 1), t + 1)]
                if t - down >= 0:
                    add(window + [(self.U(i, t - down), 1)], -np.inf, 1, f"min-down {nm} h{t}")
                else:
                    add(window, -np.inf, 1 - u0, f"min-down {nm} h{t}")
        r_idx = [k for k, terms in enumerate(rows) for _ in terms]
        c_idx = [j for terms in rows for j, _ in terms]
        vals = [a for terms in rows for _, a in terms]
        self.A = csr_matrix((vals, (r_idx, c_idx)), shape=(len(rows), self.N))
        self.c, self.row_lo, self.row_hi, self.row_names = c, np.array(lo), np.array(hi), names
        self.lb = np.zeros(self.N)
        self.ub = np.r_[np.ones(2 * n * T), [p["pmax_mw"] for p in plants for _ in range(T)]]
        self.integer = np.r_[np.ones(2 * n * T, bool), np.zeros(n * T, bool)]

    def U(self, i, t): return i * self.T + t
    def V(self, i, t): return self.n * self.T + i * self.T + t
    def P(self, i, t): return 2 * self.n * self.T + i * self.T + t

    def violations(self, x, tol=1e-6):
        """Names of the rules x breaks (empty list = x is a valid solution)."""
        ax = self.A @ x
        bad = [self.row_names[k] for k in np.where((ax < self.row_lo - tol) | (ax > self.row_hi + tol))[0]]
        if np.any(x < self.lb - tol) or np.any(x > self.ub + tol):
            bad.append("variable bounds")
        if np.any(np.abs(x[self.integer] - np.round(x[self.integer])) > tol):
            bad.append("integrality")
        return bad

    def to_highs(self):
        lp = highspy.HighsLp()
        lp.num_col_, lp.num_row_ = self.N, self.A.shape[0]
        lp.col_cost_, lp.col_lower_, lp.col_upper_ = self.c, self.lb, self.ub
        inf = highspy.kHighsInf
        lp.row_lower_ = np.where(np.isinf(self.row_lo), -inf, self.row_lo)
        lp.row_upper_ = np.where(np.isinf(self.row_hi), inf, self.row_hi)
        A = csc_matrix(self.A)
        lp.a_matrix_.format_ = highspy.MatrixFormat.kColwise
        lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = A.indptr, A.indices, A.data
        lp.integrality_ = [highspy.HighsVarType.kInteger if k else highspy.HighsVarType.kContinuous
                           for k in self.integer]
        return lp


# =====================================================================================================
# 3. From an on/off schedule to a full MILP solution
# =====================================================================================================
def dispatch(plants, on, demand_mw):
    """Cheapest output for one hour given which plants are on: everyone at pmin, then fill cheapest first.
    Returns MW per plant, or None if the on-plants can't match demand exactly."""
    pmin = np.array([p["pmin_mw"] for p in plants]) * on
    pmax = np.array([p["pmax_mw"] for p in plants]) * on
    if pmin.sum() > demand_mw + 1e-9 or pmax.sum() < demand_mw - 1e-9:
        return None
    out, left = pmin.copy(), demand_mw - pmin.sum()
    for i in sorted(range(len(plants)), key=lambda i: plants[i]["marginal_cost_per_mwh"]):
        if on[i]:
            add = min(left, pmax[i] - pmin[i])
            out[i] += add
            left -= add
    return out


def full_solution(model, schedule):
    """schedule [hours x plants] of 0/1 -> MILP vector x (u, v, p), or None if some hour can't be dispatched."""
    x = np.zeros(model.N)
    for i, p in enumerate(model.plants):
        prev = int(p["on_at_start"])
        for t in range(model.T):
            x[model.U(i, t)] = schedule[t, i]
            x[model.V(i, t)] = max(0, schedule[t, i] - prev)
            prev = schedule[t, i]
    for t in range(model.T):
        out = dispatch(model.plants, schedule[t], model.demand[t])
        if out is None:
            return None
        for i in range(model.n):
            x[model.P(i, t)] = out[i]
    return x


def repair(model, schedule, max_rounds=50):
    """Greedy, purely local fixes until the schedule obeys every rule (or give up -> None).

    - too little capacity in an hour      -> switch on the cheapest plant that's off
    - too much minimum output in an hour  -> switch off the most expensive plant that's on
    - a plant started but leaves too soon -> keep it on for its minimum up time, or, if that would push
                                             the minimum output above demand, drop that short run instead
    - a plant restarts too soon           -> keep it on through the gap, or, if that would push the minimum
                                             output above demand, keep it off for its full minimum rest
    (Choosing the direction that keeps the hourly rules intact stops the hourly and the up/down fixes from
    undoing each other round after round.)
    """
    plants, T, n = model.plants, model.T, model.n
    S = schedule.copy().astype(int)
    avg_cost = [p["no_load_cost_per_h"] / p["pmax_mw"] + p["marginal_cost_per_mwh"] for p in plants]
    cheap_first = sorted(range(n), key=lambda i: avg_cost[i])
    pmax = np.array([p["pmax_mw"] for p in plants])
    pmin = np.array([p["pmin_mw"] for p in plants])
    need = model.demand + model.reserve

    def can_be_on(i, hours):                                   # i on there keeps total pmin <= demand
        return all(S[t] @ pmin + pmin[i] * (1 - S[t, i]) <= model.demand[t] + 1e-9 for t in hours)

    def can_be_off(i, hours):                                  # i off there keeps capacity >= need
        return all(S[t] @ pmax - pmax[i] * S[t, i] >= need[t] - 1e-9 for t in hours)

    def runs(i, state):
        """(first hour, end hour) of every run of `state` (1 = on, 0 = off) in plant i's day."""
        col, out, t = S[:, i], [], 0
        while t < T:
            if col[t] == state:
                s = t
                while t < T and col[t] == state:
                    t += 1
                out.append((s, t))
            else:
                t += 1
        return out

    for _ in range(max_rounds):
        changed = False
        for t in range(T):                                     # capacity and minimum output, hour by hour
            while S[t] @ pmax < need[t] - 1e-9:
                off = [i for i in cheap_first if not S[t, i]]
                if not off:
                    return None
                S[t, off[0]] = 1
                changed = True
            if S[t] @ pmin > model.demand[t] + 1e-9:
                for i in reversed(cheap_first):                # most expensive first
                    if S[t, i] and can_be_off(i, [t]):
                        S[t, i] = 0
                        changed = True
                        if S[t] @ pmin <= model.demand[t] + 1e-9:
                            break
        for i, p in enumerate(plants):                         # min up / min down, plant by plant
            up, down, u0 = int(p["min_up_h"]), int(p["min_down_h"]), int(p["on_at_start"])
            for s, e in runs(i, 1):                            # on from hour s to e-1
                started = s > 0 or not u0                      # (on at midnight = no start today)
                if started and e < T and e - s < up:           # switched off before its minimum up time
                    ext = range(e, min(s + up, T))
                    if not can_be_on(i, ext) and can_be_off(i, range(s, e)):
                        S[s:e, i] = 0                          # drop the short run
                    else:
                        S[ext, i] = 1                          # stay on for the minimum up time
                    changed = True
            for s, e in runs(i, 0):                            # off from hour s to e-1
                was_on = s > 0 or u0                           # (off at midnight without being on = no rest rule)
                if was_on and e < T and e - s < down:          # restarts before its minimum rest
                    rest = range(e, min(s + down, T))
                    if not can_be_on(i, range(s, e)) and can_be_off(i, rest):
                        S[rest, i] = 0                         # stay off for the minimum rest
                    else:
                        S[s:e, i] = 1                          # stay on through the gap
                    changed = True
        x = full_solution(model, S)
        if x is not None and not model.violations(x):
            return S
        if not changed:
            return None
    return None


def true_cost(model, schedule):
    x = full_solution(model, schedule)
    return None if x is None else float(model.c @ x)


# =====================================================================================================
# 4. Blocks and the QUBO
# =====================================================================================================
def split_into_blocks(need, K):
    """Split hours 0..T-1 into K consecutive blocks with demand as flat as possible inside each block
    (dynamic programming over the squared deviation from each block's mean)."""
    T = len(need)
    cs, cs2 = np.r_[0, np.cumsum(need)], np.r_[0, np.cumsum(need ** 2)]
    sse = lambda a, b: cs2[b] - cs2[a] - (cs[b] - cs[a]) ** 2 / (b - a)        # hours a..b-1
    best = np.full((K + 1, T + 1), np.inf)
    arg = np.zeros((K + 1, T + 1), int)
    best[0, 0] = 0
    for k in range(1, K + 1):
        for b in range(k, T + 1):
            for a in range(k - 1, b):
                v = best[k - 1, a] + sse(a, b)
                if v < best[k, b]:
                    best[k, b], arg[k, b] = v, a
    cuts, b = [], T
    for k in range(K, 0, -1):
        cuts.append((arg[k, b], b))
        b = arg[k, b]
    return [list(range(a, b)) for a, b in reversed(cuts)]


class Qubo:
    """Energy(x) = offset + sum_k Q[k,k] x_k + sum_{k<l} Q[k,l] x_k x_l   with x_k in {0,1}.

    Bit k = (plant i, block b), k = i * K + b. Bit = 1 means "plant i is on for the whole block b".
    Energy = approximate daily cost + penalty for not having enough capacity on.
    """

    def __init__(self, plants, demand, reserve, blocks, penalty=1.0, target=0.5):
        n, K = len(plants), len(blocks)
        self.n, self.K, self.blocks = n, K, blocks
        self.N = n * K
        Q = np.zeros((self.N, self.N))
        offset = 0.0
        k = lambda i, b: i * K + b

        def lin(a, w):
            Q[a, a] += w

        def quad(a, b_, w):
            a, b_ = min(a, b_), max(a, b_)
            if a == b_:
                Q[a, a] += w                                    # x*x = x
            else:
                Q[a, b_] += w

        for b, hours in enumerate(blocks):
            L = len(hours)
            need = max(demand[t] + reserve[t] for t in hours)   # capacity must cover the block's worst hour
            rho = float(np.mean([demand[t] / (demand[t] + reserve[t]) for t in hours]))
            for i, p in enumerate(plants):
                # running cost while on: no-load + energy, assuming it runs at about rho of its size
                lin(k(i, b), L * (p["no_load_cost_per_h"] + p["marginal_cost_per_mwh"] * rho * p["pmax_mw"]))
                # startup cost: x_b * (1 - x_{b-1})   (before block 0: the plant's midnight state)
                if b == 0:
                    lin(k(i, b), p["startup_cost"] * (1 - p["on_at_start"]))
                else:
                    lin(k(i, b), p["startup_cost"])
                    quad(k(i, b), k(i, b - 1), -p["startup_cost"])
            # capacity: h = (sum pmax_i x_i - need) / need should be >= 0. Unbalanced penalty (no slack
            # qubits):  A * (h - target)^2 for both sides, plus a steeper linear wall when h < 0 is
            # approximated by the quadratic's slope. A is in dollars, scaled by the block's typical cost.
            scale = penalty * L * float(np.mean([demand[t] for t in hours])) * \
                float(np.mean([p["marginal_cost_per_mwh"] for p in plants]))
            a = np.array([p["pmax_mw"] / need for p in plants])     # h = a.x - 1
            c0 = -1.0 - target                                       # (a.x + c0)^2
            for i in range(n):
                lin(k(i, b), scale * (a[i] ** 2 + 2 * c0 * a[i]))
                for j in range(i + 1, n):
                    quad(k(i, b), k(j, b), scale * 2 * a[i] * a[j])
            offset += scale * c0 ** 2
        self.Q, self.offset = Q, offset

    def energy(self, x):
        x = np.asarray(x, float)
        return self.offset + x @ np.triu(self.Q) @ x

    def all_energies(self):
        """Energy of all 2^N bitstrings. Index z has bit k = (z >> k) & 1."""
        z = np.arange(2 ** self.N, dtype=np.int64)
        bits = [((z >> k) & 1).astype(np.float64) for k in range(self.N)]
        E = np.full(2 ** self.N, self.offset)
        for k in range(self.N):
            if self.Q[k, k]:
                E += self.Q[k, k] * bits[k]
            for l in range(k + 1, self.N):
                if self.Q[k, l]:
                    E += self.Q[k, l] * bits[k] * bits[l]
        return E

    def to_schedule(self, x, T):
        """Bits -> [hours x plants] 0/1 schedule."""
        S = np.zeros((T, self.n), int)
        for i in range(self.n):
            for b, hours in enumerate(self.blocks):
                S[hours, i] = int(x[i * self.K + b])
        return S


# =====================================================================================================
# 5. Solving the QUBO: QAOA (quantum), simulated annealing, brute force
# =====================================================================================================
def bits_of(z, N):
    return np.array([(z >> k) & 1 for k in range(N)], int)


def qaoa_state(Ehat, gammas, betas, N, group=5):
    """QAOA statevector: start in |+...+>, then for each layer apply exp(-i gamma E) and exp(-i beta sum X).

    The mixer RX(2 beta) acts on every qubit; it is applied `group` qubits at a time as one small dense
    matrix (kron of RX's), which needs fewer passes over the 2^N vector than one qubit at a time.
    """
    psi = np.full(2 ** N, 2 ** (-N / 2), complex)
    for g, b in zip(gammas, betas):
        psi = psi * np.exp(-1j * g * Ehat)                      # cost layer (diagonal)
        c, s = math.cos(b), -1j * math.sin(b)
        rx = np.array([[c, s], [s, c]])                         # exp(-i beta X) on one qubit
        q = 0
        while q < N:                                            # mixer on qubits q .. q+k-1
            k = min(group, N - q)
            M = rx
            for _ in range(k - 1):
                M = np.kron(M, rx)
            if q == 0:                                          # one big matrix product
                psi = (psi.reshape(-1, 2 ** k) @ M.T).reshape(-1)
            else:
                v = psi.reshape(2 ** (N - q - k), 2 ** k, 2 ** q)
                psi = np.matmul(M, v).reshape(-1)
            q += k
    return psi


def qaoa_circuit(qubo, Ehat_scale, Ehat_shift, gammas, betas):
    """The same QAOA as a Qiskit circuit (this is what would run on real quantum hardware).

    Cost layer exp(-i gamma (E - shift)/scale) with x_k = (1 - Z_k)/2:
      linear  w x_k        -> RZ(-gamma w/scale) on k
      pair    w x_k x_l    -> RZ(-gamma w/(2 scale)) on k and l, RZZ(gamma w/(2 scale)) on k,l
    (global phases dropped). Mixer exp(-i beta X) = RX(2 beta).
    """
    from qiskit import QuantumCircuit
    N, Q = qubo.N, qubo.Q
    qc = QuantumCircuit(N)
    qc.h(range(N))
    for g, b in zip(gammas, betas):
        a = g / Ehat_scale
        for k in range(N):
            rz = -a * Q[k, k]
            for l in range(N):
                w = Q[min(k, l), max(k, l)] if k != l else 0.0
                rz += -a * w / 2
            if rz:
                qc.rz(rz, k)
        for k in range(N):
            for l in range(k + 1, N):
                if Q[k, l]:
                    qc.rzz(a * Q[k, l] / 2, k, l)
        qc.rx(2 * b, range(N))
    return qc


def sample_on_qbraid(qc, device_id, shots, max_credits=0.0, timeout=3600, log=print):
    """Run the (already measured) circuit once on a qBraid device: real QPU or cloud simulator.

    Safety: the cost is estimated from the device's price list first, and the job is only submitted if the
    estimate is within `max_credits` (default 0 = free devices only). 100 qBraid credits = 1 USD.
    Returns {integer bitstring: count} in the same bit order as the Aer path (qubit 0 = rightmost).
    """
    from qbraid.runtime import QbraidProvider
    from qiskit import transpile
    device = QbraidProvider().get_device(device_id)
    status = str(device.status())
    if "ONLINE" not in status:
        raise RuntimeError(f"{device_id} is {status}; pick an ONLINE device (qbraid devices list --status ONLINE)")
    prof = device.profile
    if prof.num_qubits is not None and prof.num_qubits < qc.num_qubits:
        raise RuntimeError(f"{device_id} has {prof.num_qubits} qubits, the circuit needs {qc.num_qubits}")
    price = prof.pricing
    per_task = float(price.perTask) if price else 0.0
    per_shot = float(price.perShot) if price else 0.0
    per_min = float(price.perMinute) if price else 0.0
    estimate = per_task + per_shot * shots
    note = f" + {per_min:g} credits per minute of device time" if per_min else ""
    log(f"  {device_id}: estimated cost {estimate:,.0f} credits (${estimate / 100:,.2f}){note}")
    if estimate > max_credits or (per_min and max_credits <= 0):
        raise RuntimeError(f"Not submitted: the estimate is above --max-credits {max_credits:g}. Re-run with "
                           f"--max-credits <limit> once you've agreed to the cost.")
    # plain gates every provider understands (RZZ -> CX, RZ, CX)
    qc = transpile(qc, basis_gates=["h", "rx", "rz", "cx"], optimization_level=1)
    log(f"  submitting {qc.num_qubits} qubits, {qc.count_ops().get('cx', 0)} CX gates, depth {qc.depth()}, "
        f"{shots} shots ...")
    job = device.run(qc, shots=shots)
    log(f"  job id {job.id} (also visible in the Quantum Jobs panel); waiting up to {timeout} s")
    job.wait_for_final_state(timeout=timeout)
    counts = job.result().data.get_counts()
    return {int(b.replace(" ", ""), 2): int(c) for b, c in counts.items()}


def solve_qaoa(qubo, p=2, shots=4000, alpha=0.25, maxiter=60, seed=0, sampler="auto", device=None,
               max_credits=0.0, log=print):
    """Train QAOA angles on a simulated statevector, then sample bitstrings (Qiskit circuit if available).

    `maxiter` caps the COBYLA angle search (each step = one statevector simulation, ~0.5 s at 20 qubits);
    for p=2 the CVaR has usually stopped improving after ~50 steps."""
    N = qubo.N
    if N > 24:
        raise ValueError(f"{N} qubits is too many to simulate here; use --solver anneal or fewer --blocks")
    t0 = time.perf_counter()
    E = qubo.all_energies()
    shift, scale = E.mean(), E.std()
    Ehat = (E - shift) / scale
    order = np.argsort(E)
    E_sorted = Ehat[order]

    def cvar(probs):
        """Average energy of the best `alpha` fraction of outcomes (alpha = 1 -> plain expectation)."""
        ps = probs[order]
        cum = np.cumsum(ps)
        cut = np.searchsorted(cum, alpha)
        tot = ps[:cut] @ E_sorted[:cut] + (alpha - (cum[cut - 1] if cut else 0.0)) * E_sorted[min(cut, len(ps) - 1)]
        return tot / alpha

    def objective(theta):
        psi = qaoa_state(Ehat, theta[:p], theta[p:], N)
        return cvar(np.abs(psi) ** 2)

    # linear-ramp start: gamma grows, beta shrinks, like a slow (adiabatic) anneal
    x0 = np.r_[np.linspace(0.1, 0.8, p), np.linspace(0.8, 0.1, p)]
    res = minimize(objective, x0, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.3})
    gammas, betas = res.x[:p], res.x[p:]
    log(f"  QAOA p={p}: {N} qubits, {res.nfev} circuit evaluations, CVaR({alpha}) {res.fun:+.3f} "
        f"(uniform guessing {cvar(np.full(2 ** N, 2.0 ** -N)):+.3f})")

    rng = np.random.default_rng(seed)
    used = "numpy statevector"
    samples = None
    if sampler == "qbraid":
        from qiskit import QuantumCircuit  # noqa: F401  (fail early if qiskit is missing)
        qc = qaoa_circuit(qubo, scale, shift, gammas, betas)
        qc.measure_all()
        samples = sample_on_qbraid(qc, device, shots, max_credits, log=log)
        shots = sum(samples.values())
        used = f"qBraid device {device}"
    if sampler in ("auto", "qiskit"):
        try:
            from qiskit import transpile
            from qiskit_aer import AerSimulator
            qc = qaoa_circuit(qubo, scale, shift, gammas, betas)
            qc.measure_all()
            sim = AerSimulator(seed_simulator=seed)
            counts = sim.run(transpile(qc, sim), shots=shots).result().get_counts()
            samples = {int(s.replace(" ", ""), 2): c for s, c in counts.items()}   # qiskit: qubit 0 = rightmost
            used = f"Qiskit Aer circuit ({qc.num_qubits} qubits, depth {qc.depth()})"
        except ImportError:
            if sampler == "qiskit":
                raise
    if samples is None:
        probs = np.abs(qaoa_state(Ehat, gammas, betas, N)) ** 2
        draws = rng.choice(2 ** N, size=shots, p=probs / probs.sum())
        zs, cs = np.unique(draws, return_counts=True)
        samples = dict(zip(zs.tolist(), cs.tolist()))
    best_z = int(order[0])
    p_best = sum(c for z, c in samples.items() if E[z] <= E[best_z] + 1e-9) / shots
    log(f"  sampled {shots} shots with {used}; {len(samples)} distinct bitstrings; "
        f"QUBO optimum seen in {100 * p_best:.1f}% of shots (random guessing: {100 * 2.0 ** -N:.4f}%)")
    cands = sorted(samples, key=lambda z: E[z])
    return [bits_of(z, N) for z in cands], time.perf_counter() - t0


def solve_anneal(qubo, sweeps=1000, restarts=20, seed=0, log=print):
    """Simulated annealing on the QUBO (classical stand-in for a quantum annealer, works for any size).

    All `restarts` independent runs are advanced together (one numpy vector per bit), which is much
    faster than looping over runs in Python."""
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    N, R = qubo.N, restarts
    Qs = np.triu(qubo.Q, 1)
    Qs = Qs + Qs.T                                    # symmetric off-diagonal couplings
    d = np.diag(qubo.Q).copy()
    scale = np.abs(qubo.Q).max()
    x = rng.integers(0, 2, (R, N))                    # one row per restart
    field = d + x @ Qs                                # energy change of flipping 0->1, per run and bit
    rows = np.arange(R)
    for T in np.geomspace(scale, scale * 1e-4, sweeps):
        u = rng.random((N, R))
        for k in rng.permutation(N):
            dE = field[:, k] * (1 - 2 * x[:, k])
            flip = (dE <= 0) | (u[k] < np.exp(-np.maximum(dE, 0) / T))
            if flip.any():
                f = rows[flip]
                x[f, k] ^= 1
                field[f] += np.where(x[f, k], 1, -1)[:, None] * Qs[k]
    found = {tuple(r): qubo.energy(r) for r in x}
    cands = sorted(found, key=found.get)
    log(f"  simulated annealing: {N} bits, {restarts} restarts x {sweeps} sweeps, "
        f"{len(cands)} distinct answers, best energy {found[cands[0]]:,.0f}")
    return [np.array(c) for c in cands], time.perf_counter() - t0


def solve_exact(qubo, keep=200, log=print):
    t0 = time.perf_counter()
    E = qubo.all_energies()
    order = np.argsort(E)[:keep]
    log(f"  brute force over 2^{qubo.N} bitstrings, best energy {E[order[0]]:,.0f}")
    return [bits_of(int(z), qubo.N) for z in order], time.perf_counter() - t0


# =====================================================================================================
# 6. HiGHS, cold and warm
# =====================================================================================================
def run_highs(model, start=None, time_limit=60.0, seed=0, threads=1):
    """Solve the MILP with HiGHS. `start` = full MILP vector to begin from (the warm start)."""
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", float(time_limit))
    h.setOptionValue("random_seed", int(seed))
    h.setOptionValue("threads", int(threads))
    h.passModel(model.to_highs())
    timeline = []                                    # (seconds, objective) each time a better answer appears
    t0 = [0.0]

    def on_improve(e):
        timeline.append((time.perf_counter() - t0[0], float(e.data_out.objective_function_value)))

    h.cbMipImprovingSolution.subscribe(on_improve)
    if start is not None:
        sol = highspy.HighsSolution()
        sol.col_value = list(map(float, start))
        sol.value_valid = True
        h.setSolution(sol)
    t0[0] = time.perf_counter()
    h.run()
    secs = time.perf_counter() - t0[0]
    info = h.getInfo()
    x = np.array(h.getSolution().col_value)
    return {
        "status": h.modelStatusToString(h.getModelStatus()),
        "seconds": secs,
        "objective": info.objective_function_value,
        "nodes": int(info.mip_node_count),
        "gap_pct": 100 * info.mip_gap,
        "primal_dual_integral": info.primal_dual_integral,
        "first_incumbent_s": timeline[0][0] if timeline else None,
        "first_incumbent_obj": timeline[0][1] if timeline else None,
        "improvements": len(timeline),
        "x": x,
    }


# =====================================================================================================
# 7. Main
# =====================================================================================================
def show_schedule(plants, S, title):
    print(f"\n{title}")
    print("  hour        " + "".join(f"{t % 10}" for t in range(S.shape[0])))
    for i, p in enumerate(plants):
        print(f"  {p['plant_id'][:11]:<11} " + "".join("#" if S[t, i] else "." for t in range(S.shape[0])))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plants", default=str(HERE / "data/plants.csv"))
    ap.add_argument("--demand", default=str(HERE / "data/demand.csv"))
    ap.add_argument("--copies", type=int, default=1, help="make the fleet N times bigger (harder MILP)")
    ap.add_argument("--blocks", type=int, default=None, help="K time blocks (qubits = plants x K)")
    ap.add_argument("--solver", choices=["qaoa", "anneal", "exact"], default=None,
                    help="default: qaoa if it fits in --max-qubits, else anneal")
    ap.add_argument("--max-qubits", type=int, default=20)
    ap.add_argument("--p", type=int, default=2, help="QAOA layers")
    ap.add_argument("--shots", type=int, default=4000)
    ap.add_argument("--maxiter", type=int, default=60, help="QAOA optimizer steps (angle training)")
    ap.add_argument("--alpha", type=float, default=0.25, help="QAOA CVaR fraction (1 = plain average)")
    ap.add_argument("--sampler", choices=["auto", "qiskit", "numpy", "qbraid"], default="auto",
                    help="where the trained circuit is measured; qbraid = a real device or cloud simulator")
    ap.add_argument("--device", default="qbraid:qbraid:sim:qir-sv",
                    help="qBraid device id for --sampler qbraid (qbraid devices list --status ONLINE)")
    ap.add_argument("--max-credits", type=float, default=0.0,
                    help="largest estimated cost (qBraid credits, 100 = $1) allowed for the device run")
    ap.add_argument("--penalty", type=float, default=1.0, help="weight of the capacity penalty in the QUBO")
    ap.add_argument("--candidates", type=int, default=50, help="how many best samples to repair and score")
    ap.add_argument("--time-limit", type=float, default=60.0, help="HiGHS time limit per run (s)")
    ap.add_argument("--repeats", type=int, default=3, help="HiGHS runs per mode (different seeds)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", help="save results as JSON here")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    plants, demand, reserve = bigger_fleet(*map(lambda f: f, (load_plants(a.plants), *load_demand(a.demand))),
                                           a.copies, a.seed)
    if a.selftest:
        return selftest(plants, demand, reserve)
    n, T = len(plants), len(demand)
    model = Milp(plants, demand, reserve)
    print(f"Fleet: {n} plants x {T} hours -> MILP with {model.N} variables "
          f"({2 * n * T} binary), {model.A.shape[0]} constraints")

    # ---- quantum (or stand-in) step
    # blocks: as many as fit in --max-qubits for QAOA / brute force; the annealer has no qubit limit, so it
    # (and a fleet too big for 2 QAOA blocks, which then goes to the annealer) gets 4 blocks
    if a.blocks:
        K = a.blocks
    elif a.solver == "anneal" or (a.solver is None and a.max_qubits // n < 2):
        K = 4
    else:
        K = max(1, a.max_qubits // n)
    K = min(K, T)
    blocks = split_into_blocks(demand + reserve, K)
    qubo = Qubo(plants, demand, reserve, blocks, penalty=a.penalty)
    solver = a.solver or ("qaoa" if qubo.N <= a.max_qubits else "anneal")
    print(f"\nStep 1. QUBO: {K} blocks {[f'{h[0]}-{h[-1]}' for h in blocks]} -> {qubo.N} bits, solver {solver}")
    if solver == "qaoa":
        cands, q_secs = solve_qaoa(qubo, p=a.p, shots=a.shots, alpha=a.alpha, maxiter=a.maxiter, seed=a.seed,
                                  sampler=a.sampler, device=a.device, max_credits=a.max_credits)
    elif solver == "anneal":
        cands, q_secs = solve_anneal(qubo, seed=a.seed)
    else:
        cands, q_secs = solve_exact(qubo)

    # ---- repair the best candidates, keep the cheapest valid one
    t0 = time.perf_counter()
    best_S, best_cost, raw_S, n_ok = None, math.inf, None, 0
    for x in cands[:a.candidates]:
        S0 = qubo.to_schedule(x, T)
        raw_S = S0 if raw_S is None else raw_S
        S = repair(model, S0)
        if S is None:
            continue
        n_ok += 1
        cst = true_cost(model, S)
        if cst < best_cost:
            best_S, best_cost = S, cst
    r_secs = time.perf_counter() - t0
    print(f"\nStep 2. Repair: {n_ok}/{min(len(cands), a.candidates)} candidates made valid in {r_secs:.2f} s")
    start = None
    if best_S is not None:
        start = full_solution(model, best_S)
        assert not model.violations(start)
        print(f"  quantum warm start costs ${best_cost:,.0f}")
        if n <= 12:
            show_schedule(plants, raw_S, "Best QUBO sample, before repair (# = on):")
            show_schedule(plants, best_S, "Warm start handed to HiGHS:")
    else:
        print("  no candidate could be repaired: HiGHS runs without a start")

    # ---- HiGHS cold vs warm
    print(f"\nStep 3. HiGHS, {a.repeats} run(s) each (time limit {a.time_limit:g} s, 1 thread)")
    runs = {"cold": [], "warm": []}
    for r in range(a.repeats):
        runs["cold"].append(run_highs(model, None, a.time_limit, seed=a.seed + r))
        if start is not None:
            runs["warm"].append(run_highs(model, start, a.time_limit, seed=a.seed + r))
    opt = min(r["objective"] for rs in runs.values() for r in rs)

    def summary(rs):
        med = lambda key: float(np.median([r[key] for r in rs]))
        return {"seconds": med("seconds"), "nodes": med("nodes"), "gap_pct": med("gap_pct"),
                "primal_dual_integral": med("primal_dual_integral"),
                "objective": min(r["objective"] for r in rs),
                "first_incumbent_s": float(np.median([r["first_incumbent_s"] or 0 for r in rs])),
                "status": rs[0]["status"]}

    print(f"\n  {'':6} {'time (s)':>9} {'B&B nodes':>10} {'final gap':>10} {'P-D integral':>13} "
          f"{'cost':>12} status")
    table = {}
    for mode, rs in runs.items():
        if not rs:
            continue
        s = table[mode] = summary(rs)
        print(f"  {mode:6} {s['seconds']:9.3f} {s['nodes']:10.0f} {s['gap_pct']:9.2f}% "
              f"{s['primal_dual_integral']:13.4f} ${s['objective']:>11,.0f} {s['status']}")
    if start is not None:
        c, w = table["cold"], table["warm"]
        print(f"\n  warm start was {100 * (best_cost - opt) / opt:+.2f}% from the best cost found")
        print(f"  HiGHS time    cold {c['seconds']:.3f} s -> warm {w['seconds']:.3f} s "
              f"({c['seconds'] / max(w['seconds'], 1e-9):.2f}x)")
        print(f"  B&B nodes     cold {c['nodes']:.0f} -> warm {w['nodes']:.0f}")
        where = ("including the cloud queue and device time" if a.sampler == "qbraid"
                 else "on a classical simulator (not comparable to QPU time)")
        print(f"  quantum step  {q_secs:.2f} s {where}, repair {r_secs:.2f} s")
    if a.out:
        res = {"plants": n, "hours": T, "qubits": qubo.N, "solver": solver, "blocks": blocks,
               "warm_start_cost": best_cost if start is not None else None, "best_cost": opt,
               "quantum_seconds": q_secs, "repair_seconds": r_secs, "highs": table}
        Path(a.out).write_text(json.dumps(res, indent=2))
        print(f"\nSaved {a.out}")


def selftest(plants, demand, reserve):
    """Check the pieces against each other on small cases."""
    model = Milp(plants, demand, reserve)
    T, n = len(demand), len(plants)
    # (a) the MILP optimum passes our rule checker, and our cost function agrees with it
    r = run_highs(model, None, 60)
    S = np.round(r["x"][:n * T]).reshape(n, T).T.astype(int)
    assert not model.violations(r["x"]), model.violations(r["x"])
    assert abs(true_cost(model, S) - r["objective"]) < 1e-3 * r["objective"], "dispatch disagrees with MILP"
    print(f"ok  MILP optimum ${r['objective']:,.0f} is valid; merit-order dispatch gives the same cost")
    # (b) the repair leaves a valid schedule alone, and fixes an 'everything off' schedule
    assert (repair(model, S) == S).all()
    print(f"ok  repair keeps a valid schedule; all-off schedule -> "
          f"{'valid' if repair(model, np.zeros((T, n), int)) is not None else 'not repairable'}")
    # (c) QUBO energy formula = brute-force table; QAOA numpy statevector = Qiskit circuit
    blocks = split_into_blocks(demand + reserve, 2)
    q = Qubo(plants, demand, reserve, blocks)
    E = q.all_energies()
    rng = np.random.default_rng(1)
    for z in rng.integers(0, 2 ** q.N, 20):
        assert abs(E[z] - q.energy(bits_of(int(z), q.N))) < 1e-6 * abs(E[z])
    print(f"ok  QUBO energies ({q.N} bits) match the brute-force table")
    try:
        from qiskit.quantum_info import Statevector
        shift, scale = E.mean(), E.std()
        g, b = [0.4, 0.7], [0.6, 0.2]
        p_np = np.abs(qaoa_state((E - shift) / scale, g, b, q.N)) ** 2
        p_qk = Statevector(qaoa_circuit(q, scale, shift, g, b)).probabilities()
        assert np.allclose(p_np, p_qk, atol=1e-9), np.abs(p_np - p_qk).max()
        print("ok  numpy QAOA simulation and the Qiskit circuit give identical probabilities")
    except ImportError:
        print("--  qiskit not installed: circuit check skipped")
    # (d) a warm start is accepted by HiGHS and gives the same optimum
    w = run_highs(model, r["x"], 60)
    assert abs(w["objective"] - r["objective"]) < 1e-6 * r["objective"]
    print(f"ok  HiGHS accepts a warm start (first answer at {w['first_incumbent_s']:.4f} s)")


if __name__ == "__main__":
    main()
