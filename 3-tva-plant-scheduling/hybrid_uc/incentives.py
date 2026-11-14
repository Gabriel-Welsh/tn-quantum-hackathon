"""Classical incentives from Lagrangian relaxation.

Relax the two constraints that couple plants within an hour (demand balance, reserve) with prices:
lam[t] ($/MWh) and mu[t] ($/MW of capacity, >= 0). The day then splits into one small problem per plant,
solved exactly by dynamic programming over (on/off, hours held), which respects min up/down times and
startup costs. Every plant problem is independent, so the work grows linearly with the fleet.

Outputs:
  * lower_bound - no schedule can cost less (a certificate; no MILP needed)
  * value[i][t][state] - plant i's priced cost-to-go from hour t; the difference between "on" and "off"
    is the incentive the hourly QUBO and pick step use (it generalizes amortized startup and commitment windows)
  * schedule - each plant's own best plan at the final prices (usually close, rarely feasible as is)
"""
import numpy as np


def plant_dims(p):
    return max(1, int(round(p["min_up_h"]))), max(1, int(round(p["min_down_h"])))


def state_index(p, on, held):
    """State entering an hour: on/off and how many hours it has been held (capped)."""
    MU, MD = plant_dims(p)
    return min(held, MU) - 1 if on else MU + min(held, MD) - 1


def initial_state(p):
    MU, MD = plant_dims(p)        # check.locks: the midnight state "lasted long enough to switch freely"
    return state_index(p, bool(p["on_at_start"]), MU if p["on_at_start"] else MD)


def solve_plant(p, lam, mu):
    """Exact priced single-plant problem. Returns (V [T+1 x S], on [T], output [T])."""
    T = len(lam)
    MU, MD = plant_dims(p)
    S = MU + MD
    out_on = np.where(lam > p["marginal_cost_per_mwh"], p["pmax_mw"], p["pmin_mw"])
    g = p["no_load_cost_per_h"] - mu * p["pmax_mw"] + (p["marginal_cost_per_mwh"] - lam) * out_on
    V = np.zeros((T + 1, S))
    on_next = np.minimum(np.arange(1, MU + 1), MU - 1)           # on, held k -> held k+1 (capped)
    off_next = MU + np.minimum(np.arange(1, MD + 1), MD - 1)
    for t in range(T - 1, -1, -1):
        Vn = V[t + 1]
        v_on = g[t] + Vn[on_next]
        v_on[MU - 1] = min(v_on[MU - 1], Vn[MU])                 # may switch off once min up is met
        v_off = Vn[off_next].copy()
        v_off[MD - 1] = min(v_off[MD - 1], p["startup_cost"] + g[t] + Vn[0])   # may start once min down is met
        V[t, :MU], V[t, MU:] = v_on, v_off
    on = np.zeros(T, dtype=int)
    s = initial_state(p)
    for t in range(T):
        Vn = V[t + 1]
        if s < MU:
            stay = g[t] + Vn[on_next[s]]
            if s == MU - 1 and Vn[MU] < stay:
                s = MU
            else:
                on[t], s = 1, on_next[s]
        else:
            k = s - MU
            start = p["startup_cost"] + g[t] + Vn[0]
            if k == MD - 1 and start < Vn[off_next[k]]:
                on[t], s = 1, 0
            else:
                s = off_next[k]
    return V, on, on * out_on


class Incentives:
    def __init__(self, plants, lam, mu, lower_bound, history):
        self.plants, self.lam, self.mu = plants, lam, mu
        self.lower_bound, self.history = lower_bound, history
        solved = [solve_plant(p, lam, mu) for p in plants]
        self.value = [v for v, _, _ in solved]
        self.schedule = np.array([on for _, on, _ in solved]).T

    def future(self, i, t, on, held):
        """Priced cost-to-go of plant i from hour t, entering it in state (on, held)."""
        return self.value[i][t, state_index(self.plants[i], on, held)]


def dual_value(plants, demand, reserve, lam, mu):
    total, P, CAP = 0.0, np.zeros(len(demand)), np.zeros(len(demand))
    for p in plants:
        V, on, out = solve_plant(p, lam, mu)
        total += V[0, initial_state(p)]
        P += out
        CAP += on * p["pmax_mw"]
    return total + lam @ demand + mu @ (demand + reserve), P, CAP


def lagrangian(plants, demand, reserve, iters=300, upper_bound=None, start=None):
    """Subgradient ascent on the prices (Polyak steps). Returns Incentives at the best prices found."""
    demand, reserve = np.asarray(demand, float), np.asarray(reserve, float)
    if start is None:
        lam = np.full(len(demand), float(np.median([p["marginal_cost_per_mwh"] for p in plants])))
        mu = np.zeros(len(demand))
    else:
        lam, mu = start[0].copy(), start[1].copy()
    best = (-np.inf, lam.copy(), mu.copy())
    theta, stall, history = 1.0, 0, []
    for _ in range(iters):
        L, P, CAP = dual_value(plants, demand, reserve, lam, mu)
        history.append(L)
        if L > best[0] + 1e-9:
            best, stall = (L, lam.copy(), mu.copy()), 0
        else:
            stall += 1
            if stall >= 8:
                theta, stall = theta / 2, 0
        if theta < 1e-4:
            break
        g_lam = demand - P
        g_mu = demand + reserve - CAP
        g_mu = np.where((mu > 0) | (g_mu > 0), g_mu, 0.0)
        norm = g_lam @ g_lam + g_mu @ g_mu
        if norm < 1e-9:
            break
        target = upper_bound if upper_bound is not None else best[0] + 0.03 * abs(best[0])
        step = theta * max(target - L, 1e-6 * abs(L)) / norm
        lam = lam + step * g_lam
        mu = np.maximum(0.0, mu + step * g_mu)
    return Incentives(plants, best[1], best[2], best[0], history)
