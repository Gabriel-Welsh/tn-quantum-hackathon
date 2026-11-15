#!/usr/bin/env python3
"""Why did our first "pure QAOA" break so many rules when the starter's QAOA doesn't?

Runs the hour-by-hour loop four ways (3 slack qubits, QAOA p=1, 200 shots, seed 0), adding the
starter's two ingredients one at a time:
  A  no locks, best-energy sample   the first figure 01: one-hour QUBO = costs + capacity penalty only,
                                    keep the sample with the lowest QUBO energy        (pure_qaoa_day)
  B  + locks in the QUBO            add check.locks' min up/down penalties to the QUBO, still keep
                                    the lowest-energy sample (quantum side only)
  C  + pick the cheapest VALID      the starter's schedule_day: among the samples keep the cheapest
     sample (starter formulation)   by exact cost that passes hour_ok with the locks  (starter_qaoa_day)
  D  + rule checking                run_qaoa_schedule.schedule_day, credit off: adds the feasibility
                                    look-ahead and local-search repair
Prints every rule C still breaks, with the hour, so the cause can be read off.

  PY=~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python
  $PY explanation/diagnose_pure_qaoa.py      # 5, 6 and 10 plants -> results/diagnose.json (+ .log)
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scheduling"))
sys.path.insert(0, str(HERE))

from check import check_schedule, locks, solve_milp  # noqa: E402
import run_qaoa_schedule as RQ  # noqa: E402
from run_experiments import fleet, n_slack_bits, pure_qaoa_day, starter_qaoa_day  # noqa: E402

SEED, SHOTS = 0, 200


def locks_energy_pick_day(plants, d, r, ns, seed=SEED, shots=SHOTS):
    """B: QUBO with lock penalties, lowest-QUBO-energy sample kept (no classical validity check)."""
    n = len(plants)
    qa = RQ.QAOA(n + ns)
    rng = np.random.default_rng(seed)
    was_on = [int(x["on_at_start"]) for x in plants]
    sched, angles = [], None
    for t in range(len(d)):
        must_on, must_off = locks(plants, sched)
        c = RQ.plant_hour_costs(plants, was_on)
        Q, off = RQ.build_qubo(c, plants, d[t], r[t], 50, ns, 2.0 * c.max())
        Q, off = RQ.add_locks(Q, off, must_on, must_off, weight=2 * c.max())
        angles, probs, _ = qa.run(Q, off, p=1, start=angles, maxiter=60)
        s = rng.choice(len(probs), size=shots, p=probs / probs.sum())
        E = qa.energies(Q, off)
        k = int(s[np.argmin(E[s])])
        pick = [int((k >> i) & 1) for i in range(n)]
        sched.append(pick)
        was_on = pick
    return np.array(sched)


def startups(plants, s):
    return int(((s[1:] == 1) & (s[:-1] == 0)).sum() +
               sum(1 for i, p in enumerate(plants) if s[0][i] and not p["on_at_start"]))


def kind(v):
    return "min up/down" if ("min up" in v[2] or "min down" in v[2]) else v[2]


def main():
    out = {}
    for n in (5, 6, 10):
        plants, d, r = fleet(n)
        ns = n_slack_bits(plants, d, r)
        milp_cost, milp_sched, *_ = solve_milp(plants, d, r)
        m = check_schedule(plants, d, r, milp_sched, verbose=False)
        out[n] = {"MILP": dict(gap=0.0, broken=0, cost=milp_cost, startup_cost=m["startup_cost"],
                               no_load_cost=m["no_load_cost"], energy_cost=m["energy_cost"],
                               startups=startups(plants, milp_sched))}
        print(f"\n===== {n} plants ({n + ns} qubits/hour), MILP ${milp_cost:,.0f}", flush=True)
        runs = {
            "A": lambda: pure_qaoa_day(plants, d, r, SEED, ns),
            "B": lambda: locks_energy_pick_day(plants, d, r, ns),
            "C": lambda: starter_qaoa_day(plants, d, r, SEED, ns),
            "D": lambda: RQ.schedule_day(plants, d, r, p=1, shots=SHOTS, seed=SEED, use_credit=False,
                                         n_slack=ns, verbose=False)[0],
        }
        for mode, fn in runs.items():
            s = fn()
            res = check_schedule(plants, d, r, s, milp_cost=milp_cost, verbose=False)
            out[n][mode] = dict(gap=res["gap_pct"], broken=len(res["violations"]),
                                kinds=dict(Counter(kind(v) for v in res["violations"])),
                                startups=startups(plants, s), cost=res["total_cost"],
                                startup_cost=res["startup_cost"], no_load_cost=res["no_load_cost"],
                                energy_cost=res["energy_cost"],
                                schedule=s.tolist(), violations=[list(map(str, v)) for v in res["violations"]])
            print(f"  {mode}: gap {res['gap_pct']:+7.2f}%  broken {len(res['violations']):>2}  "
                  f"{out[n][mode]['kinds']}  startups {out[n][mode]['startups']}", flush=True)
        for v in out[n]["C"]["violations"]:
            print("     C breaks:", v)
        if out[n]["C"]["violations"]:
            names = [p["plant_id"] for p in plants]
            need = d + r
            print("     C schedule around the breaks (hour, need MW, plants on):")
            hrs = sorted({int(v[0]) for v in out[n]["C"]["violations"]})
            for t in range(max(0, hrs[0] - 6), min(24, hrs[-1] + 2)):
                on = "+".join(nm for nm, u in zip(names, out[n]["C"]["schedule"][t]) if u)
                print(f"       {t:>2}  {need[t]:>6.0f}  {on}")
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "diagnose.json").write_text(json.dumps(out, indent=1, default=float))
    print("\nsaved results/diagnose.json")


if __name__ == "__main__":
    main()
