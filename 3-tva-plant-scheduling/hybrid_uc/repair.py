"""Classical stage 3: find where a schedule is off (the "~1% cases") and fix it.

1. Certificate. The Lagrangian lower bound (incentives.py) says how far ANY schedule can be from optimal:
   certified_gap = (cost - lower_bound) / lower_bound. No MILP needed, so it works at any scale.
2. Diagnosis. Lists every broken rule (hour, plant, rule) using check.py's definitions.
3. Local search. Moves on each plant's on-blocks: start one hour earlier/later, stop one hour
   earlier/later, drop a block, bridge a gap between two blocks, or add a new block of min_up hours.
   Paired moves: when a move turns plant i on in some hours, also try turning one other plant off in
   those hours (e.g. "start GAS_CC an hour earlier and drop OIL that hour"), which single moves miss.
   Partners are capped at the 8 dearest plants running in those hours, so a pass stays ~linear in N.
   Large-neighbourhood moves: when no small move helps, start from a bigger change to one plant (drop a
   whole on-block, cut it to start or stop at any hour inside it, or bridge the gap between two blocks), then greedily adjust other plants in the hours
   it touched until nothing improves; keep it if the day got cheaper or broke fewer rules. These run for
   fleets of up to 16 plants, and on bigger fleets only while a rule is still broken (they cost ~N^2 T^2). This handles swaps such as "drop the big unit for 8 hours,
   cover the peak with three small ones", which no one- or two-plant move reaches.
   Objective = exact cost + a large penalty per broken rule. Best improving move each pass, until none.
   Each move is scored incrementally (only the hours and the plant it touches), so a pass costs about
   N x (moves per plant) x (hours touched) and grows roughly linearly with the fleet.
"""
import numpy as np

import check

BIG = 1e7          # $ per broken rule: any fix beats any saving
PER_MW = 1e5       # $ per MW of shortfall, so covering a big gap one plant at a time still counts as progress


class Scorer:
    def __init__(self, plants, demand, reserve):
        self.plants, self.D, self.R = plants, np.asarray(demand), np.asarray(reserve)
        self.T, self.n = len(demand), len(plants)
        self.start = np.array([int(p["on_at_start"]) for p in plants])
        self.pmax = np.array([p["pmax_mw"] for p in plants])
        self.pmin = np.array([p["pmin_mw"] for p in plants])
        self._cache = {}

    def hour_cost(self, s, t):
        prev = self.start if t == 0 else s[t - 1]
        key = (t, s[t].tobytes(), prev.tobytes())
        if key not in self._cache:
            self._cache[key] = check.hour_cost(self.plants, self.D[t], s[t], prev)
        return self._cache[key]

    def hour_broken(self, s, t):
        cap, floor = s[t] @ self.pmax, s[t] @ self.pmin
        return int(cap < self.D[t] + self.R[t] - 1e-6) + int(cap < self.D[t] - 1e-6) + int(floor > self.D[t] + 1e-6)

    def hour_penalty(self, s, t):
        cap, floor = s[t] @ self.pmax, s[t] @ self.pmin
        need = self.D[t] + self.R[t]
        mw = max(0.0, need - cap) + max(0.0, floor - self.D[t])
        return BIG * self.hour_broken(s, t) + PER_MW * mw

    def plant_broken(self, col, i):
        p, prev, since, bad = self.plants[i], self.start[i], None, 0
        for t in range(self.T):
            if col[t] != prev:
                if since is not None:
                    held = t - since
                    bad += int(prev == 1 and held < p["min_up_h"]) + int(prev == 0 and held < p["min_down_h"])
                prev, since = col[t], t
        return bad

    def total(self, s):
        cost = sum(self.hour_cost(s, t) for t in range(self.T))
        broken = sum(self.hour_broken(s, t) for t in range(self.T)) + \
            sum(self.plant_broken(s[:, i], i) for i in range(self.n))
        return cost, broken

    def delta(self, s, i, new_col):
        """Change in (cost + BIG * broken) if plant i's column becomes new_col."""
        changed = np.flatnonzero(s[:, i] != new_col)
        if len(changed) == 0:
            return 0.0
        hours = sorted(set(changed) | {t + 1 for t in changed if t + 1 < self.T})
        before = sum(self.hour_cost(s, t) for t in hours) + \
            sum(self.hour_penalty(s, t) for t in changed) + BIG * self.plant_broken(s[:, i], i)
        old = s[:, i].copy()
        s[:, i] = new_col
        after = sum(self.hour_cost(s, t) for t in hours) + \
            sum(self.hour_penalty(s, t) for t in changed) + BIG * self.plant_broken(new_col, i)
        s[:, i] = old
        return after - before


