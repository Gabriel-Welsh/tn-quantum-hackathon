"""Notebook interface: enter a fleet, run the hybrid (incentives + QAOA + repair), compare with the MILP.

In a notebook (qBraid-SDK kernel):
    from hybrid_uc.ui import show
    show()

solve() does the work and can be called without widgets.
"""
import io
import os
import time

import numpy as np

import check
from . import fleet, incentives, pipeline, qaoa, repair

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_PLANTS = 16
# Rough timings measured on this Lab instance (one simulated day). Used only for the time estimate.
QAOA_SECONDS = {8: 0.7, 11: 1.5, 15: 15, 19: 70}        # QAOA sampling, by qubits per hour
REPAIR_SECONDS = {5: 3, 8: 12, 12: 60, 16: 150}         # one classical repair, by number of plants


def _interp(table, x):
    """Log-scale interpolation in a {size: seconds} table; doubles per step past the last entry."""
    known = sorted(table)
    if x <= known[0]:
        return table[known[0]]
    for a, b in zip(known, known[1:]):
        if x <= b:
            w = (x - a) / (b - a)
            return float(np.exp((1 - w) * np.log(table[a]) + w * np.log(table[b])))
    return table[known[-1]] * 2 ** (x - known[-1])


def estimate_seconds(n_plants, n_qubits, sampler, do_repair, compare_random):
    """Rough wall-clock estimate for one Run click: sampling plus every classical repair it performs."""
    sample = _interp(QAOA_SECONDS, n_qubits) if sampler == "qaoa" else 1.0
    repairs = (1 + (compare_random and sampler != "random") + 1) if do_repair else 0   # main, random, classical
    return sample + repairs * _interp(REPAIR_SECONDS, n_plants)


def solve(plants, demand, reserve, sampler="qaoa", shots=200, seed=7, p=1, do_repair=True, compare_random=False):
    """Run the whole pipeline. Returns a dict with costs, % errors vs the MILP and schedules."""
    plants = fleet.validate([dict(x) for x in plants])
    out = dict(n=len(plants), qubits=len(plants) + qaoa.encoding(plants)[2])
    t = time.perf_counter()
    milp_cost, milp_sched, _, _ = check.solve_milp(plants, demand, reserve)
    out.update(milp_cost=milp_cost, milp_schedule=milp_sched, t_milp=time.perf_counter() - t)

    t = time.perf_counter()
    inc = incentives.lagrangian(plants, demand, reserve)
    t_inc = time.perf_counter() - t

    def run(smp):
        t0 = time.perf_counter()
        if smp == "classical":          # reference: the Lagrangian schedule itself, no sampler
            sched, log = inc.schedule, []
        else:
            sched, log = pipeline.run_day(plants, demand, reserve, inc, sampler=smp, shots=shots, seed=seed, p=p)
        t_hourly = time.perf_counter() - t0 + t_inc
        before = check.check_schedule(plants, demand, reserve, sched, milp_cost=milp_cost, verbose=False)
        res = dict(sampler=smp, schedule_before=sched, log=log, before=before, t_hourly=t_hourly,
                   lower_bound=inc.lower_bound)
        if do_repair:
            t0 = time.perf_counter()
            final, rep = repair.repair(plants, demand, reserve, sched, inc.lower_bound, milp_cost)
            res.update(repair=rep, t_repair=time.perf_counter() - t0)
        else:
            final = sched
        res["schedule"] = final
        res["after"] = check.check_schedule(plants, demand, reserve, final, milp_cost=milp_cost, verbose=False)
        pp = [r["p_pick"] for r in log if r["p_pick"] is not None]
        res["p_pick"] = float(np.mean(pp)) if pp else None
        return res

    out["main"] = run(sampler)
    if compare_random and sampler != "random":
        out["random"] = run("random")
    if do_repair:
        out["classical"] = run("classical")
    return out


