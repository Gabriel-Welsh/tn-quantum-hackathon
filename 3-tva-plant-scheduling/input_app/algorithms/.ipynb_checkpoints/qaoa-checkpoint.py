"""Gabe's notebook-derived QAOA schedule, run on the local statevector simulator.

The shared run_qaoa_schedule.py contains the notebook's QUBO, QAOA circuit,
hourly sampling, and look-ahead improvements. This wrapper never submits paid
quantum jobs; it supplies only a local simulator schedule to the web app.
"""

from importlib.util import find_spec

NAME = "QAOA"
DESCRIPTION = (
    "QAOA: local one-layer simulator, 200 shots per hour, seed 7, "
    "with the notebook-derived look-ahead and local search."
)


def solve(plants, demand, reserve):
    """Return the same hourly commitment matrix as the reusable QAOA script."""
    # Three slack bits accompany the plant bits. The cap bounds local
    # statevector work, which doubles in size with each extra qubit.
    if len(plants) + 3 > 16:
        raise ValueError("Local QAOA supports up to 13 plants (16 qubits including slack bits).")
    if find_spec("qiskit") is None:
        raise RuntimeError("QAOA needs Qiskit. Run the app in the qBraid-SDK Python environment.")
    # Import only when selected, so the other algorithms work without Qiskit.
    from run_qaoa_schedule import schedule_day

    # No device runner is passed: these shots are local simulator samples.
    # The reusable script's separate CLI owns optional qBraid device jobs.
    schedule, _ = schedule_day(
        plants, demand, reserve, p=1, shots=200, sampler="qaoa", seed=7,
        use_credit=True, lookahead=3, use_local_search=True, verbose=False,
    )
    return schedule
