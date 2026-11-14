"""Hourly QUBO for N plants and a fast QAOA simulator.

The QUBO is the notebook's, generalized:
    E(y) = sum_j lin_j y_j + A (sum_j b_j y_j - r)^2
with y = (x_0..x_{N-1}, s_0..s_{K-1}); b = capacity blocks per plant, then -1, -2, -4, ... for slack;
r = blocks needed this hour. lin holds the plant costs, the incentives and the lock penalties.

The simulator applies exactly the notebook's circuit (H on all qubits; per layer rz/rzz cost layer scaled by
the largest Ising coefficient, then rx mixer). Because the cost layer is diagonal it is a phase multiply,
so 15-20 qubits run in milliseconds per evaluation. to_qiskit() builds the same circuit for hardware.
"""
from functools import lru_cache

import numpy as np
from scipy.optimize import minimize


class HourQUBO:
    def __init__(self, lin, b, r, A, n_plants):
        self.lin, self.b, self.r, self.A, self.n_plants = np.asarray(lin, float), np.asarray(b, float), r, A, n_plants
        self.n_qubits = len(lin)

    def energies(self):
        bits = bits_table(self.n_qubits)
        return bits @ self.lin + self.A * (bits @ self.b - self.r) ** 2

    def matrix(self):
        """Upper-triangular Q with E = y^T Q y + A r^2 (the notebook's format)."""
        Q = np.triu(2 * self.A * np.outer(self.b, self.b), 1)
        Q[np.diag_indices_from(Q)] = self.lin + self.A * (self.b ** 2 - 2 * self.r * self.b)
        return Q, self.A * self.r ** 2

    def ising(self):
        Q, _ = self.matrix()
        h = -np.diag(Q) / 2 - (Q.sum(0) + Q.sum(1) - 2 * np.diag(Q)) / 4
        J = {(j, k): Q[j, k] / 4 for j in range(len(Q)) for k in range(j + 1, len(Q)) if Q[j, k] != 0}
        return h, J

    def scale(self):
        h, J = self.ising()
        return max(np.abs(h).max(), max((abs(v) for v in J.values()), default=0.0), 1e-12)

    def to_choice(self, k, n_total):
        """Bitstring index k (plant bits first) -> full on/off choice for all n_total plants."""
        c = np.zeros(n_total, dtype=int)
        c[self.must_on] = 1
        for j, i in enumerate(self.free):
            c[i] = (k >> j) & 1
        return tuple(int(x) for x in c)


def encoding(plants):
    """Capacity blocks: block = smallest pmax; plant i counts floor(pmax_i / block) blocks;
    K slack bits cover 0 .. largest plant's blocks of spare capacity."""
    block = min(p["pmax_mw"] for p in plants)
    a = np.floor(np.array([p["pmax_mw"] for p in plants]) / block + 1e-9)
    K = int(np.ceil(np.log2(a.max() + 1)))
    return block, a, K


def plant_hour_costs(plants, was_on):
    """TODO 2's approximation, for any fleet: startup if off before + no-load + extra price on pmin MW."""
    cheapest = min(p["marginal_cost_per_mwh"] for p in plants)
    return np.array([p["startup_cost"] * (1 - w) + p["no_load_cost_per_h"]
                     + p["pmin_mw"] * (p["marginal_cost_per_mwh"] - cheapest) for p, w in zip(plants, was_on)])