# ---------------------------------------------------------------- widgets
COLUMNS = [  # field, header, width, kind
    ("plant_id", "name", "110px", "text"),
    ("type", "type", "150px", "text"),
    ("pmin_mw", "pmin MW", "75px", "float"),
    ("pmax_mw", "pmax MW", "75px", "float"),
    ("marginal_cost_per_mwh", "$/MWh", "75px", "float"),
    ("no_load_cost_per_h", "no-load $/h", "85px", "float"),
    ("startup_cost", "startup $", "85px", "float"),
    ("min_up_h", "min up h", "70px", "float"),
    ("min_down_h", "min down h", "80px", "float"),
    ("on_at_start", "on at 0h", "65px", "bool"),
]


def figure_png(fig):
    """Render a figure to PNG bytes (white background) and close it. Independent of the matplotlib backend,
    which matters because plt.show() from a widget callback often draws nothing in JupyterLab."""
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def chart_widget(png, name):
    """Show PNG bytes as an <img> inside an HTML widget (renders in any frontend) and save a copy to
    hybrid_chart_<name>.png. Returns (widget, path)."""
    import base64
    import ipywidgets as W
    path = os.path.join(HERE, "outputs", f"hybrid_chart_{name}.png")
    with open(path, "wb") as f:
        f.write(png)
    src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    return W.HTML(f"<img src='{src}' alt='{name} chart' style='max-width:100%;height:auto;"
                  "background:white;display:block'/>"), path


RED = "<span style='color:#e05545'>{}</span>"      # mid-tone: readable on light and dark themes
GREEN = "<span style='color:#2ea44f'>{}</span>"
SECTION = "<h4 style='margin:16px 0 4px;border-bottom:1px solid rgba(128,128,128,0.4);padding-bottom:2px'>{}</h4>"


def rules_html(rows, label):
    """A 'rules check' section: every broken rule (hour, plant, rule, detail) in each final schedule."""
    import html as htmllib
    out = [SECTION.format("Rules check (final schedules)")]
    for r in rows:
        v = r["after"]["violations"]
        name = label[r["sampler"]]
        if not v:
            out.append(f"<p style='margin:2px 0'>{name}: <span style='color:#2ea44f'>no rules broken</span> "
                       "(demand, reserve and min up/down met every hour)</p>")
            continue
        out.append(f"<p style='margin:6px 0 2px'>{name}: <span style='color:#e05545'><b>{len(v)} rule(s) "
                   "broken</b></span></p><table style='border-collapse:collapse;font-size:12px'>"
                   "<tr>" + "".join(f"<th style='padding:2px 8px;text-align:left'>{h}</th>"
                                    for h in ["hour", "plant", "rule", "detail"]) + "</tr>")
        for t, pid, rule, detail in v[:40]:
            out.append("<tr>" + "".join(f"<td style='padding:2px 8px'>{htmllib.escape(str(c))}</td>"
                                        for c in [t, pid, rule, detail]) + "</tr>")
        out.append("</table>")
        if len(v) > 40:
            out.append(f"<p style='margin:2px 0;font-size:12px'>... and {len(v) - 40} more</p>")
    return "".join(out)


