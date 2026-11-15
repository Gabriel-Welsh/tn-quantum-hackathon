#!/usr/bin/env python3
"""Hour-by-hour unit commitment with QAOA and the look-ahead credit.

For each hour:
  1. Work out which plants min up / min down times force on or off, plus feasibility locks:
     a plant that is on stays on if switching it off (it then can't restart for min_down
     hours) would leave a later hour short of capacity.
  2. Build the one-hour QUBO: plant costs + capacity penalty (slack bits) + lock penalties,
     minus the look-ahead credit:  E' = E - sum_i credit_i * x_i
     plan rule (default): credit_i = w * max(0, startup_i - (k-1) * hold_i) if plant i is in the
       cheapest future plan k <= L hours from now (its startup is paid soon anyway).
     necessity rule: credit_i = w * startup_i if some hour in the next L hours needs more MW
       than the fleet can supply without plant i.
  3. Tune QAOA angles on the exact statevector (warm start from the previous hour).
  4. Sample the tuned circuit `shots` times: on the local simulator, or on a quantum
     device through qBraid (--device). Take the best sampled choice: valid this hour AND
     leaves every later hour coverable, lowest hour_cost - credit (same credit as the QUBO).
  5. Local search (classical, --no-local-search turns it off): improve that choice by
     switching single plants on/off or swapping pairs. If no sample is valid, it repairs
     the closest one instead of breaking a rule.
  6. Carry the choice forward as "who was on".

Usage (run from the project root):
  python scheduling/run_qaoa_schedule.py                                  # local simulator, data/*.csv
  python scheduling/run_qaoa_schedule.py --plants my_plants.csv --demand my_demand.csv --out outputs/schedule.csv
  python scheduling/run_qaoa_schedule.py --shots 20 --p 2 --seed 3
  python scheduling/run_qaoa_schedule.py --no-credit                      # the starter's loop, for comparison
  python scheduling/run_qaoa_schedule.py --sampler exact                  # try every choice (no QAOA)

Quantum devices (through qBraid; angles are still tuned locally, only the sampling runs remotely):
  python scheduling/run_qaoa_schedule.py --device --hours 14              # IonQ simulator, forte-1 noise (free)
  python scheduling/run_qaoa_schedule.py --device                         # IonQ simulator, all 24 hours (free)
  python scheduling/run_qaoa_schedule.py --device aws:ionq:qpu:forte-1 --hours 14 --shots 100   # real QPU (paid)
  qbraid devices list --status ONLINE                          # other device IDs

Paid devices: the script prints the credit estimate and asks before submitting (--yes skips
the question). Job IDs are saved to --jobs-log (default qaoa_jobs.json); rerun the same
command to resume after a timeout or interruption without resubmitting.

CSV formats are the same as data/plants.csv and data/demand.csv (demand.csv needs
hour, demand_mw, reserve_mw).
"""
import argparse
import csv
import hashlib
import itertools
import json
import sys
import time
import warnings
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
             "  ~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python scheduling/run_qaoa_schedule.py")

DEFAULT_DEVICE = "ionq:ionq:sim:simulator"


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


def future_plan(plants, demand, reserve):
    """For each hour, the cheapest valid on/off choice if startups were free: who you'd want running then.
    Enumerates all 2^n choices per hour (classical; fine up to about 14 plants)."""
    n = len(plants)
    choices = [list(c) for c in itertools.product([0, 1], repeat=n)]
    plan = []
    for t in range(len(demand)):
        ok = [c for c in choices if hour_ok(plants, demand[t], reserve[t], c)]
        plan.append(min(ok, key=lambda c: hour_cost(plants, demand[t], c, c)) if ok else [0] * n)
    return np.array(plan)


