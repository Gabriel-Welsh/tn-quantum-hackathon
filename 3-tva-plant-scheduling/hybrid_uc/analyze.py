"""Benchmark behind RESULTS.md.

    python -m hybrid_uc.analyze            (about 30 minutes; writes hybrid_uc/RESULTS.md and results.json)
    python -m hybrid_uc.analyze --resume   reuse sections already saved in results.json, run only the missing ones

A  real 5-plant fleet, base day: incentive mode x sampler x shots, before and after repair
B  real fleet on other demand curves (does it generalize?)
C  larger synthetic fleets with QAOA (8, 12, 16 plants = 11, 15, 19 qubits per hour)
D  classical stages only at scale (10 to 200 plants) vs the MILP: gap, certificate, time
E  shots to solution: QAOA vs random at 10-200 shots for 5, 8, 12 plants
"""
import contextlib
import io
import json
import os
import time

import numpy as np

import check
from . import fleet, incentives, pipeline, repair

HERE = os.path.dirname(os.path.abspath(__file__))


def gap(plants, D, R, s, milp):
    r = check.check_schedule(plants, D, R, s, milp_cost=milp, verbose=False)
    return (r["gap_pct"] if r["gap_pct"] is not None else np.nan), len(r["violations"])


def one_run(plants, D, R, inc, milp, mode, sampler, shots, seed):
    t0 = time.perf_counter()
    s, log = pipeline.run_day(plants, D, R, inc, mode=mode, sampler=sampler, shots=shots, seed=seed)
    t_hourly = time.perf_counter() - t0
    g0, b0 = gap(plants, D, R, s, milp)
    t0 = time.perf_counter()
    s2, rep = repair.repair(plants, D, R, s, inc.lower_bound, milp)
    t_rep = time.perf_counter() - t0
    g1, b1 = gap(plants, D, R, s2, milp)
    pp = [r["p_pick"] for r in log if r["p_pick"] is not None]
    return dict(mode=mode, sampler=sampler, shots=shots, seed=seed, gap_before=g0, broken_before=b0,
                gap_after=g1, broken_after=b1, repair_moves=len(rep["changes"]),
                p_pick=float(np.mean(pp)) if pp else None, t_hourly=t_hourly, t_repair=t_rep)


def summarize(runs):
    v0 = [r["gap_before"] for r in runs if r["broken_before"] == 0]
    v1 = [r["gap_after"] for r in runs if r["broken_after"] == 0]
    pp = [r["p_pick"] for r in runs if r["p_pick"] is not None]
    return dict(n=len(runs), valid_before=len(v0), mean_gap_before=float(np.mean(v0)) if v0 else np.nan,
                valid_after=len(v1), mean_gap_after=float(np.mean(v1)) if v1 else np.nan,
                worst_gap_after=float(np.max(v1)) if v1 else np.nan,
                moves=float(np.mean([r["repair_moves"] for r in runs])),
                p_pick=float(np.mean(pp)) if pp else None,
                t_hourly=float(np.mean([r["t_hourly"] for r in runs])))


def cell(s, before=True):
    k = "before" if before else "after"
    m = s[f"mean_gap_{k}"]
    return f"{s[f'valid_{k}']}/{s['n']}, {m:+.2f}%" if not np.isnan(m) else f"{s[f'valid_{k}']}/{s['n']}"


def checkpoint(out):
    """Save finished sections as we go, so a crash later doesn't lose them."""
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)