def on_blocks(col):
    blocks, t = [], 0
    while t < len(col):
        if col[t]:
            a = t
            while t + 1 < len(col) and col[t + 1]:
                t += 1
            blocks.append((a, t))
        t += 1
    return blocks


def candidate_columns(col, p):
    T, MU = len(col), int(p["min_up_h"])
    out = []
    blocks = on_blocks(col)
    for k, (a, b) in enumerate(blocks):
        for lo, hi, val in [(a - 1, a - 1, 1), (a, a, 0), (b + 1, b + 1, 1), (b, b, 0), (a, b, 0)]:
            if 0 <= lo <= hi < T:
                c = col.copy()
                c[lo:hi + 1] = val
                out.append(c)
        if k + 1 < len(blocks):                          # bridge the gap to the next block
            c = col.copy()
            c[b + 1:blocks[k + 1][0]] = 1
            out.append(c)
    for t in range(T):                                   # a new block of min_up hours starting at t
        if not col[t]:
            c = col.copy()
            c[t:min(T, t + MU)] = 1
            out.append(c)
    return out


def seeded_greedy(sc, s, i, seed_col, max_steps=24):
    """Large-neighbourhood move: apply plant i's seed column (drop a block, or bridge a gap), then greedily
    apply the best change to any other plant that touches the hours the seed changed, until nothing improves.
    Returns (total delta, moves)."""
    s2 = s.copy()
    total = sc.delta(s2, i, seed_col)
    window = set(np.flatnonzero(s2[:, i] != seed_col).tolist())
    s2[:, i] = seed_col
    moves = [(i, seed_col.copy())]
    for _ in range(max_steps):
        best = (-1e-6, None, None)
        for j, p in enumerate(sc.plants):
            if j == i:
                continue
            for cj in candidate_columns(s2[:, j], p):
                if not window & set(np.flatnonzero(cj != s2[:, j]).tolist()):
                    continue
                d = sc.delta(s2, j, cj)
                if d < best[0]:
                    best = (d, j, cj)
        if best[1] is None:
            break
        total += best[0]
        s2[:, best[1]] = best[2]
        moves.append((best[1], best[2].copy()))
    return total, moves


def lns_seeds(col):
    """Seed columns for the large move: each on-block dropped or cut to start/end at any hour inside it,
    and each gap between blocks bridged."""
    blocks = on_blocks(col)
    for a, b in blocks:
        c = col.copy()
        c[a:b + 1] = 0
        yield c
        for cut in range(a + 1, b + 1):          # start later: on from `cut`
            c = col.copy()
            c[a:cut] = 0
            yield c
        for cut in range(a, b):                  # stop earlier: on until `cut`
            c = col.copy()
            c[cut + 1:b + 1] = 0
            yield c
    for (_, b), (a2, _) in zip(blocks, blocks[1:]):
        c = col.copy()
        c[b + 1:a2] = 1
        yield c


