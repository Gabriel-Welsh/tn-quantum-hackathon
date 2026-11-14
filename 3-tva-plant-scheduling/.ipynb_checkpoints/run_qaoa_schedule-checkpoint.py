#!/usr/bin/env python3
"""Hour-by-hour unit commitment with QAOA and the look-ahead credit.

For each hour:
  1. Work out which plants min up / min down times force on or off (classical).
  2. Build the one-hour QUBO: plant costs + capacity penalty (slack bits) + lock penalties,
     minus the look-ahead credit:  E' = E - sum_i credit_i * x_i
     credit_i = w * startup_i if some hour in the next L hours needs more MW than the
     fleet can supply without plant i (on or off now: the startup is paid anyway, or
     would be paid again after switching off).
  3. Tune QAOA angles on the exact statevector (warm start from the previous hour).
  4. Draw `shots` samples and keep the valid sampled choice with the lowest
     hour_cost - credit (the pick uses the same credit as the QUBO).
  5. Carry the choice forward as "who was on".

Usage (run from this folder, with the qBraid-SDK kernel's Python):
  python run_qaoa_schedule.py                                  # data/plants.csv, data/demand.csv
  python run_qaoa_schedule.py --plants my_plants.csv --demand my_demand.csv --out schedule.csv
  python run_qaoa_schedule.py --shots 20 --p 2 --seed 3
  python run_qaoa_schedule.py --no-credit                      # the starter's loop, for comparison
  python run_qaoa_schedule.py --sampler exact                  # try every choice (no QAOA)

CSV formats are the same as data/plants.csv and data/demand.csv (demand.csv needs
hour, demand_mw, reserve_mw). Everything runs on a local simulator: no jobs, no credits.
"""
import argparse
import csv
import itertools
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import check_schedule, hour_cost, hour_ok, load_demand, load_plants, locks, solve_milp  # noqa: E402

try:
    from qiskit import QuantumCircuit
    from qiskit.circuit import ParameterVector
    from qiskit.quantum_info import Statevector
except ImportError:
    sys.exit("Qiskit not found. Run this with the qBraid-SDK environment's Python, e.g.\n"
             "  ~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python run_qaoa_schedule.py")


# ------------------------------------------------------------------ QUBO
def plant_hour_costs(plants, was_on, starter_formula=False):
    """Approximate $ cost of having each plant on this hour (TODO 2 in the starter)."""
    m = min(p["marginal_cost_per_mwh"] for p in plants)
    c = np.zeros(len(plants))
    for i, p in enumerate(plants):
        if starter_formula:   # the starter notebook's version, kept for reproducing its numbers
            extra = p["pmin_mw"] * p["marginal_cost_per_mwh"] - m
        else:                 # the formula as written: pmin * (marginal - marginal_cheapest)
            extra = p["pmin_mw"] * (p["marginal_cost_per_mwh"] - m)
        c[i] = p["startup_cost"] * (1 - was_on[i]) + p["no_load_cost_per_h"] + extra
    return c


def build_qubo(c, plants, demand_mw, reserve_mw, block_mw, n_slack, penalty):
    """E = sum c_i x_i + A (sum a_i x_i - sum 2^k s_k - r)^2, as an upper-triangular Q plus offset."""
    n = len(plants) + n_slack
    b = np.array([p["pmax_mw"] / block_mw for p in plants] + [-(2 ** k) for k in range(n_slack)])
    r = np.ceil((demand_mw + reserve_mw) / block_mw)
    Q = np.zeros((n, n))
    Q[np.arange(len(c)), np.arange(len(c))] += c
    for j in range(n):
        Q[j, j] += penalty * (b[j] ** 2 - 2 * r * b[j])
        for k in range(j + 1, n):
            Q[j, k] += penalty * 2 * b[j] * b[k]
    return Q, penalty * r ** 2


def add_locks(Q, offset, must_on, must_off, weight):
    Q = Q.copy()
    for i in must_on:
        Q[i, i] -= weight
        offset += weight
    for i in must_off:
        Q[i, i] += weight
    return Q, offset


def necessity_credit(plants, need, t, lookahead, weight):
    """credit_i = weight * startup_i if some hour in t+1..t+lookahead can't be covered without plant i."""
    total = sum(p["pmax_mw"] for p in plants)
    future = need[t + 1 : t + 1 + lookahead]
    credit = np.zeros(len(plants))
    if len(future):
        for i, p in enumerate(plants):
            if future.max() > total - p["pmax_mw"]:
                credit[i] = weight * p["startup_cost"]
    return credit