def main(resume=False):
    out, md = {}, []
    path = os.path.join(HERE, "results.json")
    prev = json.load(open(path)) if resume and os.path.exists(path) else {}
    T0 = time.time()
    D0, R0 = check.load_demand()
    real = fleet.load_fleet(os.path.join(os.path.dirname(HERE), "data", "plants.csv"))
    say = lambda *a: print(*a, flush=True)

    # ---------------------------------------------------------------- A
    if "A" in prev:
        milp, lower_bound, rows = prev["A"]["milp"], prev["A"]["lower_bound"], prev["A"]["rows"]
        out["A"] = prev["A"]
        say("A: reused from results.json")
    else:
        say("A: real fleet, base day")
        milp = check.solve_milp(real, D0, R0)[0]
        inc = incentives.lagrangian(real, D0, R0)
        lr_rep = repair.repair(real, D0, R0, inc.schedule)[0]
        g, b = gap(real, D0, R0, lr_rep, milp)
        rows = [dict(mode="lagrangian", sampler="classical only (no sampler)", shots="-",
                     **summarize([dict(gap_before=gap(real, D0, R0, inc.schedule, milp)[0],
                                       broken_before=gap(real, D0, R0, inc.schedule, milp)[1],
                                       gap_after=g, broken_after=b, repair_moves=0, p_pick=None, t_hourly=0.0)]))]
        for mode in ["none", "amortize", "lagrangian"]:
            ex = one_run(real, D0, R0, inc, milp, mode, "exact", 0, 0)
            rows.append(dict(mode=mode, sampler="exact (all 32)", shots="-", **summarize([ex])))
            for shots in [20, 50, 200]:
                for smp in ["qaoa", "random"]:
                    runs = [one_run(real, D0, R0, inc, milp, mode, smp, shots, s) for s in range(5)]
                    rows.append(dict(mode=mode, sampler=smp, shots=shots, **summarize(runs)))
                    say(f"  {mode:<10} {smp:<6} {shots:>4}: {cell(rows[-1])} -> {cell(rows[-1], False)}")
        out["A"] = dict(milp=milp, lower_bound=inc.lower_bound, rows=rows)
        checkpoint(out)
        lower_bound = inc.lower_bound
    md += ["## A. Real 5-plant fleet, base day", "",
           f"MILP optimum ${milp:,.0f}. Lagrangian lower bound ${lower_bound:,.0f} "
           f"({100 * (milp - lower_bound) / milp:.2f}% below the optimum). 5 seeds per sampled row. "
           "Cells: valid days / runs, mean gap of the valid ones. P(pick) = probability the sampler gave the choice kept.", "",
           "| incentives | sampler | shots | before repair | after repair | worst after | repair moves | P(pick) |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        pp = "-" if r["p_pick"] is None else f"{r['p_pick']:.3f}"
        md.append(f"| {r['mode']} | {r['sampler']} | {r['shots']} | {cell(r)} | {cell(r, False)} | "
                  f"{r['worst_gap_after']:+.2f}% | {r['moves']:.1f} | {pp} |")

    # ---------------------------------------------------------------- B
    if "B" in prev:
        brows, skipped = prev["B"]["rows"], prev["B"]["skipped"]
        out["B"] = prev["B"]
        say("B: reused from results.json")
    else:
        say("B: real fleet, other demand curves")
        noise = np.random.default_rng(3).normal(0, 0.05, len(D0))
        variants = {"demand x0.70": (D0 * .7, R0 * .7), "demand x0.85": (D0 * .85, R0 * .85),
                    "demand x1.05": (D0 * 1.05, R0 * 1.05), "peak 3 h earlier": (np.roll(D0, -3), np.roll(R0, -3)),
                    "base +5% noise": (D0 * (1 + noise), R0 * (1 + noise)),
                    "base +5% noise (seed 4)": tuple(x * (1 + np.random.default_rng(4).normal(0, .05, len(D0))) for x in (D0, R0))}
        brows = []
        skipped = []
        for name, (D, R) in variants.items():
            try:
                m = check.solve_milp(real, D, R)[0]
            except RuntimeError:
                skipped.append(name)
                say(f"  {name}: skipped, no feasible schedule exists (the MILP says infeasible)")
                continue
            ic = incentives.lagrangian(real, D, R)
            ex = summarize([one_run(real, D, R, ic, m, "lagrangian", "exact", 0, 0)])
            q = summarize([one_run(real, D, R, ic, m, "lagrangian", "qaoa", 50, s) for s in range(5)])
            rd = summarize([one_run(real, D, R, ic, m, "lagrangian", "random", 50, s) for s in range(5)])
            cl = gap(real, D, R, repair.repair(real, D, R, ic.schedule)[0], m)
            brows.append(dict(name=name, milp=m, lb=ic.lower_bound, exact=ex, qaoa=q, random=rd, classical=cl))
            say(f"  {name:<24} exact {cell(ex)}->{cell(ex, False)}  qaoa50 {cell(q)}->{cell(q, False)}  random50 {cell(rd)}->{cell(rd, False)}")
        out["B"] = dict(rows=brows, skipped=skipped)
        checkpoint(out)
    md += ["", "## B. Real fleet, other demand curves (Lagrangian incentives)", "",
           "| demand curve | MILP $ | exact, before -> after repair | QAOA 50 shots, before -> after | random 50 shots, before -> after | classical only (Lagrangian + repair) |",
           "|---|---|---|---|---|---|"]
    for r in brows:
        md.append(f"| {r['name']} | {r['milp']:,.0f} | {cell(r['exact'])} -> {cell(r['exact'], False)} | "
                  f"{cell(r['qaoa'])} -> {cell(r['qaoa'], False)} | {cell(r['random'])} -> {cell(r['random'], False)} | "
                  f"{r['classical'][0]:+.2f}%{'' if r['classical'][1] == 0 else ' (broken)'} |")
    if skipped:
        md += ["", f"Skipped (no feasible schedule exists, per the MILP): {', '.join(skipped)}."]

    # ---------------------------------------------------------------- C
    if "C" in prev:
        crows = prev["C"]
        out["C"] = prev["C"]
        say("C: reused from results.json")
    else:
        say("C: larger fleets with QAOA")
        crows = []
        for n in [8, 12, 16]:
            pl = fleet.synthetic_fleet(n, seed=1)
            D, R = fleet.scaled_demand(pl, D0, R0)
            m, _, _, ms = check.solve_milp(pl, D, R)
            ic = incentives.lagrangian(pl, D, R)
            row = dict(n=n, qubits=n + 3, milp=m, milp_s=ms, lb=ic.lower_bound)
            g0, b0 = gap(pl, D, R, ic.schedule, m)
            g1, b1 = gap(pl, D, R, repair.repair(pl, D, R, ic.schedule)[0], m)
            row["lr_only"] = summarize([dict(gap_before=g0, broken_before=b0, gap_after=g1, broken_after=b1,
                                             repair_moves=0, p_pick=None, t_hourly=0.0)])
            if n <= 12:
                row["exact"] = summarize([one_run(pl, D, R, ic, m, "lagrangian", "exact", 0, 0)])
            for shots in [50, 200]:
                for smp in ["qaoa", "random"]:
                    seeds = range(2) if n >= 16 else range(3)
                    row[f"{smp}{shots}"] = summarize([one_run(pl, D, R, ic, m, "lagrangian", smp, shots, s) for s in seeds])
                    say(f"  N={n} {smp} {shots}: {cell(row[f'{smp}{shots}'])} -> {cell(row[f'{smp}{shots}'], False)}  "
                        f"P(pick) {row[f'{smp}{shots}']['p_pick']:.4f}  {row[f'{smp}{shots}']['t_hourly']:.0f} s/day")
            crows.append(row)
        out["C"] = crows
        checkpoint(out)
    md += ["", "## C. Larger synthetic fleets with QAOA (Lagrangian incentives, 3 seeds; 2 at 16 plants)", "",
           "Qubits per hour is the maximum; plants that min up/down already fix are set classically, so most hours use fewer.", "",
           "Before -> after repair. P(pick) at 200 shots: average probability the sampler gave the choice kept "
           "(random samples only the plants not fixed by min up/down, so its P is above 1 / 2^N).", "",
           "| plants | qubits/hour | MILP s | Lagrangian schedule alone -> repaired | exact per hour | QAOA 50 | random 50 | QAOA 200 | random 200 | QAOA P(pick) | random P(pick) | ratio |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in crows:
        ex = f"{cell(r['exact'])} -> {cell(r['exact'], False)}" if "exact" in r else "too many choices"
        md.append(f"| {r['n']} | {r['qubits']} | {r['milp_s']:.2f} | {cell(r['lr_only'])} -> {cell(r['lr_only'], False)} | {ex} | "
                  + " | ".join(f"{cell(r[k])} -> {cell(r[k], False)}" for k in ["qaoa50", "random50", "qaoa200", "random200"])
                  + f" | {r['qaoa200']['p_pick']:.4f} | {r['random200']['p_pick']:.4f} | "
                    f"{r['qaoa200']['p_pick'] / max(r['random200']['p_pick'], 1e-12):.1f}x |")

    # ---------------------------------------------------------------- D
    if "D" in prev:
        drows = prev["D"]
        out["D"] = prev["D"]
        say("D: reused from results.json")
    else:
        say("D: classical stages at scale")
        drows = []
        for n in [10, 25, 50, 100, 200]:
            pl = fleet.synthetic_fleet(n, seed=1)
            D, R = fleet.scaled_demand(pl, D0, R0)
            t = time.perf_counter(); ic = incentives.lagrangian(pl, D, R); t_lr = time.perf_counter() - t
            t = time.perf_counter(); s, rep = repair.repair(pl, D, R, ic.schedule, ic.lower_bound); t_rep = time.perf_counter() - t
            cost, broken = repair.Scorer(pl, D, R).total(s)
            ic2 = incentives.lagrangian(pl, D, R, upper_bound=cost, start=(ic.lam, ic.mu))
            lb = max(ic.lower_bound, ic2.lower_bound)
            t = time.perf_counter(); m = check.solve_milp(pl, D, R)[0]; t_m = time.perf_counter() - t
            drows.append(dict(n=n, t_lr=t_lr, t_repair=t_rep, moves=len(rep["changes"]), broken=broken,
                              gap=100 * (cost - m) / m, certified=100 * (cost - lb) / lb, lr_gap=100 * (m - lb) / m,
                              t_milp=t_m, qubits=n + 3))
            say(f"  N={n}: gap {drows[-1]['gap']:+.3f}%  certified {drows[-1]['certified']:+.2f}%  LR {t_lr:.1f}s repair {t_rep:.1f}s MILP {t_m:.1f}s")
        out["D"] = drows
        checkpoint(out)
    md += ["", "## D. Classical stages only, at scale (Lagrangian schedule + repair, no QAOA)", "",
           "| plants | qubits/hour if QAOA | gap vs MILP | certified gap (no MILP needed) | bound vs optimum | broken | Lagrangian s | repair s | MILP s |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in drows:
        md.append(f"| {r['n']} | {r['qubits']} | {r['gap']:+.3f}% | {r['certified']:+.2f}% | {r['lr_gap']:.2f}% | {r['broken']} | "
                  f"{r['t_lr']:.1f} | {r['t_repair']:.1f} | {r['t_milp']:.1f} |")

    # ---------------------------------------------------------------- E
    if "E" in prev:
        erows = prev["E"]
        out["E"] = prev["E"]
        say("E: reused from results.json")
    else:
        say("E: shots to solution")
        erows = []
        for n in [5, 8, 12]:
            pl = real if n == 5 else fleet.synthetic_fleet(n, seed=1)
            D, R = (D0, R0) if n == 5 else fleet.scaled_demand(pl, D0, R0)
            m = check.solve_milp(pl, D, R)[0]
            ic = incentives.lagrangian(pl, D, R)
            for shots in [10, 25, 50, 100, 200]:
                for smp in ["qaoa", "random"]:
                    sm = summarize([one_run(pl, D, R, ic, m, "lagrangian", smp, shots, s) for s in range(3)])
                    erows.append(dict(plants=n, shots=shots, sampler=smp, **sm))
                    say(f"  N={n} {smp} {shots}: {cell(sm)} -> {cell(sm, False)}")
        out["E"] = erows
        checkpoint(out)
    md += ["", "## E. Shots to solution (Lagrangian incentives, 3 seeds)", "",
           "How many shots per hour each sampler needs. Before repair isolates the sampler; after repair is the full pipeline.", "",
           "| plants | shots/hour | QAOA before repair | random before repair | QAOA after repair | random after repair |",
           "|---|---|---|---|---|---|"]
    for n in [5, 8, 12]:
        for shots in [10, 25, 50, 100, 200]:
            q = next(r for r in erows if r["plants"] == n and r["shots"] == shots and r["sampler"] == "qaoa")
            rd = next(r for r in erows if r["plants"] == n and r["shots"] == shots and r["sampler"] == "random")
            md.append(f"| {n} | {shots} | {cell(q)} | {cell(rd)} | {cell(q, False)} | {cell(rd, False)} |")

    md.insert(0, f"# Hybrid unit commitment: benchmark results\n\nGenerated by `python -m hybrid_uc.analyze` "
                 f"in {time.time() - T0:.0f} s.\n")
    with open(os.path.join(HERE, "RESULTS.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    say(f"done in {time.time() - T0:.0f} s")


if __name__ == "__main__":
    import sys
    with contextlib.redirect_stderr(io.StringIO()):
        main(resume="--resume" in sys.argv)