def plan_credit(plants, plan, t, lookahead, weight):
    """credit_i = weight * max(0, startup_i - (k-1) * hold_i) if plant i is in the future plan k <= lookahead
    hours from now. hold_i = $/h to keep it on (no-load + pmin at its premium over the cheapest plant).
    With this credit, being on this hour wins exactly when startup_i > k * hold_i."""
    m = min(p["marginal_cost_per_mwh"] for p in plants)
    credit = np.zeros(len(plants))
    for i, p in enumerate(plants):
        ahead = np.flatnonzero(plan[t + 1 : t + 1 + lookahead, i])
        if len(ahead):
            hold = p["no_load_cost_per_h"] + p["pmin_mw"] * (p["marginal_cost_per_mwh"] - m)
            credit[i] = weight * max(0.0, p["startup_cost"] - ahead[0] * hold)   # ahead[0] = k - 1
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
        """Tune angles to minimize <E> (rescaled to 0..1).
        Returns (angles, probabilities of all bitstrings, the tuned circuit with measurements)."""
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
        measured = QuantumCircuit(self.n, self.n)
        measured.compose(qc.assign_parameters(dict(zip(params, res.x))), inplace=True)
        measured.measure(range(self.n), range(self.n))
        return res.x, probs_at(res.x), measured


# ------------------------------------------------------------------ quantum devices (qBraid)
class DeviceRunner:
    """Submits tuned circuits to a qBraid device, one job per hour, and keeps a resumable job log."""

    def __init__(self, device_id, shots, noise_model, log_path, timeout):
        try:
            from qbraid.runtime import QbraidJob, QbraidProvider
        except ImportError:
            sys.exit("qBraid SDK not found. Use the qBraid-SDK environment's Python for --device.")
        self.QbraidJob = QbraidJob
        self.device = QbraidProvider().get_device(device_id)
        self.device_id, self.shots, self.timeout = device_id, shots, timeout
        self.noise_model = None
        if noise_model and noise_model != "none":
            models = [str(m) for m in (getattr(self.device.profile, "noise_models", None) or [])]
            if noise_model in models:
                self.noise_model = noise_model
            elif models:
                sys.exit(f"{device_id} has no noise model '{noise_model}' (it has: {', '.join(models)}). "
                         f"Pick one with --noise-model, or --noise-model none.")
        self.log_path = Path(log_path)
        self.log = {"device": device_id, "shots": shots, "noise_model": self.noise_model, "hours": {}}
        if self.log_path.exists():
            old = json.loads(self.log_path.read_text())
            if (old.get("device"), old.get("shots"), old.get("noise_model")) == (device_id, shots, self.noise_model):
                self.log = old
                if old["hours"]:
                    print(f"Resuming from {self.log_path}: jobs already recorded for hours "
                          f"{', '.join(sorted(old['hours'], key=int))}")
            else:
                print(f"Note: {self.log_path} is for a different device/shots/options; starting a new log.")

    def status(self):
        return str(self.device.status()).split(".")[-1]

    def cost_estimate(self, n_jobs):
        pr = self.device.profile.pricing
        per_task = float(getattr(pr, "perTask", getattr(pr, "per_task", 0)) or 0)
        per_shot = float(getattr(pr, "perShot", getattr(pr, "per_shot", 0)) or 0)
        per_min = float(getattr(pr, "perMinute", getattr(pr, "per_minute", 0)) or 0)
        return n_jobs * (per_task + per_shot * self.shots), per_task, per_shot, per_min

    def _save(self):
        self.log_path.write_text(json.dumps(self.log, indent=1))

    def sample(self, t, qc):
        """Counts for hour t: reuses a finished or pending job from the log, otherwise submits one."""
        from qiskit import qasm2
        fingerprint = hashlib.sha256(qasm2.dumps(qc).encode()).hexdigest()[:16]
        entry = self.log["hours"].get(str(t))
        if entry and entry.get("circuit") != fingerprint:
            sys.exit(f"\nHour {t}: {self.log_path} has job {entry['job_id']} for a different circuit "
                     f"(the data or settings changed since it was submitted).\n"
                     f"Use a new --jobs-log file, or delete this one, to submit fresh jobs.")
        if entry and "counts" in entry:
            return entry["counts"], entry["job_id"], "from log"
        if entry:
            job = self.QbraidJob(entry["job_id"], device=self.device)
            how = "resumed"
        else:
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Circuit contains measurement gates")
                # a fresh dict each call: device.run rewrites runtime_options in place
                opts = {"runtime_options": {"noise_model": self.noise_model}} if self.noise_model else {}
                job = self.device.run(qc, shots=self.shots, **opts)
            self.log["hours"][str(t)] = {"job_id": job.id, "circuit": fingerprint}
            self._save()
            how = "submitted"
        print(f"  hour {t:>2}: job {job.id} {how}, waiting (timeout {self.timeout} s) ...", flush=True)
        try:
            job.wait_for_final_state(timeout=self.timeout)
        except Exception as e:   # timeout or polling error: keep the job ID, let the user resume
            self._save()
            sys.exit(f"\nHour {t}: job {job.id} not finished ({type(e).__name__}: {e}).\n"
                     f"Its ID is saved in {self.log_path}. Rerun the same command to resume.")
        status = str(job.status()).split(".")[-1]
        if status != "COMPLETED":
            self.log["hours"].pop(str(t))
            self._save()
            sys.exit(f"\nHour {t}: job {job.id} ended with status {status}. "
                     f"Rerun to resubmit, or check it in the Quantum Jobs panel.")
        counts = {k.replace(" ", ""): int(v) for k, v in job.result().data.get_counts().items()}
        self.log["hours"][str(t)].update(counts=counts, status=status)
        self._save()
        return counts, job.id, how