# ------------------------------------------------------------------ QAOA
class QAOA:
    def __init__(self, n_qubits):
        self.n = n_qubits
        self.bits = (np.arange(2 ** n_qubits)[:, None] >> np.arange(n_qubits)) & 1   # row k = bits of index k

    def energies(self, Q, offset):
        return np.einsum("bj,jk,bk->b", self.bits, np.triu(Q), self.bits) + offset

    @staticmethod
    def to_ising(Q):
        # y = (1 - z)/2  ->  sum h_j Z_j + sum J_jk Z_j Z_k + const
        h, J = np.zeros(len(Q)), {}
        for j in range(len(Q)):
            h[j] -= Q[j, j] / 2
            for k in range(j + 1, len(Q)):
                if Q[j, k] != 0:
                    J[(j, k)] = Q[j, k] / 4
                    h[j] -= Q[j, k] / 4
                    h[k] -= Q[j, k] / 4
        return h, J

    def circuit(self, Q, p):
        h, J = self.to_ising(Q)
        scale = max(np.abs(h).max(), max((abs(v) for v in J.values()), default=0)) or 1.0
        gammas, betas = ParameterVector("gamma", p), ParameterVector("beta", p)
        qc = QuantumCircuit(self.n)
        qc.h(range(self.n))
        for layer in range(p):
            for j, hj in enumerate(h):
                if hj != 0:
                    qc.rz(2 * gammas[layer] * hj / scale, j)
            for (j, k), Jjk in J.items():
                qc.rzz(2 * gammas[layer] * Jjk / scale, j, k)
            qc.rx(2 * betas[layer], range(self.n))
        return qc, list(gammas) + list(betas)

    def run(self, Q, offset, p=1, start=None, maxiter=60):
        """Tune angles to minimize <E> (rescaled to 0..1). Returns (angles, probabilities of all bitstrings)."""
        E = self.energies(Q, offset)
        E = (E - E.min()) / ((E.max() - E.min()) or 1.0)
        qc, params = self.circuit(Q, p)

        def probs_at(angles):
            return Statevector(qc.assign_parameters(dict(zip(params, angles)))).probabilities()

        def avg_energy(angles):
            return probs_at(angles) @ E

        if start is None or len(start) != 2 * p:
            grid = [(g, b) for g in np.linspace(0.1, 3.0, 15) for b in np.linspace(0.1, 1.5, 8)]
            g, b = min(grid, key=lambda gb: avg_energy([gb[0]] * p + [gb[1]] * p))
            start = [g] * p + [b] * p
        res = minimize(avg_energy, start, method="COBYLA", options={"maxiter": maxiter, "rhobeg": 0.2})
        return res.x, probs_at(res.x)


# ------------------------------------------------------------------ day loop
def schedule_day(plants, demand, reserve, p=1, shots=200, sampler="qaoa", seed=7, use_credit=True,
                 lookahead=3, credit_weight=1.0, block_mw=50, n_slack=3, penalty_k=2.0,
                 starter_formula=False, maxiter=60, verbose=True):
    n = len(plants)
    rng = np.random.default_rng(seed)
    need = demand + reserve
    qaoa = QAOA(n + n_slack) if sampler == "qaoa" else None
    plant_index = (((np.arange(2 ** (n + n_slack))[:, None] >> np.arange(n)) & 1) @ (2 ** np.arange(n)))
    all_choices = [list(c) for c in itertools.product([0, 1], repeat=n)]

    history, angles, rows = [], None, []
    was_on = [int(x["on_at_start"]) for x in plants]
    for t in range(len(demand)):
        t0 = time.perf_counter()
        credit = necessity_credit(plants, need, t, lookahead, credit_weight) if use_credit else np.zeros(n)
        must_on, must_off = locks(plants, history)
        c = plant_hour_costs(plants, was_on, starter_formula)

        if sampler == "exact":
            seen, samples = all_choices, None
        else:
            if qaoa is not None:
                Q, offset = build_qubo(c, plants, demand[t], reserve[t], block_mw, n_slack, penalty_k * c.max())
                Q[np.arange(n), np.arange(n)] -= credit                          # look-ahead term
                Q, offset = add_locks(Q, offset, must_on, must_off, weight=2 * c.max())
                angles, probs = qaoa.run(Q, offset, p=p, start=angles, maxiter=maxiter)
            else:                                                                 # random guessing
                probs = np.full(2 ** (n + n_slack), 1 / 2 ** (n + n_slack))
            samples = rng.choice(len(probs), size=shots, p=probs / probs.sum())
            seen = [[(k >> i) & 1 for i in range(n)] for k in np.unique(plant_index[samples])]

        def score(ch):                                                            # same credit as the QUBO
            return hour_cost(plants, demand[t], ch, was_on) - float(np.dot(credit, ch))

        ok = [ch for ch in seen if hour_ok(plants, demand[t], reserve[t], ch, must_on, must_off)]
        note = ""
        if not ok:
            ok = [ch for ch in seen if hour_ok(plants, demand[t], reserve[t], ch)]
            note = "no sample respected the locks"
        if ok:
            pick = min(ok, key=score)
        else:
            k = int(np.bincount(plant_index[samples]).argmax())
            pick = [(k >> i) & 1 for i in range(n)]
            note = "no valid sample: kept the most common one"

        cost = hour_cost(plants, demand[t], pick, was_on)
        rows.append(dict(hour=t, pick=pick, cost=cost, credit=credit, note=note, secs=time.perf_counter() - t0))
        if verbose:
            on = "+".join(pl["plant_id"] for pl, u in zip(plants, pick) if u) or "none"
            cr = ", ".join(f"{pl['plant_id']} ${v:,.0f}" for pl, v in zip(plants, credit) if v)
            print(f"  hour {t:>2}  need {need[t]:>6.0f} MW  {on:<34} ${cost:>10,.0f}"
                  + (f"  credit: {cr}" if cr else "") + (f"  [{note}]" if note else ""), flush=True)
        history.append(pick)
        was_on = pick
    return np.array(history), rows


