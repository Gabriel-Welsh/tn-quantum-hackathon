"""End to end for one fleet and one demand curve.

    python -m hybrid_uc.run                                  # data/plants.csv + data/demand.csv
    python -m hybrid_uc.run --plants my_fleet.csv --demand my_day.csv
    python -m hybrid_uc.run --interactive --save-plants my_fleet.csv
    python -m hybrid_uc.run --synthetic 12                   # a generated 12-plant fleet
    python -m hybrid_uc.run --sampler random --shots 50      # honesty check

Stages: (1) classical incentives (Lagrangian prices + cost-to-go), (2) hour-by-hour QAOA with those
incentives, (3) classical repair + certificate. Prints the MILP optimum for comparison unless --no-milp.
"""
import argparse
import os
import time

import numpy as np

import check
from . import fleet, incentives, pipeline, qaoa, repair

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--plants", default=os.path.join(HERE, "data", "plants.csv"), help="fleet CSV (plants.csv columns)")
    src.add_argument("--interactive", action="store_true", help="type the fleet in: number of plants, then each plant")
    src.add_argument("--synthetic", type=int, metavar="N", help="generate an N-plant fleet from the 5 templates")
    ap.add_argument("--demand", default=os.path.join(HERE, "data", "demand.csv"), help="CSV with demand_mw [, reserve_mw]")
    ap.add_argument("--reserve-pct", type=float, help="reserve as a share of demand, if the CSV has no reserve_mw")
    ap.add_argument("--rescale-demand", action="store_true",
                    help="scale the demand curve so peak demand + reserve = 90%% of the fleet's capacity")
    ap.add_argument("--save-plants", help="write the fleet to this CSV (handy after --interactive)")
    ap.add_argument("--mode", default="lagrangian", choices=["lagrangian", "amortize", "none"])
    ap.add_argument("--sampler", default="qaoa", choices=["qaoa", "random", "exact"])
    ap.add_argument("--shots", type=int, default=200)
    ap.add_argument("--p", type=int, default=1, help="QAOA layers")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-repair", action="store_true")
    ap.add_argument("--no-milp", action="store_true", help="skip the MILP (for fleets where it is slow)")
    ap.add_argument("--out", help="write the final schedule to this CSV")
    ap.add_argument("--export-hour", type=int, help="write that hour's tuned QAOA circuit as OpenQASM 2")
    a = ap.parse_args()

    if a.interactive:
        plants = fleet.prompt_fleet()
    elif a.synthetic:
        plants = fleet.synthetic_fleet(a.synthetic, seed=a.seed)
    else:
        plants = fleet.load_fleet(a.plants)
    if a.save_plants:
        fleet.save_fleet(plants, a.save_plants)
        print(f"fleet saved to {a.save_plants}")
    D, R = fleet.load_demand(a.demand, a.reserve_pct)
    if a.rescale_demand or a.synthetic:
        D, R = fleet.scaled_demand(plants, D, R)
    n, T = len(plants), len(D)
    block, blocks, K = qaoa.encoding(plants)
    print(f"{n} plants, {T} hours, total capacity {sum(p['pmax_mw'] for p in plants):,.0f} MW, "
          f"peak demand + reserve {(D + R).max():,.0f} MW")
    print(f"QUBO per hour: {n} plant qubits + {K} slack = {n + K} qubits (capacity in {block:.0f} MW blocks)")
    if a.sampler == "qaoa" and n + K > 22:
        raise SystemExit(f"{n + K} qubits is too many for the statevector simulator here (limit 22). "
                         "Use --sampler random, a smaller fleet, or export circuits for hardware.")

    t0 = time.perf_counter()
    inc = incentives.lagrangian(plants, D, R)
    t_inc = time.perf_counter() - t0
    print(f"\n[1] incentives: Lagrangian lower bound ${inc.lower_bound:,.0f} "
          f"({len(inc.history)} price updates, {t_inc:.2f} s)")
    print("    energy price by hour ($/MWh):", " ".join(f"{x:.0f}" for x in inc.lam))

    t0 = time.perf_counter()
    sched, log = pipeline.run_day(plants, D, R, inc, mode=a.mode, sampler=a.sampler, shots=a.shots, seed=a.seed, p=a.p)
    t_q = time.perf_counter() - t0
    label = lambda c: "+".join(p["plant_id"] for p, u in zip(plants, c) if u) or "none"
    print(f"\n[2] hour by hour ({a.sampler}, {a.mode} incentives, {a.shots} shots, {t_q:.1f} s)")
    print(f"    {'hour':>4}  {'need MW':>8}  {'P(pick)':>8}  {'distinct':>8}  choice")
    for row in log:
        pp = "-" if row["p_pick"] is None else f"{row['p_pick']:.3f}"
        print(f"    {row['hour']:>4}  {D[row['hour']] + R[row['hour']]:>8.0f}  {pp:>8}  {row['n_unique']:>8}  {label(row['pick'])}")

    milp_cost = None
    if not a.no_milp:
        milp_cost, _, _, secs = check.solve_milp(plants, D, R)
        print(f"\nMILP optimum ${milp_cost:,.0f} ({secs:.2f} s)")
    final = sched
    if not a.no_repair:
        t0 = time.perf_counter()
        final, rep = repair.repair(plants, D, R, sched, inc.lower_bound, milp_cost)
        cost, broken = repair.Scorer(plants, D, R).total(final)
        if not broken:      # tighten the certificate: re-run the price search aiming at the cost we reached
            inc2 = incentives.lagrangian(plants, D, R, upper_bound=cost, start=(inc.lam, inc.mu))
            if inc2.lower_bound > inc.lower_bound:
                rep["lower_bound"] = inc2.lower_bound
                rep["certified_gap_before"] = 100 * (rep["cost_before"] - inc2.lower_bound) / inc2.lower_bound
                rep["certified_gap_after"] = 100 * (cost - inc2.lower_bound) / inc2.lower_bound
        print(f"\n[3] classical repair + certificate ({time.perf_counter() - t0:.2f} s)")
        print("    " + repair.describe(rep).replace("\n", "\n    "))
    print()
    check.check_schedule(plants, D, R, final, milp_cost=milp_cost)

    if a.out:
        with open(a.out, "w") as f:
            f.write("hour," + ",".join(p["plant_id"] for p in plants) + "\n")
            for t, row in enumerate(final):
                f.write(f"{t}," + ",".join(str(int(x)) for x in row) + "\n")
        print(f"schedule written to {a.out}")
    if a.export_hour is not None:
        if a.sampler != "qaoa":
            raise SystemExit("--export-hour needs --sampler qaoa")
        from qiskit import qasm2
        row = log[a.export_hour]
        qc = qaoa.to_qiskit(row["qubo"], row["angles"], p=a.p)
        path = f"qaoa_hour{a.export_hour}.qasm"
        with open(path, "w") as f:
            f.write(qasm2.dumps(qc))
        print(f"hour {a.export_hour} circuit ({qc.num_qubits} qubits) written to {path}")


if __name__ == "__main__":
    main()