def counts_to_samples(counts, n_qubits):
    # Qiskit-style bitstrings put qubit 0 last, so int(key, 2) gives the index with bit j = qubit j.
    idx = np.array([int(k, 2) for k in counts], dtype=int) & (2 ** n_qubits - 1)
    return np.repeat(idx, [counts[k] for k in counts])


# ------------------------------------------------------------------ future feasibility
def future_shortfall(plants, history, need, t, ch):
    """MW short in later hours if we pick `ch` now and plants switched off stay off as long as min down
    forces them to. Plants that `ch` keeps on are assumed available later (they can stay on).
    0 means every later hour can still be covered; > 0 means `ch` makes some later hour impossible."""
    n, T = len(plants), len(need)
    restart = np.full(n, t + 1)                       # first later hour each plant can be on
    for j, p in enumerate(plants):
        if ch[j]:
            continue
        states = [int(p["on_at_start"])] + [int(h[j]) for h in history] + [0]
        held = 0
        for s in reversed(states):
            if s != 0:
                break
            held += 1
        if held < len(states):                        # switched today: min down applies (same rule as locks())
            restart[j] = t + 1 + max(0, int(p["min_down_h"]) - held)
    short = 0.0
    pmax = np.array([p["pmax_mw"] for p in plants])
    for h in range(t + 1, min(T, int(restart.max()))):
        cap = pmax[(np.array(ch) == 1) | (restart <= h)].sum()
        short += max(0.0, need[h] - cap)
    return short


def local_search(start, key, n, max_steps=50):
    """Steepest descent over 1-plant flips and on/off swaps, minimizing key(choice)."""
    cur, cur_k = list(start), key(start)
    for _ in range(max_steps):
        on = [i for i in range(n) if cur[i]]
        off = [i for i in range(n) if not cur[i]]
        nbrs = []
        for i in range(n):
            nb = cur.copy(); nb[i] ^= 1; nbrs.append(nb)
        for i in on:
            for j in off:
                nb = cur.copy(); nb[i], nb[j] = 0, 1; nbrs.append(nb)
        best = min(nbrs, key=key)
        best_k = key(best)
        if best_k >= cur_k:
            break
        cur, cur_k = best, best_k
    return cur