def show():
    import ipywidgets as W
    import matplotlib.pyplot as plt
    import html as htmllib
    import traceback
    from IPython.display import display

    real = fleet.load_fleet(os.path.join(HERE, "data", "plants.csv"))
    base_d, base_r = check.load_demand()
    state = dict(rows=[dict(p) for p in real], demand=(base_d, base_r), demand_name="data/demand.csv")

    n_plants = W.BoundedIntText(value=len(real), min=1, max=MAX_PLANTS, description="Plants:",
                                layout=W.Layout(width="160px"))
    preset = W.Dropdown(options=["TVA 5-plant fleet", "synthetic (from templates)"], value="TVA 5-plant fleet",
                        description="Reset table to:", style={"description_width": "initial"},
                        layout=W.Layout(width="330px"))
    fill_btn = W.Button(description="Reset", icon="undo", tooltip="Replace the table with the chosen preset")
    fleet_status = W.HTML()
    table_box = W.VBox()
    load_up = W.FileUpload(accept=".csv", multiple=False, description="Load fleet CSV")
    save_name = W.Text(value="my_fleet.csv", layout=W.Layout(width="160px"))
    save_btn = W.Button(description="Save fleet CSV", icon="save")
    demand_up = W.FileUpload(accept=".csv", multiple=False, description="Demand CSV")
    demand_lbl = W.HTML()
    demand_status = W.HTML()
    rescale = W.Checkbox(value=False, description="Scale demand to this fleet (peak = 90% of capacity)",
                         layout=W.Layout(width="420px"))
    sampler = W.ToggleButtons(options=[("QAOA", "qaoa"), ("random", "random"), ("exact (all choices)", "exact")],
                              value=None, description="Sampler:")
    shots = W.IntSlider(value=200, min=10, max=1000, step=10, description="Shots/hour:", continuous_update=False)
    seed = W.IntText(value=7, description="Seed:", layout=W.Layout(width="160px"))
    do_repair = W.Checkbox(value=True, description="Classical repair")
    compare = W.Checkbox(value=True, description="Also run random guessing (honesty check)",
                         layout=W.Layout(width="360px"))
    estimate = W.HTML()
    run_btn = W.Button(description="Run", button_style="primary", icon="play")
    results = W.VBox(layout=W.Layout(width="100%"))

    def make_row(p):
        cells = []
        for field, _, width, kind in COLUMNS:
            v = p.get(field, "")
            if kind == "text":
                w = W.Text(value=str(v), layout=W.Layout(width=width))
            elif kind == "bool":
                w = W.Checkbox(value=bool(float(v or 0)), indent=False, layout=W.Layout(width=width))
            else:
                w = W.FloatText(value=float(v or 0), layout=W.Layout(width=width))
            w.observe(lambda _: update_estimate(), "value")
            cells.append(w)
        return cells

    def render_table():
        header = W.HBox([W.HTML(f"<b>{h}</b>", layout=W.Layout(width=wd)) for _, h, wd, _ in COLUMNS])
        state["cells"] = [make_row(p) for p in state["rows"]]
        table_box.children = [header] + [W.HBox(c) for c in state["cells"]]
        update_estimate()

    def read_table():
        rows = []
        for cells in state["cells"]:
            p = {}
            for (field, _, _, kind), w in zip(COLUMNS, cells):
                p[field] = (1.0 if w.value else 0.0) if kind == "bool" else w.value
            rows.append(p)
        return rows

    def resize(_=None):
        """Change the number of rows. Rows removed by shrinking are kept and come back (with any edits)
        when the table grows again; only rows beyond those are filled from the templates."""
        rows = read_table() if "cells" in state else state["rows"]
        n = n_plants.value
        spare = state.setdefault("spare", [])
        if n < len(rows):
            state["spare"] = rows[n:] + spare
            rows = rows[:n]
        elif n > len(rows):
            back, state["spare"] = spare[:n - len(rows)], spare[n - len(rows):]
            rows = rows + back
            if n > len(rows):
                used = {r["plant_id"] for r in rows}
                extra = [p for p in fleet.synthetic_fleet(n + len(used), seed=1) if p["plant_id"] not in used]
                rows = rows + extra[:n - len(rows)]
        state["rows"] = rows
        render_table()

    def fill(_=None):
        state["spare"] = []
        n = n_plants.value
        if preset.value.startswith("TVA"):
            rows = [dict(p) for p in real][:n]
            if n > len(rows):
                rows += fleet.synthetic_fleet(n, seed=1)[len(rows):]
        else:
            rows = fleet.synthetic_fleet(n, seed=seed.value)
            rescale.value = True
        state["rows"] = rows
        render_table()

    def current_demand():
        D, R = state["demand"]
        if rescale.value:
            plants = fleet.validate(read_table())
            D, R = fleet.scaled_demand(plants, D, R)
        return D, R

    def sync_controls(_=None):
        """Grey out settings that do nothing for the chosen sampler."""
        shots.disabled = seed.disabled = sampler.value == "exact"
        compare.disabled = sampler.value == "random"
        update_estimate()

    def update_estimate(_=None):
        try:
            plants = fleet.validate(read_table())
        except Exception as err:          # noqa: BLE001 - show any input problem to the user
            estimate.value = f"<span style='color:#e05545'>Fleet problem: {err}</span>"
            return
        n, K = len(plants), qaoa.encoding(plants)[2]
        D, R = current_demand()
        cap = sum(p["pmax_mw"] for p in plants)
        msg = (f"{n} plants &rarr; <b>{n + K} qubits per hour</b> ({n} plants + {K} slack). "
               f"Capacity {cap:,.0f} MW, peak demand + reserve {(D + R).max():,.0f} MW. ")
        if (D + R).max() > cap:
            msg += "<span style='color:#e05545'>Capacity is below peak demand + reserve: no valid schedule. " \
                   "Add plants or tick 'Scale demand'.</span>"
        elif sampler.value is None:
            msg += "<span style='color:#b9770e'>Pick a sampler to run.</span>"
        elif sampler.value == "exact" and n > 14:
            msg += "<span style='color:#e05545'>Exact enumeration is limited to 14 plants.</span>"
        else:
            sec = estimate_seconds(n, n + K, sampler.value, do_repair.value, compare.value)
            text = f"~{sec:.0f} s" if sec < 120 else f"~{sec / 60:.0f} min"
            msg += f"Rough run time: {text} (sampling + repair)." if sec < 120 else \
                f"<span style='color:#b9770e'>Rough run time: {text} (sampling + repair).</span>"
        estimate.value = msg
        scaled = " (scaled to this fleet)" if rescale.value else ""
        demand_lbl.value = (f"<code>{state['demand_name']}</code>{scaled}: {len(D)} hours, demand "
                            f"{D.min():,.0f}&ndash;{D.max():,.0f} MW, reserve {100 * R.sum() / max(D.sum(), 1e-9):.0f}% of demand")

    def on_load(change):
        files = load_up.value
        if not files:
            return
        f = files[0]
        path = "/tmp/_uploaded_fleet.csv"
        with open(path, "wb") as fh:
            fh.write(bytes(f["content"]))
        try:
            state["rows"] = fleet.load_fleet(path)
            n_plants.value = len(state["rows"])
            render_table()
        except Exception as err:          # noqa: BLE001
            fleet_status.value = RED.format(f"Could not load {htmllib.escape(f['name'])}: {htmllib.escape(str(err))}")
            return
        fleet_status.value = GREEN.format(f"Loaded {htmllib.escape(f['name'])}: {len(state['rows'])} plants")

    def on_demand(change):
        files = demand_up.value
        if not files:
            return
        f = files[0]
        path = "/tmp/_uploaded_demand.csv"
        with open(path, "wb") as fh:
            fh.write(bytes(f["content"]))
        try:
            state["demand"] = fleet.load_demand(path)
            state["demand_name"] = f["name"]
            update_estimate()
        except Exception as err:          # noqa: BLE001
            demand_status.value = RED.format(f"Could not read {htmllib.escape(f['name'])}: {htmllib.escape(str(err))}")
            return
        demand_status.value = GREEN.format(f"Loaded {htmllib.escape(f['name'])}")

    def on_save(_):
        try:
            path = os.path.join(HERE, save_name.value)
            fleet.save_fleet(fleet.validate(read_table()), path)
            fleet_status.value = GREEN.format(f"Fleet saved to <code>{htmllib.escape(path)}</code>")
        except Exception as err:          # noqa: BLE001
            fleet_status.value = RED.format(f"Could not save: {htmllib.escape(str(err))}")

    def message(text, color=None):
        style = f" style='color:{color}'" if color else ""
        results.children = [W.HTML(f"<p{style}>{text}</p>")]

    def preflight():
        """Check every input before running. Returns (plants, D, R, problems, seconds)."""
        problems, plants, D, R, sec = [], None, None, None, 0.0
        if sampler.value is None:
            problems.append("Pick a sampler (QAOA, random or exact) under <b>3. Run</b>.")
        if shots.value < 1:
            problems.append("Shots per hour must be at least 1.")
        try:
            plants = fleet.validate(read_table())
        except Exception as err:          # noqa: BLE001
            problems.append(f"Fleet table: {htmllib.escape(str(err))}")
        try:
            D, R = current_demand()
            D, R = np.asarray(D, float), np.asarray(R, float)
            if len(D) == 0:
                problems.append("The demand file has no hours.")
            elif not (np.isfinite(D).all() and np.isfinite(R).all()):
                problems.append("The demand file has blank or non-numeric values.")
            elif (D < 0).any() or (R < 0).any():
                problems.append("Demand and reserve must not be negative.")
        except Exception as err:          # noqa: BLE001
            problems.append(f"Demand: {htmllib.escape(str(err))}")
        if plants is not None and D is not None and not problems:
            n, K = len(plants), qaoa.encoding(plants)[2]
            cap = sum(p["pmax_mw"] for p in plants)
            if (D + R).max() > cap:
                problems.append(f"Total capacity {cap:,.0f} MW is below the peak demand + reserve "
                                f"{(D + R).max():,.0f} MW, so no valid schedule exists. Add plants, raise pmax, "
                                "or tick 'Scale demand to this fleet'.")
            if sampler.value == "qaoa" and n + K > 22:
                problems.append(f"{n + K} qubits per hour is too many for the simulator (limit 22). "
                                "Use fewer plants or the random sampler.")
            if sampler.value == "exact" and n > 14:
                problems.append("Exact enumeration is limited to 14 plants (2^N choices per hour).")
            sec = estimate_seconds(n, n + K, sampler.value, do_repair.value, compare.value)
        return plants, D, R, problems, sec

    def on_run(_):
        plants, D, R, problems, sec = preflight()
        if problems:
            results.children = [W.HTML("<p style='color:#e05545'><b>Can't run yet:</b></p><ul>"
                                       + "".join(f"<li>{p}</li>" for p in problems) + "</ul>")]
            return
        settings = (sampler.value, shots.value, seed.value, do_repair.value, compare.value, len(plants))
        if sec > 120 and state.get("confirmed") != settings:
            state["confirmed"] = settings
            message(f"This run will take roughly {sec / 60:.0f} minutes (sampling + repair). "
                    "Click <b>Run</b> again to start, or change the settings.", "#b9770e")
            return
        state.pop("confirmed", None)
        steps = "MILP, incentives, hour-by-hour sampling" + (", classical repair" if do_repair.value else "")
        message(f"Running... ({steps})")
        run_btn.disabled = True
        try:
            res = solve(plants, D, R, sampler=sampler.value, shots=shots.value, seed=seed.value,
                        do_repair=do_repair.value, compare_random=compare.value and sampler.value != "random")
            name = {"qaoa": "QAOA", "random": "random", "exact": "exact enumeration"}[sampler.value]
            sampled = "" if sampler.value == "exact" else f", {shots.value} shots/hour, seed {seed.value}"
            settings_txt = (f"Settings: {len(plants)} plants (up to {res['qubits']} qubits/hour), sampler {name}"
                            f"{sampled}, classical repair {'on' if do_repair.value else 'off'}, demand "
                            f"{htmllib.escape(state['demand_name'])}{' scaled to the fleet' if rescale.value else ''}.")
            results.children = report(plants, D, R, res, settings_txt)
        except RuntimeError as err:
            message(f"No valid schedule exists for this fleet and demand: {htmllib.escape(str(err))}", "#e05545")
        except Exception:                 # noqa: BLE001 - show the error instead of failing silently
            results.children = [W.HTML("<p style='color:#e05545'>Something went wrong:</p><pre>"
                                       + htmllib.escape(traceback.format_exc()) + "</pre>")]
        finally:
            run_btn.disabled = False

    def report(plants, D, R, res, settings_txt):
        """Results as widgets: headline, comparison table, rules check, repair details, chart, saved files."""
        names = [p["plant_id"] for p in plants]
        parts = []
        main = res["main"]
        rows = [main] + [res[k] for k in ("random", "classical") if k in res]
        repaired = "repair" in main
        tail = " + repair" if repaired else " (no repair)"
        label = {"qaoa": "QAOA hybrid" + tail, "random": "Random guessing" + tail,
                 "exact": "Exact enumeration" + tail, "classical": "Classical only (Lagrangian + repair)"}
        short = {"qaoa": "QAOA", "random": "Random", "exact": "Exact"}[main["sampler"]]
        gap = lambda r: f"{r['gap_pct']:+.2f}%" if r["valid"] else RED.format("not valid")
        broken = lambda r: GREEN.format("0") if r["valid"] else RED.format(f"<b>{len(r['violations'])}</b>")
        td = "<td style='padding:4px 10px'>{}</td>"

        # 1. headline
        a = main["after"]
        status = GREEN.format("valid, every rule met") if a["valid"] else \
            RED.format(f"{len(a['violations'])} rule(s) broken")
        parts.append(W.HTML(
            "<h3 style='margin-bottom:4px'>Result</h3>"
            f"<p style='font-size:15px;margin:4px 0'><b>{label[main['sampler']]}</b>: "
            f"${a['total_cost']:,.0f}, <b>{gap(a)}</b> vs the MILP optimum (${res['milp_cost']:,.0f}), {status}.</p>"
            f"<p style='opacity:0.75;font-size:12px;margin:2px 0'>{settings_txt}</p>"))

        # 2. comparison table (MILP first, as the standard)
        headers = ["method", "cost", "gap vs MILP", "rules broken"] + \
            (["before repair", "certified bound"] if repaired else []) + ["P(kept choice)", "time"]
        html = [SECTION.format("Comparison"), "<table style='border-collapse:collapse'><tr>"
                + "".join(f"<th style='padding:4px 10px;text-align:left;border-bottom:1px solid rgba(128,128,128,0.5)'>{h}</th>"
                          for h in headers) + "</tr>"]
        milp_cols = ["<b>MILP optimum</b> (the standard)", f"${res['milp_cost']:,.0f}", "0.00%", GREEN.format("0")]
        milp_cols += (["-", "exact"] if repaired else []) + ["-", f"{res['t_milp']:.2f} s"]
        html.append("<tr style='background:rgba(128,128,128,0.15);border-bottom:1px solid rgba(128,128,128,0.4)'>" + "".join(td.format(c) for c in milp_cols) + "</tr>")
        for r in rows:
            cols = [label[r["sampler"]], f"${r['after']['total_cost']:,.0f}", f"<b>{gap(r['after'])}</b>",
                    broken(r["after"])]
            if repaired:
                b = r["before"]
                before = f"{b['gap_pct']:+.2f}%, valid" if b["valid"] else \
                    RED.format(f"not valid, {len(b['violations'])} broken")
                cert = "-"
                if r["after"]["valid"]:
                    cert = f"&le; {100 * (r['after']['total_cost'] - r['lower_bound']) / r['lower_bound']:.2f}%"
                cols += [before, cert]
            t = f"{r['t_hourly']:.1f} s" + (f" + {r['t_repair']:.1f} s repair" if "t_repair" in r else "")
            cols += ["-" if r["p_pick"] is None else f"{r['p_pick']:.4f}", t]
            html.append("<tr>" + "".join(td.format(c) for c in cols) + "</tr>")
        notes = ["<b>gap vs MILP</b>: how much more the schedule costs than the optimal one."]
        if repaired:
            notes += ["<b>before repair</b>: the hour-by-hour schedule as sampled, before classical repair fixed it.",
                      "<b>certified bound</b>: the most the schedule can be above the true optimum, from the "
                      "Lagrangian lower bound alone (no MILP needed)."]
        else:
            notes.append("Classical repair is off, so these are the raw hour-by-hour schedules and can break rules.")
        notes.append("<b>P(kept choice)</b>: average probability the sampler gave the on/off choice that was kept "
                     f"(a uniform guess over all plants gives {2.0 ** -res['n']:.4f}).")
        if len(rows) > 1:
            notes.append("The other rows run the same pipeline without QAOA, to show what QAOA itself adds.")
        notes.append("<b>time</b>: incentives + sampling" + (", then repair." if repaired else "."))
        html.append("</table><ul style='font-size:12px;opacity:0.8;margin:6px 0'>"
                    + "".join(f"<li>{n}</li>" for n in notes) + "</ul>")
        parts.append(W.HTML("".join(html)))

        # 3. rules check, 4. repair details
        parts.append(W.HTML(rules_html(rows, label)))
        if repaired:
            text = repair.describe(main["repair"])
            parts.append(W.HTML(SECTION.format(f"What classical repair changed ({short} schedule)")
                                + "<pre style='font-size:12px;line-height:1.35;margin:4px 0'>"
                                + htmllib.escape(text) + "</pre>"))
        parts.append(W.HTML(SECTION.format("Schedules")))
        panels = [("MILP (optimal)", res["milp_schedule"])]
        if repaired:
            panels.append((f"{short} hour by hour, before repair", main["schedule_before"]))
        panels.append((f"{short} hybrid, {'after repair' if repaired else 'no repair'}", main["schedule"]))
        T, n = len(D), len(plants)
        row_h = 0.55 + 0.3 * n
        fig, axes = plt.subplots(len(panels) + 1, 1, sharex=True, squeeze=False,
                                 figsize=(9, row_h * len(panels) + 2.6),
                                 gridspec_kw=dict(height_ratios=[row_h] * len(panels) + [2.2]))
        axes = axes[:, 0]
        for ax, (title, sched) in zip(axes, panels):
            # hour h fills [h, h+1], plant i fills [i, i+1], so cells line up with the hour axis below
            ax.imshow(np.asarray(sched).T, aspect="auto", cmap="Greens", vmin=0, vmax=1.4,
                      interpolation="nearest", extent=(0, T, n, 0))
            ax.set_yticks(np.arange(n) + 0.5, names, fontsize=8)
            ax.set_xticks(np.arange(0, T + 1, 1), minor=True)
            ax.grid(which="minor", axis="x", color="white", lw=0.6)
            ax.tick_params(which="minor", length=0)
            ax.set_title(title + "  (green = on)", fontsize=10)
        cap_ax = axes[-1]
        edges = np.arange(T + 1)
        pmax = np.array([p["pmax_mw"] for p in plants])
        cap_ax.stairs(D + R, edges, baseline=None, color="black", lw=1.5, label="demand + reserve")
        cap_ax.stairs(np.asarray(res["milp_schedule"]) @ pmax, edges, baseline=None, color="#2a78d6", lw=1.5,
                      label="capacity on: MILP")
        cap_ax.stairs(np.asarray(main["schedule"]) @ pmax, edges, baseline=None, color="#eb6834", lw=1.5, ls="--",
                      label=f"capacity on: {short} hybrid")
        cap_ax.set_ylabel("MW")
        cap_ax.set_title("Capacity switched on vs what each hour needs", fontsize=10)
        cap_ax.legend(fontsize=8, loc="upper left")
        cap_ax.set_xlim(0, T)
        cap_ax.set_xticks(np.arange(0, T + 1, 2))
        cap_ax.set_xlabel("hour (each block is one hour, starting at the tick)")
        fig.tight_layout()
        chart, chart_path = chart_widget(figure_png(fig), "schedule")
        parts.append(chart)
        buf = io.StringIO()
        buf.write("hour," + ",".join(names) + "\n")
        for t, row in enumerate(main["schedule"]):
            buf.write(f"{t}," + ",".join(str(int(x)) for x in row) + "\n")
        path = os.path.join(HERE, "outputs", "hybrid_schedule.csv")
        with open(path, "w") as f:
            f.write(buf.getvalue())
        parts.append(W.HTML(SECTION.format("Saved files")
                            + f"<p style='font-size:12px;margin:2px 0'>schedule: <code>{htmllib.escape(path)}</code>"
                            f"<br>chart: <code>{htmllib.escape(chart_path)}</code></p>"))
        return parts

    n_plants.observe(resize, "value")
    fill_btn.on_click(fill)
    load_up.observe(on_load, "value")
    demand_up.observe(on_demand, "value")
    save_btn.on_click(on_save)
    run_btn.on_click(on_run)
    sampler.observe(sync_controls, "value")
    for w in (rescale, compare, do_repair):
        w.observe(update_estimate, "value")

    render_table()
    sync_controls()
    ui = W.VBox([
        W.HTML("<h3>1. Fleet</h3><p style='margin:2px 0'>Set the number of plants and edit any cell. Rows you "
               "remove come back if you add them again; extra rows are filled from the plant templates.</p>"),
        W.HBox([n_plants, preset, fill_btn]),
        table_box,
        W.HBox([load_up, save_name, save_btn]),
        fleet_status,
        W.HTML("<h3>2. Demand</h3>"),
        demand_lbl,
        W.HBox([demand_up, rescale]),
        demand_status,
        W.HTML("<h3>3. Run</h3>"),
        sampler, W.HBox([shots, seed]), W.HBox([do_repair, compare]),
        estimate, run_btn,
        results,
    ])
    display(ui)
    return ui
