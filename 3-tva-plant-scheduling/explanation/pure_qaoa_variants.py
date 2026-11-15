#!/usr/bin/env python3
"""Is figure 01's rule breaking caused by our "pure QAOA" set-up, by the QUBO, or by QAOA itself?

Runs the hour-by-hour loop with NO classical rule checking (best-QUBO-energy sample is used as is),
changing one thing at a time:
  locks    add check.locks' min up/down penalties to the QUBO (quantum-side, as the starter's QAOA does)
  shots    200 (figure 01) vs more
  p        QAOA layers
  slack    slack qubits: enough for every hour (figure 01) vs the starter's 3
  exact    replace QAOA by the QUBO's exact minimum (a perfect sampler), to separate QUBO from QAOA
Also records per hour how flat the QUBO landscape is after QAOA's 0..1 rescaling.

  PY=~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python
  $PY explanation/pure_qaoa_variants.py      # -> results/variants.json, printout results/variants.log
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from check import check_schedule, hour_ok, locks, solve_milp  # noqa: E402
import run_qaoa_schedule as RQ  # noqa: E402
from run_experiments import fleet, n_slack_bits, n_slack_bits_full  # noqa: E402


def day(plants, d, r, n_slack, use_locks=False, shots=200, p=1, sampler="qaoa", seed=0, maxiter=60):
    n = len(plants)
    nq = n + n_slack
    qa = RQ.QAOA(nq)
    bits = qa.bits
    choice = bits[:, :n] @ (2 ** np.arange(n))
    rng = np.random.default_rng(seed)
    was_on = [int(x["on_at_start"]) for x in plants]
    sched, angles, hours = [], None, []
    for t in range(len(d)):
        c = RQ.plant_hour_costs(plants, was_on)
        Q, off = RQ.build_qubo(c, plants, d[t], r[t], 50, n_slack, 2.0 * c.max())
        must_on, must_off = locks(plants, sched)
        if use_locks:
            Q, off = RQ.add_locks(Q, off, must_on, must_off, weight=2 * c.max())
        E = qa.energies(Q, off)
        En = (E - E.min()) / (E.max() - E.min())
        h = dict(hour=t, near_min=int((En < 0.01).sum()))
        # gap between the QUBO's best choice and the 2nd-best distinct on/off choice, after rescaling
        best_per_choice = np.full(2 ** n, np.inf)
        np.minimum.at(best_per_choice, choice, En)
        srt = np.sort(best_per_choice)
        h["best_vs_2nd"] = float(srt[1] - srt[0])
        if sampler == "exact":
            k = int(np.argmin(E))
        else:
            angles, probs, _ = qa.run(Q, off, p=p, start=angles if angles is not None and len(angles) == 2 * p
                                      else None, maxiter=maxiter)
            s = rng.choice(len(probs), size=shots, p=probs / probs.sum())
            k = int(s[np.argmin(E[s])])
            h.update(exp_En=float(probs @ En), exp_En_uniform=float(En.mean()),
                     p_ground=float(probs[np.argmin(E)]), hit_ground=bool(np.isclose(E[k], E.min())))
        pick = [int(b) for b in bits[k, :n]]
        h["locks_broken"] = sum(1 - pick[i] for i in must_on) + sum(pick[i] for i in must_off)
        h["hour_ok"] = bool(hour_ok(plants, d[t], r[t], pick))
        hours.append(h)
        sched.append(pick)
        was_on = pick
    return np.array(sched), hours


VARIANTS = [
    ("fig 01 (pure, 200 shots, p=1)",       dict()),
    ("pure, starter's 3 slack bits",         dict(slack3=True)),
    ("pure, 2000 shots",                    dict(shots=2000)),
    ("pure, p=3",                           dict(p=3)),
    ("locks in QUBO, 200 shots",             dict(use_locks=True)),
    ("locks in QUBO, 2000 shots",            dict(use_locks=True, shots=2000)),
    ("locks in QUBO, p=3, 2000 shots",       dict(use_locks=True, p=3, shots=2000)),
    ("exact QUBO min, no locks",             dict(sampler="exact")),
    ("exact QUBO min + locks",               dict(sampler="exact", use_locks=True)),
]


def main():
    out = []
    for n in (5, 10):
        plants, d, r = fleet(n)
        milp_cost, *_ = solve_milp(plants, d, r)
        ns_full = n_slack_bits_full(plants, d, r)
        print(f"\n===== {n} plants (slack bits {ns_full}; starter uses 3)", flush=True)
        for name, kw in VARIANTS:
            kw = dict(kw)
            ns = 3 if kw.pop("slack3", False) else ns_full
            for seed in (0, 1, 2) if kw.get("sampler") != "exact" else (0,):
                t0 = time.perf_counter()
                s, hours = day(plants, d, r, ns, seed=seed, **kw)
                res = check_schedule(plants, d, r, s, milp_cost=milp_cost, verbose=False)
                kinds = Counter("min up/down" if "min" in v[2] and ("up" in v[2] or "down" in v[2]) else v[2]
                                for v in res["violations"])
                row = dict(n=n, variant=name, seed=seed, qubits=n + ns, gap=res["gap_pct"],
                           broken=len(res["violations"]), kinds=dict(kinds),
                           hours_bad=sum(not h["hour_ok"] for h in hours),
                           lock_hours=sum(h["locks_broken"] > 0 for h in hours), per_hour=hours,
                           secs=time.perf_counter() - t0)
                out.append(row)
            rows = [x for x in out if x["n"] == n and x["variant"] == name]
            hit = [np.mean([h["hit_ground"] for h in x["per_hour"]]) for x in rows if "hit_ground" in x["per_hour"][0]]
            print(f"  {name:<34} qubits {rows[0]['qubits']:>2}  gap {np.mean([x['gap'] for x in rows]):+7.2f}%  "
                  f"broken {np.mean([x['broken'] for x in rows]):5.1f}  "
                  f"capacity/min-output bad hours {np.mean([x['hours_bad'] for x in rows]):4.1f}  "
                  + (f"best sample = QUBO min {np.mean(hit):.0%} of hours" if hit else ""), flush=True)
        # landscape flatness (from the first variant, seed 0)
        h0 = [x for x in out if x["n"] == n and x["variant"] == VARIANTS[0][0] and x["seed"] == 0][0]["per_hour"]
        print(f"  landscape (fig 01 run): bitstrings within 1% of min energy, median {np.median([h['near_min'] for h in h0]):.0f}; "
              f"best vs 2nd-best on/off choice, median {np.median([h['best_vs_2nd'] for h in h0]):.4f} of the range; "
              f"<E> QAOA {np.mean([h['exp_En'] for h in h0]):.3f} vs uniform {np.mean([h['exp_En_uniform'] for h in h0]):.3f}; "
              f"P(QUBO min) {np.mean([h['p_ground'] for h in h0]):.5f} vs uniform {1 / 2 ** (n + ns_full):.5f}",
              flush=True)
        (HERE / "results").mkdir(exist_ok=True)
        (HERE / "results" / "variants.json").write_text(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main()