def repair(plants, demand, reserve, schedule, lower_bound=None, milp_cost=None, max_passes=200, pairs=True,
           max_partners=8, lns=True, lns_max_plants=16):
    sc = Scorer(plants, demand, reserve)
    by_price = sorted(range(len(plants)), key=lambda j: -plants[j]["marginal_cost_per_mwh"])  # dearest first
    s = np.array(schedule, dtype=np.int64).copy()
    cost0, broken0 = sc.total(s)
    violations0 = check.check_schedule(plants, demand, reserve, s, verbose=False)["violations"]
    changes = []
    for _ in range(max_passes):
        best = (-1e-6, [])
        for i, p in enumerate(plants):
            for col in candidate_columns(s[:, i], p):
                d = sc.delta(s, i, col)
                if d < best[0]:
                    best = (d, [(i, col)])
                if pairs and ((col == 1) & (s[:, i] == 0)).any():
                    old = s[:, i].copy()
                    s[:, i] = col
                    gained = (col == 1) & (old == 0)
                    partners = [j for j in by_price if j != i and (s[gained, j] == 1).any()][:max_partners]
                    for j in partners:
                        cj = s[:, j].copy()
                        cj[gained] = 0
                        d2 = d + sc.delta(s, j, cj)
                        if d2 < best[0]:
                            best = (d2, [(i, col), (j, cj)])
                    s[:, i] = old
        if not best[1] and lns and (len(plants) <= lns_max_plants or sc.total(s)[1] > 0):
            for i in range(len(plants)):
                for seed_col in lns_seeds(s[:, i]):
                    d, moves = seeded_greedy(sc, s, i, seed_col)
                    if d < best[0]:
                        best = (d, moves)
        if not best[1]:
            break
        for k, (i, col) in enumerate(best[1]):
            on = np.flatnonzero((col == 1) & (s[:, i] == 0))
            off = np.flatnonzero((col == 0) & (s[:, i] == 1))
            changes.append(dict(plant=plants[i]["plant_id"], on_hours=on.tolist(), off_hours=off.tolist(),
                                saved=-best[0] if best[0] > -PER_MW / 2 else None, paired=len(best[1]) > 1 and k > 0))
            s[:, i] = col
    cost1, broken1 = sc.total(s)
    start = np.array(schedule, dtype=np.int64)
    net = []
    for i, p in enumerate(plants):
        on = np.flatnonzero((s[:, i] == 1) & (start[:, i] == 0)).tolist()
        off = np.flatnonzero((s[:, i] == 0) & (start[:, i] == 1)).tolist()
        if on or off:
            net.append(dict(plant=p["plant_id"], on_hours=on, off_hours=off))
    report = dict(cost_before=cost0, broken_before=broken0, violations_before=violations0,
                  cost_after=cost1, broken_after=broken1, changes=changes, net_changes=net,
                  search_moves=len(changes), lower_bound=lower_bound, milp_cost=milp_cost)
    if lower_bound:
        report["certified_gap_before"] = 100 * (cost0 - lower_bound) / lower_bound
        report["certified_gap_after"] = 100 * (cost1 - lower_bound) / lower_bound
    if milp_cost:
        report["gap_before"] = 100 * (cost0 - milp_cost) / milp_cost
        report["gap_after"] = 100 * (cost1 - milp_cost) / milp_cost
    return s, report


def describe(report, names_by_id=None):
    """Plain-language summary: what was wrong, the net change per plant, and the result."""
    lines = []
    if report["broken_before"]:
        lines.append(f"before repair: ${report['cost_before']:,.0f}, NOT valid ({report['broken_before']} rule(s) broken):")
        for v in report["violations_before"][:10]:
            lines.append(f"    hour {v[0]:>2}  {v[1]:<10} {v[2]:<16} {v[3]}")
        if len(report["violations_before"]) > 10:
            lines.append(f"    ... and {len(report['violations_before']) - 10} more")
    else:
        lines.append(f"before repair: ${report['cost_before']:,.0f}, valid")
    if report["net_changes"]:
        lines.append(f"net changes ({report['search_moves']} search moves):")
        for ch in report["net_changes"]:
            what = []
            if ch["on_hours"]:
                what.append(f"now ON at hours {span(ch['on_hours'])}")
            if ch["off_hours"]:
                what.append(f"now OFF at hours {span(ch['off_hours'])}")
            lines.append(f"    {ch['plant']:<10} {'; '.join(what)}")
    else:
        lines.append("no changes needed")
    status = "valid" if not report["broken_after"] else f"still NOT valid ({report['broken_after']} rule(s) broken)"
    lines.append(f"after repair:  ${report['cost_after']:,.0f}, {status}")
    if not report["broken_before"] and report["cost_before"] > report["cost_after"]:
        lines.append(f"saved: ${report['cost_before'] - report['cost_after']:,.0f}")
    if "certified_gap_after" in report and not report["broken_after"]:
        lines.append(f"certified bound: at most {report['certified_gap_after']:.2f}% above the true optimum "
                     f"(Lagrangian lower bound ${report['lower_bound']:,.0f})")
    if "gap_after" in report:
        before = "not valid" if report["broken_before"] else f"{report['gap_before']:+.2f}%"
        after = "not valid" if report["broken_after"] else f"{report['gap_after']:+.2f}%"
        lines.append(f"gap vs MILP optimum: {before} -> {after}")
    return "\n".join(lines)


def span(hours):
    """[0, 1, 2, 3, 9, 12, 13] -> '0-3, 9, 12-13'."""
    parts, start = [], hours[0]
    for prev, h in zip(hours, hours[1:] + [None]):
        if h is None or h != prev + 1:          # the run of consecutive hours ends at prev
            parts.append(f"{start}-{prev}" if prev > start else str(start))
            start = h
    return ", ".join(parts)