def build_hour_qubo(plants, demand_mw, reserve_mw, was_on, incentive, must_on=(), must_off=(), penalty=None,
                    fix_locked=True):
    """QUBO for one hour. With fix_locked, plants that min up/down already force on or off are not
    qubits at all (classical variable fixing): the locked-on ones count toward capacity, and
    qubo.free lists the plants the qubits stand for. Without it, locks are penalty terms (the notebook's way)."""
    block, a, K = encoding(plants)
    c = plant_hour_costs(plants, was_on) + np.asarray(incentive)
    A = 2 * np.abs(c).max() if penalty is None else penalty
    r = np.ceil((demand_mw + reserve_mw) / block)
    if fix_locked:
        locked = set(must_on) | set(must_off)
        free = [i for i in range(len(plants)) if i not in locked]
        r -= sum(a[i] for i in must_on)
        lin = np.r_[c[free], np.zeros(K)]
        b = np.r_[a[free], -(2.0 ** np.arange(K))]
        q = HourQUBO(lin, b, r, A, len(free))
    else:
        free = list(range(len(plants)))
        lin = np.r_[c, np.zeros(K)]
        for i in must_on:
            lin[i] -= A
        for i in must_off:
            lin[i] += A
        q = HourQUBO(lin, np.r_[a, -(2.0 ** np.arange(K))], r, A, len(plants))
    q.free, q.must_on = free, list(must_on)
    return q


@lru_cache(maxsize=4)
def bits_table(n):
    return ((np.arange(2 ** n)[:, None] >> np.arange(n)) & 1).astype(np.float64)


def qaoa_state(phase, n, gammas, betas):
    """Statevector after p layers. phase = E / scale for every basis state."""
    psi = np.full(2 ** n, 2 ** (-n / 2), dtype=np.complex128)
    for g, beta in zip(gammas, betas):
        psi *= np.exp(-1j * g * phase)
        c, s = np.cos(beta), -1j * np.sin(beta)
        for q in range(n):
            v = psi.reshape(-1, 2, 2 ** q)
            a0, a1 = v[:, 0, :].copy(), v[:, 1, :]
            v[:, 0, :] = c * a0 + s * a1
            v[:, 1, :] = s * a0 + c * a1
    return psi


class QAOASampler:
    """Tunes angles on the exact statevector (like the notebook's run_qaoa), warm-starting from the
    previous hour, then draws shots. Also records the probability mass it put on each plant choice."""

    def __init__(self, p=1, maxiter=60):
        self.p, self.maxiter, self.angles = p, maxiter, None

    def probabilities(self, qubo):
        n = qubo.n_qubits
        E = qubo.energies()
        En = (E - E.min()) / max(E.max() - E.min(), 1e-12)
        phase = E / qubo.scale()
        probs_at = lambda ang: np.abs(qaoa_state(phase, n, ang[:self.p], ang[self.p:])) ** 2
        avg = lambda ang: probs_at(ang) @ En
        start = self.angles
        if start is None or len(start) != 2 * self.p:
            grid = [(g, b) for g in np.linspace(0.1, 3.0, 15) for b in np.linspace(0.1, 1.5, 8)]
            g, b = min(grid, key=lambda gb: avg([gb[0]] * self.p + [gb[1]] * self.p))
            start = [g] * self.p + [b] * self.p
        res = minimize(avg, start, method="COBYLA", options={"maxiter": self.maxiter, "rhobeg": 0.2})
        self.angles = res.x
        return probs_at(res.x)

    def sample(self, qubo, shots, rng):
        probs = self.probabilities(qubo)
        return rng.choice(len(probs), size=shots, p=probs / probs.sum()), probs


class RandomSampler:
    def sample(self, qubo, shots, rng):
        n = qubo.n_qubits
        return rng.integers(0, 2 ** n, size=shots), np.full(2 ** n, 2.0 ** -n)


def to_qiskit(qubo, angles, p=1, measure=True):
    """The same circuit as qiskit gates, for hardware or another simulator."""
    from qiskit import QuantumCircuit
    h, J = qubo.ising()
    scale = qubo.scale()
    n = qubo.n_qubits
    qc = QuantumCircuit(n, n if measure else 0)
    qc.h(range(n))
    for layer in range(p):
        g, beta = angles[layer], angles[p + layer]
        for j, hj in enumerate(h):
            if hj != 0:
                qc.rz(2 * g * hj / scale, j)
        for (j, k), Jjk in J.items():
            qc.rzz(2 * g * Jjk / scale, j, k)
        qc.rx(2 * beta, range(n))
    if measure:
        qc.measure(range(n), range(n))
    return qc