# ------------------------------------------------------------------ main
def main():
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plants", default=here / "data" / "plants.csv", help="plants CSV (default: data/plants.csv)")
    ap.add_argument("--demand", default=here / "data" / "demand.csv", help="demand CSV (default: data/demand.csv)")
    ap.add_argument("--p", type=int, default=1, help="QAOA layers (default 1)")
    ap.add_argument("--shots", type=int, default=200, help="samples per hour (default 200)")
    ap.add_argument("--seed", type=int, default=7, help="sampling seed (default 7)")
    ap.add_argument("--sampler", choices=["qaoa", "random", "exact"], default="qaoa",
                    help="qaoa (default), random guessing, or exact (try every choice, no QAOA)")
    ap.add_argument("--no-credit", action="store_true", help="turn off the look-ahead credit")
    ap.add_argument("--lookahead", type=int, default=3, help="look-ahead window L in hours (default 3)")
    ap.add_argument("--credit-weight", type=float, default=1.0, help="credit weight w (default 1.0)")
    ap.add_argument("--penalty", type=float, default=2.0, help="capacity penalty A = this x max(c) (default 2)")
    ap.add_argument("--block-mw", type=float, default=50, help="capacity block size in MW (default 50)")
    ap.add_argument("--slack-bits", type=int, default=3, help="slack qubits, covers 0..2^k-1 spare blocks (default 3)")
    ap.add_argument("--maxiter", type=int, default=60, help="COBYLA iterations per hour (default 60)")
    ap.add_argument("--starter-costs", action="store_true",
                    help="use the starter notebook's plant_hour_costs (to reproduce its numbers)")
    ap.add_argument("--no-milp", action="store_true", help="skip the MILP comparison")
    ap.add_argument("--out", help="write the schedule to this CSV")
    ap.add_argument("--quiet", action="store_true", help="only print the summary")
    a = ap.parse_args()

    plants = load_plants(a.plants)
    demand, reserve = load_demand(a.demand)
    n_qubits = len(plants) + a.slack_bits
    print(f"{len(plants)} plants, {len(demand)} hours, sampler={a.sampler}"
          + (f", p={a.p}, shots={a.shots}, {n_qubits} qubits" if a.sampler != "exact" else "")
          + (", no credit" if a.no_credit else f", look-ahead L={a.lookahead} w={a.credit_weight}"))
    if a.sampler == "qaoa" and n_qubits > 20:
        print(f"warning: {n_qubits} qubits means a 2^{n_qubits} statevector per step; this will be slow.")

    t0 = time.perf_counter()
    schedule, rows = schedule_day(plants, demand, reserve, p=a.p, shots=a.shots, sampler=a.sampler, seed=a.seed,
                                  use_credit=not a.no_credit, lookahead=a.lookahead, credit_weight=a.credit_weight,
                                  block_mw=a.block_mw, n_slack=a.slack_bits, penalty_k=a.penalty,
                                  starter_formula=a.starter_costs, maxiter=a.maxiter, verbose=not a.quiet)
    secs = time.perf_counter() - t0

    milp_cost, milp_secs = None, 0.0
    if not a.no_milp:
        try:
            milp_cost, _, _, milp_secs = solve_milp(plants, demand, reserve)
        except RuntimeError as e:
            print(f"MILP: {e}")
    res = check_schedule(plants, demand, reserve, schedule, milp_cost=milp_cost, verbose=False)

    print(f"\nTotal cost ${res['total_cost']:,.0f}   ({secs:.1f} s)")
    if milp_cost is not None:
        print(f"MILP optimum ${milp_cost:,.0f}   ({milp_secs:.3f} s)   gap {res['gap_pct']:+.2f}%")
    if res["violations"]:
        print(f"{len(res['violations'])} rule(s) broken:")
        for v in res["violations"]:
            print("  ", v)
    else:
        print("All rules satisfied.")

    if a.out:
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["hour"] + [p["plant_id"] for p in plants] + ["hour_cost"])
            for r in rows:
                w.writerow([r["hour"]] + list(r["pick"]) + [round(r["cost"], 2)])
        print(f"Schedule written to {a.out}")


if __name__ == "__main__":
    main()
