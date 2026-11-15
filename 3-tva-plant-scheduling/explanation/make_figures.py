#!/usr/bin/env python3
"""Turn explanation/results/*.json (from run_experiments.py) into the PNG figures in explanation/figures/.

  PY=~/.qbraid/environments/qbraid_r7ts/pyenv/bin/python
  $PY explanation/make_figures.py

Figure                               Data file        Made by run_experiments.py ...
01_pure_qaoa_vs_milp.png             pure.json        pure
02_rule_checking.png                 pure.json        pure
03_hour_grouping.png                 blocks.json      blocks
04_qubit_growth.png                  qubits.json      qubits
05_warm_start_timeline.png           warm.json        warm
06_warm_start_metrics.png            warm.json        warm
07_summary.png                       pure/blocks/warm  (all of the above)
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
OUT = HERE / "figures"

# reference categorical palette (light mode), fixed order; text and grid in neutral inks
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
    "lines.linewidth": 2, "lines.markersize": 7, "legend.frameon": False,
})


def load(name):
    p = RES / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("wrote", OUT / name)


def agg(rows, key, **match):
    """Mean and min/max of `key` over seeds, per fleet size, for rows matching **match."""
    ns = sorted({r["n"] for r in rows})
    m, lo, hi = [], [], []
    for n in ns:
        v = [r[key] for r in rows if r["n"] == n and all(r.get(k) == x for k, x in match.items())]
        m.append(np.mean(v)), lo.append(np.min(v)), hi.append(np.max(v))
    return np.array(ns), np.array(m), np.array(lo), np.array(hi)


def note(fig, text, y=-0.02):
    fig.text(0.01, y, text, ha="left", va="top", fontsize=8.5, color=INK2, wrap=True)


# ------------------------------------------------------------------ 1 + 2
def fig_pure(rows):
    ns, gap, glo, ghi = agg(rows, "gap", method="pure")
    _, brk, blo, bhi = agg(rows, "broken", method="pure")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    a1.axhline(0, color=BLUE, lw=2)
    a1.text(ns[0], 0.6, "MILP optimum (0%)", color=INK2, fontsize=9)
    a1.fill_between(ns, glo, ghi, color=ORANGE, alpha=0.15, lw=0)
    a1.plot(ns, gap, "o-", color=ORANGE, label="pure QAOA, hour by hour")
    a1.set(xlabel="number of plants", ylabel="daily cost vs MILP optimum (%)",
           title="Pure QAOA: cost gap to the MILP")
    a1.legend(loc="upper left")
    a2.fill_between(ns, blo, bhi, color=ORANGE, alpha=0.15, lw=0)
    a2.plot(ns, brk, "o-", color=ORANGE)
    a2.set(xlabel="number of plants", ylabel="rules broken in the day",
           title="Pure QAOA: broken rules (invalid schedules)")
    for a in (a1, a2):
        a.set_xticks(ns)
    note(fig, "Pure QAOA = one-hour QUBO (costs + capacity penalty with slack qubits), QAOA p=1 on an exact "
              "statevector, 200 shots, lowest-energy sample kept; no lock, feasibility check or repair. Line = mean "
              "of 3 seeds, band = min-max. A negative gap is not a win: those schedules break rules (right panel), "
              "so they are not allowed. Fleet = first N plants of plants10.csv, demand scaled to capacity.")
    save(fig, "01_pure_qaoa_vs_milp.png")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    for method, col, lab in [("pure", ORANGE, "pure QAOA"), ("rules", AQUA, "QAOA + rule checking")]:
        ns, g, lo, hi = agg(rows, "gap", method=method)
        a1.fill_between(ns, lo, hi, color=col, alpha=0.15, lw=0)
        a1.plot(ns, g, "o-", color=col, label=lab)
        ns, b, lo, hi = agg(rows, "broken", method=method)
        a2.plot(ns, b, "o-", color=col, label=lab)
    a1.axhline(0, color=BLUE, lw=2, label="MILP optimum")
    a1.set(xlabel="number of plants", ylabel="daily cost vs MILP optimum (%)",
           title="Adding rule checking: cost gap")
    a2.set(xlabel="number of plants", ylabel="rules broken in the day (mean of 3 seeds)",
           title="Adding rule checking: broken rules")
    a1.legend(loc="best")
    a2.legend(loc="best")
    for a in (a1, a2):
        a.set_xticks(ns)
    note(fig, "Rule checking (run_qaoa_schedule.schedule_day, credit off): min up/down locks added to the QUBO, a "
              "look-ahead check that switching a plant off can't leave a later hour short, only valid samples "
              "may be picked (cheapest by exact cost), then classical local search / repair. Every schedule is "
              "valid, but the hour-by-hour view still can't see startups that pay off later, so a gap remains.")
    save(fig, "02_rule_checking.png")


# ------------------------------------------------------------------ 3
def fig_blocks(rows, pure_rows):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), sharey=False)
    cols = {2: BLUE, 3: AQUA, 4: VIOLET, 6: MAGENTA, 24: RED}
    for K in sorted({r["K"] for r in rows}):
        sub = sorted([r for r in rows if r["K"] == K], key=lambda r: r["n"])
        lab = "full 24-hour QUBO (annealing)" if K == 24 else f"K = {K} blocks"
        ns = [r["n"] for r in sub]
        a1.plot(ns, [r["raw_gap"] for r in sub], "o-", color=cols[K], label=lab)
        a2.plot(ns, [r["gap"] for r in sub], "o-", color=cols[K], label=lab)
    if pure_rows:
        ns, g, _, _ = agg(pure_rows, "gap", method="rules")
        a2.plot(ns, g, "s--", color=INK2, lw=1.5, label="hour by hour + rule checking")
    for a in (a1, a2):
        a.axhline(0, color=GRID, lw=1)
        a.set_xlabel("number of plants")
        a.set_xticks(range(3, 11))
    a1.set(ylabel="daily cost vs MILP optimum (%)", title="Grouped hours: QUBO answer as is")
    a2.set(ylabel="daily cost vs MILP optimum (%)", title="Grouped hours: after classical polish")
    h, l = a2.get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=6, fontsize=8.5)
    broken = [r for r in rows if r["raw_broken"]]
    note(fig, "block_qubo.py: hours grouped into K blocks of flat demand, one bit per plant per block, startups and "
              "min up/down in the QUBO. QAOA p=1 when the QUBO has <= 16 qubits, else simulated annealing on the same "
              "QUBO (marked solver in results/blocks.json). Full 24-hour QUBO = run_all_24h_qaoa_schedule.py "
              "(one bit per plant per hour + helpers), annealing only. Polish = local search moving block edges hour "
              f"by hour. {len(broken)} of {len(rows)} raw answers broke at least one rule; see results/blocks.json.", y=-0.09)
    save(fig, "03_hour_grouping.png")


# ------------------------------------------------------------------ 4
def fig_qubits(rows):
    rows = [r for r in rows if r["n"] >= 3]      # at 2 plants presolve fixes every block bit (0 qubits)
    ns = [r["n"] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw=dict(wspace=0.35))
    series = [("hourly", "one hour (8+ qubits, 24 separate runs)", ORANGE),
              ("K2", "K = 2 blocks", BLUE), ("K4", "K = 4 blocks", AQUA), ("K6", "K = 6 blocks", VIOLET),
              ("K12", "K = 12 blocks", MAGENTA), ("day24", "full 24-hour QUBO", RED)]
    for key, lab, col in series:
        q = [r[key] for r in rows]
        a1.plot(ns, q, "o-", color=col, label=lab)
        a2.plot(ns, [qq * np.log10(2) for qq in q], "o-", color=col, label=lab)
    a1.axhline(20, color=INK2, lw=1, ls="--")
    a1.text(10.3, 20, "~20: exact\nsimulation\nlimit", color=INK2, fontsize=8, va="center", clip_on=False)
    a1.axhspan(100, 1000, color=GRID, alpha=0.5, lw=0)
    a1.text(10.3, 300, "100+: too many\nto run reliably\non today's QPUs", color=INK2, fontsize=8, va="center", clip_on=False)
    a1.set_yscale("log")
    a1.set(xlabel="number of plants", ylabel="qubits (log scale)", title="Qubits per QUBO", ylim=(1, 1000))
    h, l = a1.get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=6, fontsize=8.5)
    a2.axhline(np.log10(2 ** 30), color=INK2, lw=1, ls="--")
    a2.text(10.3, np.log10(2 ** 30), "2^30 =\n16 GB\nstatevector", color=INK2, fontsize=8, va="center", clip_on=False)
    a2.set(xlabel="number of plants", ylabel="log10(number of bitstrings = 2^qubits)",
           title="Search space 2^qubits grows exponentially")
    for a in (a1, a2):
        a.set_xticks(ns)
    note(fig, "Counts from the project's own QUBO builders (run_qaoa_schedule.build_qubo with enough slack bits, "
              "block_qubo.BlockQubo after presolve, run_all_24h_qaoa_schedule.build_day_qubo), no solving. Each "
              "extra plant adds a fixed number of qubits per time step, so qubits grow linearly in plants x time "
              "steps, and the state space a QAOA circuit must explore (2^qubits) grows exponentially. Block counts "
              "can dip because presolve fixes bits no valid schedule can change.", y=-0.09)
    save(fig, "04_qubit_growth.png")


# ------------------------------------------------------------------ 5 + 6
def fig_warm(rows):
    fig, axes = plt.subplots(1, len(rows), figsize=(3.1 * len(rows), 3.6), sharey=True)
    for a, row in zip(axes, rows):
        opt = row["opt"]
        for mode, col in [("cold", INK2), ("warm", ORANGE)]:
            run = row["runs"][mode][0]
            tl = run["timeline"]
            T = run["seconds"]
            xs, ys = [0.0], [np.nan]
            if mode == "warm":
                ys = [100 * (row["warm_start_cost"] - opt) / opt]
            for t, c in tl:
                xs += [t, t]
                ys += [ys[-1], 100 * (c - opt) / opt]
            xs.append(T)
            ys.append(100 * (run["objective"] - opt) / opt)
            a.plot(np.array(xs) * 1000, ys, color=col, lw=2,
                   label="cold start" if mode == "cold" else "quantum warm start")
            a.plot([T * 1000], [ys[-1]], "o", color=col, ms=6)
        a.set_title(f"{row['n']} plants ({row['qubits']} qubits, {row['solver']})", fontsize=10)
        a.set_xlabel("HiGHS time (ms)")
        a.set_xlim(left=0)
    axes[0].set_ylabel("best known schedule vs optimum (%)")
    axes[0].legend(loc="upper right", fontsize=8)
    note(fig, "Best schedule HiGHS knows over time (seed 0). Cold: nothing until HiGHS finds its own first answer, "
              "which is often far from optimal. Warm: the repaired quantum schedule (QAOA for 5 and 10 plants, "
              "annealing on the same block QUBO for 20+) is known from t = 0 at 1-2% from optimal. Dot = proof of "
              "optimality, solve ends. Fleets: quantum_warm_start_milp.bigger_fleet copies of the 5-plant fleet.")
    save(fig, "05_warm_start_timeline.png")

    ns = [r["n"] for r in rows]
    med = lambda r, m, k: float(np.median([x[k] for x in r["runs"][m]]))
    x = np.arange(len(rows))
    w = 0.38
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(14, 4.1))
    for a, key, title, ylab in [(a1, "seconds", "Time to proven optimum", "seconds (median of 3)"),
                                (a2, "pdi", "Primal-dual integral (lower = better)", "gap x time")]:
        c = [med(r, "cold", key) for r in rows]
        wv = [med(r, "warm", key) for r in rows]
        a.bar(x - w / 2 - 0.01, c, w, color=INK2, label="cold start")
        a.bar(x + w / 2 + 0.01, wv, w, color=ORANGE, label="quantum warm start")
        for i, (cc, ww) in enumerate(zip(c, wv)):
            a.text(i + w / 2, ww, f"-{100 * (1 - ww / cc):.0f}%", ha="center", va="bottom", fontsize=8, color=INK)
        a.set(xticks=x, xticklabels=ns, xlabel="number of plants", ylabel=ylab, title=title)
        a.title.set_fontsize(10.5)
        a.legend(loc="upper left", fontsize=8)
    def t_within(run, opt, start_cost=None, tol=2.5):
        """ms until HiGHS knows a schedule within tol% of the optimum (0 if the start already is)."""
        if start_cost is not None and 100 * (start_cost - opt) / opt <= tol:
            return 0.0
        for t, c in run["timeline"]:
            if 100 * (c - opt) / opt <= tol:
                return 1000 * t
        return 1000 * run["seconds"]
    c = [np.median([t_within(x, r["opt"]) for x in r["runs"]["cold"]]) for r in rows]
    wv = [np.median([t_within(x, r["opt"], r["warm_start_cost"]) for x in r["runs"]["warm"]]) for r in rows]
    a3.bar(x - w / 2 - 0.01, c, w, color=INK2, label="cold start")
    a3.bar(x + w / 2 + 0.01, wv, w, color=ORANGE, label="quantum warm start")
    for i, ww in enumerate(wv):
        a3.text(i + w / 2, ww, f"{ww:.0f}", ha="center", va="bottom", fontsize=8, color=INK)
    a3.set(xticks=x, xticklabels=ns, xlabel="number of plants", ylabel="milliseconds (median of 3)",
           title="Time until within 2.5% of optimal")
    a3.title.set_fontsize(10.5)
    a3.legend(loc="upper left", fontsize=8)
    note(fig, "Same runs as figure 05, medians over 3 HiGHS seeds, 1 thread. On this data HiGHS proves optimality at "
              "the root node (1 branch-and-bound node) for every fleet, so there is little search tree to prune and "
              "the total-time saving is modest; the clear win is having a near-optimal schedule from second zero "
              "(right: 0 ms with the warm start). Bigger savings need MILPs that branch (ramp limits, longer horizons).")
    save(fig, "06_warm_start_metrics.png")


# ------------------------------------------------------------------ 7
def fig_summary(pure, blocks, warm):
    labels, vals, cols, notes = [], [], [], []
    n = 10
    if pure:
        for m, lab, col in [("pure", "pure QAOA\n(hour by hour)", ORANGE),
                            ("rules", "+ rule checking", AQUA)]:
            v = [r for r in pure if r["n"] == n and r["method"] == m]
            labels.append(lab), vals.append(np.mean([r["gap"] for r in v])), cols.append(col)
            notes.append(f"{np.mean([r['broken'] for r in v]):.0f} rules broken")
    if blocks:
        valid = [r for r in blocks if r["n"] == n and not r.get("full_day") and r["broken"] == 0]
        if valid:
            best = min(valid, key=lambda r: r["gap"])
            labels.append(f"grouped hours\n(K={best['K']}, polished)"), vals.append(best["gap"]), cols.append(VIOLET)
            notes.append(f"{best['qubits']} qubits, {best['solver']}")
        day = [r for r in blocks if r["n"] == n and r.get("full_day")]
        if day:
            labels.append("full 24-hour\nQUBO (polished)"), vals.append(day[0]["gap"]), cols.append(RED)
            notes.append(f"{day[0]['qubits']} qubits, anneal")
    if warm:
        r = [x for x in warm if x["n"] == n][0]
        labels.append("quantum start\n(before HiGHS)"), cols.append(YELLOW)
        vals.append(100 * (r["warm_start_cost"] - r["opt"]) / r["opt"]), notes.append(f"{r['qubits']} qubits, {r['solver']}")
        labels.append("HiGHS from\nquantum start"), vals.append(0.0), cols.append(BLUE), notes.append("proven optimal")
    fig, a = plt.subplots(figsize=(10, 4))
    x = np.arange(len(vals))
    a.bar(x, vals, 0.6, color=cols)
    for i, (v, t) in enumerate(zip(vals, notes)):
        a.text(i, max(v, 0) + 0.15, f"{v:+.2f}%\n{t}", ha="center", va="bottom", fontsize=8.5)
    a.axhline(0, color=MUTED, lw=1)
    a.set(xticks=x, xticklabels=labels, ylabel="daily cost vs MILP optimum (%)",
          title=f"The path we took ({n} plants)")
    a.set_ylim(top=max(vals) * 1.3 + 1)
    note(fig, "Each step from the earlier figures, on the 10-plant fleet. Gaps of schedules that break rules are not "
              "comparable (they skip required cost). Only the warm-started MILP is both valid and proven optimal.")
    save(fig, "07_summary.png")


def main():
    pure, blocks, qubits, warm = (load(k) for k in ("pure", "blocks", "qubits", "warm"))
    if pure:
        fig_pure(pure)
    if blocks:
        fig_blocks(blocks, pure)
    if qubits:
        fig_qubits(qubits)
    if warm:
        fig_warm(warm)
    fig_summary(pure, blocks, warm)


if __name__ == "__main__":
    main()
