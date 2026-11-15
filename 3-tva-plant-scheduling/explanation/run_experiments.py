#!/usr/bin/env python3
"""Re-run every experiment behind the figures in explanation/ and save the numbers as JSON.

Each experiment reuses the project's own code (check.py, run_qaoa_schedule.py, block_qubo.py,
run_all_24h_qaoa_schedule.py, quantum_warm_start_milp.py); nothing here changes those files.
All quantum steps are simulated locally (exact statevector). No jobs are submitted, no credits used.

Fleets: the first N plants of data/plants10.csv (N = 3..10), with data/demand10.csv scaled by
(capacity of those N plants) / (capacity of all 10), reserve = 10% of demand. N = 5 reproduces
data/plants.csv + data/demand.csv exactly (MILP optimum $327,924), N = 10 is the 10-plant file.

Usage (run from the 3-tva-plant-scheduling folder with the qBraid-SDK environment's Python):
  PY=~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python
  $PY explanation/run_experiments.py pure     # 1. hour-by-hour QAOA (starter formulation) vs + rule checking
  $PY explanation/run_experiments.py blocks   # 2. hours grouped into K blocks + the full 24-hour QUBO
  $PY explanation/run_experiments.py qubits   # 3. qubit counts of every formulation (no solving)
  $PY explanation/run_experiments.py warm     # 4. HiGHS cold vs quantum warm start
  $PY explanation/run_experiments.py all      # everything (about 30-60 minutes)
Results go to explanation/results/<name>.json; explanation/make_figures.py turns them into PNGs.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from check import check_schedule, hour_cost, hour_ok, load_demand, load_plants, locks, solve_milp  # noqa: E402
import run_qaoa_schedule as RQ  # noqa: E402
import block_qubo as BQ  # noqa: E402
import run_all_24h_qaoa_schedule as R24  # noqa: E402

RESULTS = HERE / "results"
SIZES = list(range(3, 11))           # plants per fleet
SEEDS = [0, 1, 2]                    # sampling seeds for the hour-by-hour runs
SHOTS = 200


# ------------------------------------------------------------------ fleets
def fleet(n):
    """First n plants of the 10-plant file, demand scaled to their capacity."""
    plants = load_plants(ROOT / "data" / "plants10.csv")
    demand, _ = load_demand(ROOT / "data" / "demand10.csv")
    cap_all = sum(p["pmax_mw"] for p in plants)
    sub = plants[:n]
    d = np.round(demand * sum(p["pmax_mw"] for p in sub) / cap_all)
    return sub, d, np.round(0.1 * d)


SLACK_BITS = 3   # the starter's and run_qaoa_schedule.py's default: spare capacity 0..7 blocks of 50 MW


def n_slack_bits(plants, demand, reserve, block_mw=50):
    """Slack qubits for the one-hour QUBO: always the starter's 3.

    The first version of this study used n_slack_bits_full (below), which adds slack bits until the
    capacity penalty can be exactly zero even with every plant on (5 bits at 10 plants, so 15 qubits).
    That was a mistake: every extra qubit doubles the search space QAOA has to cover with the same
    200 shots, and it also removes the penalty's push against switching on far more capacity than needed.
    With 3 bits, choices with more than 7 spare blocks pay a small penalty, which is the intended bias."""
    return SLACK_BITS


def n_slack_bits_full(plants, demand, reserve, block_mw=50):
    """(Old, kept for the before/after comparison.) Slack bits so the penalty can be zero in every hour."""
    total = sum(p["pmax_mw"] for p in plants) / block_mw
    spare = max(total - math.ceil((d + r) / block_mw) for d, r in zip(demand, reserve))
    return max(1, int(math.floor(spare)).bit_length())


def save(name, obj):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps(obj, indent=1, default=float))
    print(f"saved {RESULTS / name}.json", flush=True)


# ------------------------------------------------------------------ 1. pure QAOA vs rule checking
def pure_qaoa_day(plants, demand, reserve, seed, n_slack, shots=SHOTS, p=1, maxiter=60):
    """(Earlier, incorrect "pure QAOA" of figure 01 - kept for reference, used by the diagnosis scripts.)
    Hour-by-hour QAOA with NO classical rule checking: each hour, build the one-hour QUBO
    (costs + capacity penalty, the starter's formulation), tune QAOA, sample `shots` times and keep the
    sample with the lowest QUBO energy. No min up/down locks, no feasibility check, no repair."""
    n = len(plants)
    nq = n + n_slack
    qa = RQ.QAOA(nq)
    rng = np.random.default_rng(seed)
    was_on = [int(x["on_at_start"]) for x in plants]
    sched, angles = [], None
    for t in range(len(demand)):
        c = RQ.plant_hour_costs(plants, was_on)
        Q, off = RQ.build_qubo(c, plants, demand[t], reserve[t], 50, n_slack, 2.0 * c.max())
        angles, probs, _ = qa.run(Q, off, p=p, start=angles, maxiter=maxiter)
        samples = rng.choice(len(probs), size=shots, p=probs / probs.sum())
        E = qa.energies(Q, off)
        k = samples[np.argmin(E[samples])]
        pick = [int((k >> i) & 1) for i in range(n)]
        sched.append(pick)
        was_on = pick
    return np.array(sched)


def starter_qaoa_day(plants, demand, reserve, seed, n_slack, shots=SHOTS, p=1, maxiter=60):
    """Hour-by-hour QAOA exactly as starter.ipynb's schedule_day does it (the project's QAOA formulation):
      QUBO   = plant costs + capacity penalty (3 slack qubits) + min up/down LOCK penalties from check.locks,
               so the one-hour QUBO knows which plants earlier hours force on or off;
      QAOA   p=1, angles warm-started from the previous hour, `shots` samples;
      pick   the cheapest sampled on/off choice that is VALID this hour (hour_ok with the locks),
             by exact hour_cost. If no sample is valid: one that only breaks a lock; else the most common.
    No look-ahead, no local search, no repair (those are what "rule checking" adds)."""
    n = len(plants)
    nq = n + n_slack
    qa = RQ.QAOA(nq)
    plant_index = qa.bits[:, :n] @ (2 ** np.arange(n))
    rng = np.random.default_rng(seed)
    was_on = [int(x["on_at_start"]) for x in plants]
    history, angles = [], None
    for t in range(len(demand)):
        must_on, must_off = locks(plants, history)
        c = RQ.plant_hour_costs(plants, was_on)
        Q, off = RQ.build_qubo(c, plants, demand[t], reserve[t], 50, n_slack, 2.0 * c.max())
        Q, off = RQ.add_locks(Q, off, must_on, must_off, weight=2 * c.max())
        angles, probs, _ = qa.run(Q, off, p=p, start=angles, maxiter=maxiter)
        samples = rng.choice(len(probs), size=shots, p=probs / probs.sum())
        seen = [[int((k >> i) & 1) for i in range(n)] for k in np.unique(plant_index[samples])]
        ok = [ch for ch in seen if hour_ok(plants, demand[t], reserve[t], ch, must_on, must_off)]
        if not ok:
            ok = [ch for ch in seen if hour_ok(plants, demand[t], reserve[t], ch)]
        if ok:
            pick = min(ok, key=lambda ch: hour_cost(plants, demand[t], ch, was_on))
        else:
            k = int(np.bincount(plant_index[samples]).argmax())
            pick = [int((k >> i) & 1) for i in range(n)]
        history.append(pick)
        was_on = pick
    return np.array(history)


def exp_pure():
    rows = []
    for n in SIZES:
        plants, d, r = fleet(n)
        milp_cost, *_ = solve_milp(plants, d, r)
        ns = n_slack_bits(plants, d, r)
        for seed in SEEDS:
            for method in ("qaoa", "rules"):
                t0 = time.perf_counter()
                if method == "qaoa":      # the starter's QAOA formulation (figure 01)
                    s = starter_qaoa_day(plants, d, r, seed, ns)
                else:   # the project's loop: locks + feasibility look-ahead + valid pick + local-search repair
                    s, _ = RQ.schedule_day(plants, d, r, p=1, shots=SHOTS, sampler="qaoa", seed=seed,
                                           use_credit=False, use_local_search=True, n_slack=ns,
                                           verbose=False)
                secs = time.perf_counter() - t0
                res = check_schedule(plants, d, r, s, milp_cost=milp_cost, verbose=False)
                rows.append(dict(n=n, seed=seed, method=method, qubits=n + ns, milp_cost=milp_cost,
                                 cost=res["total_cost"], gap=res["gap_pct"],
                                 broken=len(res["violations"]), secs=secs))
                print(f"pure  n={n:>2} seed={seed} {method:<5} qubits={n + ns:>2} gap {res['gap_pct']:+7.2f}% "
                      f"broken {len(res['violations']):>2}  ({secs:.0f} s)", flush=True)
        save("pure", rows)


# ------------------------------------------------------------------ 2. grouping hours into blocks
BLOCK_KS = [2, 3, 4, 6]
QAOA_LIMIT = 16                      # largest block QUBO simulated with QAOA; bigger ones use annealing


def exp_blocks():
    rows = []
    for n in SIZES:
        plants, d, r = fleet(n)
        bmw = R24.default_block(plants)
        milp_cost, *_ = solve_milp(plants, d, r)
        for K in BLOCK_KS:
            blocks = BQ.make_blocks(plants, d, r, K, "dp")
            nq = BQ.BlockQubo(plants, d, r, blocks, bmw).N
            solver = "qaoa" if nq <= QAOA_LIMIT else "anneal"
            t0 = time.perf_counter()
            out = BQ.run(plants, d, r, blocks, bmw, solver=solver, p=1, shots=1000, seed=7, verbose=False)
            rows.append(dict(n=n, K=K, qubits=out["qubits"], solver=solver, milp_cost=milp_cost,
                             block_milp_cost=out["block_milp_cost"], raw_gap=out["raw_gap"],
                             raw_broken=out["raw_broken"], gap=out["gap"], broken=out["broken"],
                             secs=time.perf_counter() - t0))
            print(f"block n={n:>2} K={K} {solver:<6} qubits={out['qubits']:>3} raw {out['raw_gap']:+7.2f}% "
                  f"({out['raw_broken']} broken) -> polished {out['gap']:+7.2f}% ({out['broken']} broken)",
                  flush=True)
        # the full 24-hour QUBO (every plant, every hour, one problem): far too many qubits for QAOA,
        # so it is solved with simulated annealing on the same QUBO, as run_all_24h_qaoa_schedule.py does
        qb, info = R24.build_day_qubo(plants, d, r, bmw)
        Q, off = qb.matrix()
        score = R24.Scorer(plants, d, r)
        scale = info["c"].max() + max(p["startup_cost"] for p in plants)
        t0 = time.perf_counter()
        raw, _ = R24.anneal_x(R24.XEnergy(plants, info, len(d)), 300, 8, 7, t_hot=scale, t_cold=1.0)
        r0 = check_schedule(plants, d, r, raw, milp_cost=milp_cost, verbose=False)
        final = R24.polish(raw, score)
        r1 = check_schedule(plants, d, r, final, milp_cost=milp_cost, verbose=False)
        rows.append(dict(n=n, K=24, full_day=True, qubits=len(Q), solver="anneal", milp_cost=milp_cost,
                         raw_gap=r0["gap_pct"], raw_broken=len(r0["violations"]), gap=r1["gap_pct"],
                         broken=len(r1["violations"]), secs=time.perf_counter() - t0))
        print(f"day   n={n:>2} full 24h  qubits={len(Q):>4} raw {r0['gap_pct']:+7.2f}% "
              f"({len(r0['violations'])} broken) -> polished {r1['gap_pct']:+7.2f}%", flush=True)
        save("blocks", rows)


# ------------------------------------------------------------------ 3. qubit counts
def exp_qubits():
    rows = []
    for n in range(2, 11):
        plants, d, r = fleet(n)
        bmw = R24.default_block(plants)
        row = dict(n=n, hourly=n + n_slack_bits(plants, d, r))
        for K in [2, 3, 4, 6, 8, 12]:
            row[f"K{K}"] = BQ.BlockQubo(plants, d, r, BQ.make_blocks(plants, d, r, K, "dp", min_len=1), bmw).N
        qb, _ = R24.build_day_qubo(plants, d, r, bmw)
        row["day24"] = len(qb.names)
        rows.append(row)
        print("qubits", row, flush=True)
    save("qubits", rows)


# ------------------------------------------------------------------ 4. warm start for the MILP
WARM_COPIES = [1, 2, 4, 8, 16]       # copies of the 5-plant fleet: 5, 10, 20, 40, 80 plants
WARM_REPEATS = 3


def highs_with_timeline(W, model, start, seed, time_limit=120.0):
    """quantum_warm_start_milp.run_highs, plus the full list of (seconds, cost) improvements."""
    import highspy
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.setOptionValue("time_limit", time_limit)
    h.setOptionValue("random_seed", int(seed))
    h.setOptionValue("threads", 1)
    h.passModel(model.to_highs())
    timeline, t0 = [], [0.0]
    h.cbMipImprovingSolution.subscribe(
        lambda e: timeline.append((time.perf_counter() - t0[0], float(e.data_out.objective_function_value))))
    if start is not None:
        sol = highspy.HighsSolution()
        sol.col_value = list(map(float, start))
        sol.value_valid = True
        h.setSolution(sol)
    t0[0] = time.perf_counter()
    h.run()
    secs = time.perf_counter() - t0[0]
    info = h.getInfo()
    return dict(seconds=secs, objective=info.objective_function_value, nodes=int(info.mip_node_count),
                pdi=info.primal_dual_integral, timeline=timeline,
                status=h.modelStatusToString(h.getModelStatus()))


def exp_warm():
    import quantum_warm_start_milp as W
    P = W.load_plants(ROOT / "data" / "plants.csv")
    d0, r0 = W.load_demand(ROOT / "data" / "demand.csv")
    rows = []
    for copies in WARM_COPIES:
        plants, d, r = W.bigger_fleet(P, d0, r0, copies, 0)
        n, T = len(plants), len(d)
        model = W.Milp(plants, d, r)
        K = 4 if n <= 5 else (2 if n <= 10 else 4)
        blocks = W.split_into_blocks(d + r, K)
        qubo = W.Qubo(plants, d, r, blocks)
        solver = "qaoa" if qubo.N <= 20 else "anneal"
        quiet = lambda *a, **k: None
        if solver == "qaoa":
            cands, q_secs = W.solve_qaoa(qubo, p=2, shots=4000, seed=0, sampler="numpy", log=quiet)
        else:
            cands, q_secs = W.solve_anneal(qubo, seed=0, log=quiet)
        best_S, best_cost = None, math.inf
        for x in cands[:50]:
            S = W.repair(model, qubo.to_schedule(x, T))
            if S is not None and (c := W.true_cost(model, S)) < best_cost:
                best_S, best_cost = S, c
        start = W.full_solution(model, best_S)
        runs = {m: [highs_with_timeline(W, model, None if m == "cold" else start, seed)
                    for seed in range(WARM_REPEATS)] for m in ("cold", "warm")}
        opt = min(x["objective"] for rs in runs.values() for x in rs)
        rows.append(dict(n=n, copies=copies, qubits=qubo.N, solver=solver, K=K, quantum_s=q_secs,
                         warm_start_cost=best_cost, opt=opt, runs=runs))
        med = lambda m, k: float(np.median([x[k] for x in runs[m]]))
        print(f"warm  n={n:>2} {solver:<6} {qubo.N:>3} qubits  start {100 * (best_cost - opt) / opt:+.2f}%  "
              f"time {med('cold', 'seconds'):.3f}->{med('warm', 'seconds'):.3f}s  "
              f"PDI {med('cold', 'pdi'):.3f}->{med('warm', 'pdi'):.3f}  "
              f"nodes {med('cold', 'nodes'):.0f}->{med('warm', 'nodes'):.0f}", flush=True)
        save("warm", rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["pure", "blocks", "qubits", "warm", "all"])
    a = ap.parse_args()
    todo = ["qubits", "warm", "blocks", "pure"] if a.what == "all" else [a.what]
    for w in todo:
        print(f"\n=== {w} ===", flush=True)
        globals()[f"exp_{w}"]()


if __name__ == "__main__":
    main()
