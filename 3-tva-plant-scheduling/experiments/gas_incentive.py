"""Blend a classical GAS_CC incentive with the hour-by-hour QAOA loop from starter.ipynb.

Run from 3-tva-plant-scheduling/ with the qBraid kernel's python:
    python experiments/gas_incentive.py
Loads every code cell of starter.ipynb up to and including `def schedule_day`, then
re-implements the day loop with three incentive knobs. Writes experiments/gas_incentive_results.md.
"""
import contextlib, io, json, os, sys, time

import matplotlib
matplotlib.use("Agg")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# ---- load the notebook's functions -------------------------------------------------
nb = json.load(open("starter.ipynb"))
code = []
for cell in nb["cells"]:
    if cell["cell_type"] != "code":
        continue
    src = "".join(cell["source"])
    src = "\n".join("    pass" if l.strip().startswith("%") else l for l in src.splitlines())
    code.append(src.replace("plt.show()", "plt.close('all')"))
    if "def schedule_day" in src:
        break
with contextlib.redirect_stdout(io.StringIO()):
    exec("\n\n".join(code))

GAS = names.index("GAS_CC")
ALL = [list(INDEX_BITS[k][:N]) for k in range(2 ** N)]
NEED = demand + reserve


# ---- classical incentives ------------------------------------------------------------
def gas_commit_hours():
    """Classical pre-pass: GAS_CC must be on from the first hour COAL alone can't cover
    demand+reserve until the last such hour (one start, no gaps)."""
    short = np.where(NEED > plants[names.index("COAL")]["pmax_mw"])[0]
    return set(range(short.min(), short.max() + 1)) if len(short) else set()


def adjustment(was_on):
    """Per-plant $ adjustment for this hour under the current mode (negative = incentive)."""
    adj = np.zeros(N)
    if CFG["amortize"]:          # spread startup over min-up hours instead of charging it all now
        for i, p in enumerate(plants):
            if not was_on[i]:
                adj[i] -= p["startup_cost"] * (1 - 1 / p["min_up_h"])
    adj[GAS] -= CFG["gas_bonus"]
    return adj


def day(shots, sampler, seed, p=1):
    rng = np.random.default_rng(seed)
    history, was_on, angles, mass = [], [int(x["on_at_start"]) for x in plants], None, []
    commit = gas_commit_hours() if CFG["commit"] else set()
    for t in hours:
        must_on, must_off = locks(plants, history)
        must_on = list(must_on)
        if t in commit and GAS not in must_on and GAS not in must_off:
            must_on.append(GAS)
        adj = adjustment(was_on)
        Q, offset = build_qubo(plants, demand[t], reserve[t], was_on, penalty=CFG["penalty"])
        for i in range(N):
            Q[i, i] += adj[i]                       # incentive inside the QUBO
        Q, offset = add_locks(Q, offset, must_on, must_off, weight=2 * plant_hour_costs(plants, was_on).max())
        if sampler == "qaoa":
            angles, probs = run_qaoa(Q, offset, p=p, start=angles)
        else:
            probs = np.full(2 ** N_QUBITS, 1 / 2 ** N_QUBITS)
        samples = rng.choice(2 ** N_QUBITS, size=shots, p=probs / probs.sum())
        seen = [list(INDEX_BITS[k][:N]) for k in np.unique(PLANT_INDEX[samples])]
        ok = [c for c in seen if hour_ok(plants, demand[t], reserve[t], c, must_on, must_off)] \
            or [c for c in seen if hour_ok(plants, demand[t], reserve[t], c)]
        score = lambda c: hour_cost(plants, demand[t], c, was_on) + float(np.dot(adj, c))  # incentive in pick
        pick = min(ok, key=score) if ok else ALL[np.bincount(PLANT_INDEX[samples], minlength=32).argmax()]
        mass.append(choice_probs(probs)[int(np.dot(pick, 2 ** np.arange(N)))])
        history.append(pick)
        was_on = pick
    return np.array(history), float(np.mean(mass))


CONFIGS = {
    "A baseline (no incentive)":           dict(amortize=False, gas_bonus=0,     commit=False, penalty=None),
    "B amortized startup":                 dict(amortize=True,  gas_bonus=0,     commit=False, penalty=None),
    "C GAS bonus $2k/h":                   dict(amortize=False, gas_bonus=2000,  commit=False, penalty=None),
    "D GAS bonus $5k/h":                   dict(amortize=False, gas_bonus=5000,  commit=False, penalty=None),
    "E GAS commit pre-pass":               dict(amortize=False, gas_bonus=0,     commit=True,  penalty=None),
    "F commit + amortized":                dict(amortize=True,  gas_bonus=0,     commit=True,  penalty=None),
    "G commit + amortized, low penalty":   dict(amortize=True,  gas_bonus=0,     commit=True,  penalty="low"),
}
SHOTS, SEEDS = [10, 20, 50, 200], range(5)

rows = []
t0 = time.time()
for name, cfg in CONFIGS.items():
    CFG = dict(cfg)
    for shots in SHOTS:
        for sampler in ["qaoa", "random"]:
            gaps, masses = [], []
            for seed in SEEDS:
                if cfg["penalty"] == "low":    # 0.5 x biggest plant cost at the start state
                    CFG["penalty"] = 0.5 * plant_hour_costs(plants, [int(x["on_at_start"]) for x in plants]).max()
                sched, m = day(shots, sampler, seed)
                with contextlib.redirect_stdout(io.StringIO()):
                    r = check_schedule(plants, demand, reserve, sched, milp_cost=milp_cost, verbose=False)
                gaps.append(None if r["violations"] else r["gap_pct"])
                masses.append(m)
            v = [g for g in gaps if g is not None]
            rows.append((name, shots, sampler, len(v), np.mean(v) if v else np.nan,
                         min(v) if v else np.nan, np.mean(masses)))
            print(f"{name:<36}{shots:>5} {sampler:<7} valid {len(v)}/5  mean {rows[-1][4]:+6.2f}%  "
                  f"best {rows[-1][5]:+6.2f}%  P(pick) {rows[-1][6]:.3f}", flush=True)
print(f"done in {time.time() - t0:.0f} s")

with open(os.path.join(HERE, "gas_incentive_results.md"), "w") as f:
    f.write("# GAS_CC incentive + QAOA: results\n\n")
    f.write(f"MILP optimum: ${milp_cost:,.0f}. 5 seeds per row. Gap is over valid days only. "
            "P(pick) = average probability the sampler gave the choice finally kept.\n\n")
    f.write("| config | shots | sampler | valid days | mean gap | best gap | P(pick) |\n|---|---|---|---|---|---|---|\n")
    for r in rows:
        f.write(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]}/5 | {r[4]:+.2f}% | {r[5]:+.2f}% | {r[6]:.3f} |\n")