# ------------------------------------------------------------------ day loop
def schedule_day(plants, demand, reserve, p=1, shots=200, sampler="qaoa", seed=7, use_credit=True,
                 lookahead=3, credit_weight=1.0, block_mw=50, n_slack=3, penalty_k=2.0,
                 starter_formula=False, maxiter=60, runner=None, device_hours=(), use_local_search=True,
                 credit_rule="plan", verbose=True):
    n = len(plants)
    nq = n + n_slack
    rng = np.random.default_rng(seed)
    need = demand + reserve
    plan = future_plan(plants, demand, reserve) if use_credit and credit_rule == "plan" else None
    qaoa = QAOA(nq) if sampler == "qaoa" else None
    plant_index = (((np.arange(2 ** nq)[:, None] >> np.arange(n)) & 1) @ (2 ** np.arange(n)))
    all_choices = [list(c) for c in itertools.product([0, 1], repeat=n)]

    history, angles, rows = [], None, []
    was_on = [int(x["on_at_start"]) for x in plants]
    for t in range(len(demand)):
        t0 = time.perf_counter()
        if not use_credit:
            credit = np.zeros(n)
        elif plan is not None:
            credit = plan_credit(plants, plan, t, lookahead, credit_weight)
        else:
            credit = necessity_credit(plants, need, t, lookahead, credit_weight)
        must_on, must_off = locks(plants, history)
        # Feasibility locks: a plant that is on must stay on if switching it off (with its min down time)
        # would leave some later hour short even with every other available plant on.
        for j in range(n):
            if was_on[j] and j not in must_on:
                all_but_j = [0 if i == j or i in must_off else 1 for i in range(n)]
                if future_shortfall(plants, history, need, t, all_but_j) > 0:
                    must_on.append(j)
        c = plant_hour_costs(plants, was_on, starter_formula)
        source, job_id, sim_valid = "exact", None, None
        fut_cache = {}

        def fut(ch):
            k = tuple(ch)
            if k not in fut_cache:
                fut_cache[k] = future_shortfall(plants, history, need, t, ch)
            return fut_cache[k]

        def valid(ch):
            return hour_ok(plants, demand[t], reserve[t], ch, must_on, must_off) and fut(ch) == 0

        def violation(ch):                                                        # 0 iff valid(ch)
            cap = sum(p["pmax_mw"] * u for p, u in zip(plants, ch))
            floor = sum(p["pmin_mw"] * u for p, u in zip(plants, ch))
            lock = sum(1 - ch[i] for i in must_on) + sum(ch[i] for i in must_off)
            return max(0.0, need[t] - cap) + max(0.0, floor - demand[t]) + 1e4 * lock + fut(ch)

        if sampler == "exact":
            seen, samples = all_choices, None
        else:
            if qaoa is not None:
                Q, offset = build_qubo(c, plants, demand[t], reserve[t], block_mw, n_slack, penalty_k * c.max())
                Q[np.arange(n), np.arange(n)] -= credit                          # look-ahead term
                Q, offset = add_locks(Q, offset, must_on, must_off, weight=2 * c.max())
                angles, probs, measured = qaoa.run(Q, offset, p=p, start=angles, maxiter=maxiter)
            else:                                                                 # random guessing
                probs, measured = np.full(2 ** nq, 1 / 2 ** nq), None
            if runner is not None and t in device_hours:
                counts, job_id, _ = runner.sample(t, measured)
                samples = counts_to_samples(counts, nq)
                source = "device"
                pc = np.bincount(plant_index, weights=probs, minlength=2 ** n)  # ideal, for comparison
                sim_valid = sum(pc[k] for k in range(2 ** n) if valid([(k >> i) & 1 for i in range(n)]))
            else:
                samples = rng.choice(len(probs), size=shots, p=probs / probs.sum())
                source = "simulator" if qaoa is not None else "random"
            seen = [[(k >> i) & 1 for i in range(n)] for k in np.unique(plant_index[samples])]

        def score(ch):                                                            # same credit as the QUBO
            return hour_cost(plants, demand[t], ch, was_on) - float(np.dot(credit, ch))

        def key(ch):                                  # valid first, then cheapest
            v = violation(ch)
            return (v > 0, v, score(ch))

        note = ""
        sample_pick = min(seen, key=key)              # best sampled choice (valid if any sample is)
        pick = sample_pick
        if valid(pick):
            if use_local_search and sampler != "exact":
                pick = local_search(pick, key, n)
                if pick != sample_pick:
                    note = "improved by local search"
        else:                                         # no valid sample: repair instead of breaking a rule
            pick = local_search(pick, key, n)
            note = "no valid sample: repaired by local search"
            if not valid(pick):
                if n <= 16:
                    pick = min(all_choices, key=key)
                    note = "no valid sample: enumerated all choices"
                if not valid(pick):
                    note = "no valid choice exists this hour"

        best = min((ch for ch in all_choices if valid(ch)), key=score, default=None) if n <= 16 else None
        valid_share = None if samples is None else float(np.mean(
            [valid([(k >> i) & 1 for i in range(n)]) for k in plant_index[samples]]))
        cost = hour_cost(plants, demand[t], pick, was_on)
        rows.append(dict(hour=t, pick=pick, cost=cost, credit=credit, note=note, source=source, job_id=job_id,
                         valid_share=valid_share, sim_valid=sim_valid, is_best=pick == best,
                         sample_was_best=sample_pick == best,
                         secs=time.perf_counter() - t0))
        if verbose:
            on = "+".join(pl["plant_id"] for pl, u in zip(plants, pick) if u) or "none"
            cr = ", ".join(f"{pl['plant_id']} ${v:,.0f}" for pl, v in zip(plants, credit) if v)
            dev = ""
            if source == "device":
                dev = f"  [device: {valid_share:.0%} valid shots vs {sim_valid:.0%} ideal]"
            print(f"  hour {t:>2}  need {need[t]:>6.0f} MW  {on:<34} ${cost:>10,.0f}"
                  + (f"  credit: {cr}" if cr else "") + dev + (f"  [{note}]" if note else ""), flush=True)
        history.append(pick)
        was_on = pick
    return np.array(history), rows


# ------------------------------------------------------------------ main
def parse_hours(spec, n_hours):
    if spec is None or spec == "all":
        return set(range(n_hours))
    hours = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        hours.update(range(int(a), int(b or a) + 1))
    bad = [h for h in hours if not 0 <= h < n_hours]
    if bad:
        sys.exit(f"--hours: {bad} outside 0..{n_hours - 1}")
    return hours


def main():
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plants", default=here / "data" / "plants.csv", help="plants CSV (default: data/plants.csv)")
    ap.add_argument("--demand", default=here / "data" / "demand.csv", help="demand CSV (default: data/demand.csv)")
    ap.add_argument("--p", type=int, default=1, help="QAOA layers (default 1; keep 1 on hardware)")
    ap.add_argument("--shots", type=int, default=200, help="samples per hour (default 200)")
    ap.add_argument("--seed", type=int, default=7, help="sampling seed for the local simulator (default 7)")
    ap.add_argument("--sampler", choices=["qaoa", "random", "exact"], default="qaoa",
                    help="qaoa (default), random guessing, or exact (try every choice, no QAOA)")
    ap.add_argument("--device", nargs="?", const=DEFAULT_DEVICE, default=None, metavar="DEVICE_ID",
                    help=f"sample on a qBraid device instead of the local simulator; "
                         f"--device alone = {DEFAULT_DEVICE}")
    ap.add_argument("--hours", default=None,
                    help="hours to send to --device, e.g. 14 or 12-15 or 5,14 (default: all); "
                         "the other hours use the local simulator")
    ap.add_argument("--noise-model", default="forte-1",
                    help="noise model for devices that offer one, e.g. the IonQ simulator "
                         "(default forte-1; 'none' for ideal)")
    ap.add_argument("--jobs-log", default="qaoa_jobs.json", help="job log for resuming (default qaoa_jobs.json)")
    ap.add_argument("--timeout", type=int, default=3600, help="seconds to wait for each device job (default 3600)")
    ap.add_argument("--yes", action="store_true", help="don't ask before submitting to a paid device")
    ap.add_argument("--no-credit", action="store_true", help="turn off the look-ahead credit")
    ap.add_argument("--credit-rule", choices=["plan", "necessity"], default="plan",
                    help="plan (default): credit plants the cheapest future plan wants within L hours; "
                         "necessity: only plants the fleet can't do without")
    ap.add_argument("--no-local-search", action="store_true",
                    help="use the best sample as is (no classical polishing; repair still runs if no sample is valid)")
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
    if a.sampler == "qaoa" and n_qubits > 20:
        print(f"warning: {n_qubits} qubits means a 2^{n_qubits} statevector per step; this will be slow.")

    runner, device_hours = None, set()
    if a.device:
        if a.sampler != "qaoa":
            sys.exit("--device needs --sampler qaoa (the default).")
        device_hours = parse_hours(a.hours, len(demand))
        runner = DeviceRunner(a.device, a.shots, a.noise_model, a.jobs_log, a.timeout)
        to_submit = [t for t in sorted(device_hours) if str(t) not in runner.log["hours"]]
        total, per_task, per_shot, per_min = runner.cost_estimate(len(to_submit))
        print(f"Device {a.device} ({runner.status()}), hours {sorted(device_hours)}, {a.shots} shots/job"
              + (f", noise model {runner.noise_model}" if runner.noise_model else ""))
        print(f"New jobs to submit: {len(to_submit)}. Estimated cost: {total:,.0f} credits "
              f"({per_task:g}/job + {per_shot:g}/shot)" + (f" + {per_min:g}/minute" if per_min else ""))
        if total > 0 and not a.yes:
            if not sys.stdin.isatty():
                sys.exit("Paid device and no terminal to confirm: rerun with --yes to submit.")
            if input("Submit these paid jobs? [y/N] ").strip().lower() not in ("y", "yes"):
                sys.exit("Cancelled, nothing submitted.")

    print(f"{len(plants)} plants, {len(demand)} hours, sampler={a.sampler}"
          + (f", p={a.p}, shots={a.shots}, {n_qubits} qubits" if a.sampler != "exact" else "")
          + (", no credit" if a.no_credit else f", {a.credit_rule} credit L={a.lookahead} w={a.credit_weight}"))

    t0 = time.perf_counter()
    schedule, rows = schedule_day(plants, demand, reserve, p=a.p, shots=a.shots, sampler=a.sampler, seed=a.seed,
                                  use_credit=not a.no_credit, lookahead=a.lookahead, credit_weight=a.credit_weight,
                                  block_mw=a.block_mw, n_slack=a.slack_bits, penalty_k=a.penalty,
                                  starter_formula=a.starter_costs, maxiter=a.maxiter, runner=runner,
                                  device_hours=device_hours, use_local_search=not a.no_local_search,
                                  credit_rule=a.credit_rule, verbose=not a.quiet)
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
    violations = list(res["violations"])
    if violations:
        print(f"{len(violations)} rule(s) broken:")
        for v in violations:
            print("  ", v)
    else:
        print("All rules satisfied.")
    if a.sampler != "exact":
        n_best = sum(r["sample_was_best"] for r in rows)
        n_ls = sum(r["note"] == "improved by local search" for r in rows)
        n_rep = sum(r["note"].startswith("no valid sample") for r in rows)
        print(f"Best sample was already the best choice in {n_best}/{len(rows)} hours; "
              f"local search improved {n_ls}, repaired {n_rep}.")

    dev_rows = [r for r in rows if r["source"] == "device"]
    if dev_rows:
        print(f"\nDevice run on {a.device}:")
        print(f"  {'hour':>4} {'job ID':<40} {'valid shots':>12} {'ideal':>7}  best choice picked?")
        for r in dev_rows:
            print(f"  {r['hour']:>4} {str(r['job_id']):<40} {r['valid_share']:>12.0%} {r['sim_valid']:>7.0%}  "
                  f"{'yes' if r['is_best'] else 'no'}")
        print(f"  Job IDs are saved in {a.jobs_log}.")

    if a.out:
        with open(a.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["hour"] + [p["plant_id"] for p in plants] + ["hour_cost", "samples_from", "job_id"])
            for r in rows:
                w.writerow([r["hour"]] + list(r["pick"]) + [round(r["cost"], 2), r["source"], r["job_id"] or ""])
        print(f"Schedule written to {a.out}")


if __name__ == "__main__":
    main()
