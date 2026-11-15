# Hardware report data template

The **Quantum hardware report** tab in `index.html` graphs the archived local HiGHS-only medians from `../QUANTUM_WARM_START.md`; these are not complete hybrid runtimes or physical-QPU results. The report no longer displays empty end-to-end or QPU graph templates. `hardware_report.R` can generate standalone SVG charts from the CSVs below. Run the script from `input_app/`:

```bash
Rscript hardware_report.R
```

The script skips a missing CSV, so the two standalone graphs can be completed independently. Copy the header-only `speed_results.example.csv` to `speed_results.csv` and `hardware_results.example.csv` to `hardware_results.csv`, then add **measured** rows. The example files contain no results.

## Runtime comparison: `speed_results.csv`

Each row is one matched trial of MILP and QAOA–MILP on the **same** case and operating rules. Repeat trials under the same hardware and software settings. The graph shows median total seconds with interquartile-range whiskers. Use at most eight case IDs per graph, and one QAOA backend per CSV.

| Column | What to enter |
| --- | --- |
| `case_id` | Stable label for a scheduling case; use the same ID for its repeated trials. |
| `plants`, `hours` | Positive whole numbers describing that case. |
| `trial` | Positive whole-number repeat index, unique within a case. |
| `milp_seconds` | Positive end-to-end wall-clock seconds for MILP alone. |
| `hybrid_seconds` | Positive end-to-end wall-clock seconds, including QAOA preparation and tuning, shots, remote transfer and queue when applicable, and MILP validation or repair. |
| `backend` | One of `local_simulator`, `remote_simulator`, or `qpu`. A simulator speedup is not a QPU speedup. |
| `milp_valid`, `hybrid_valid` | `true` only when the same checker accepts each resulting schedule. The chart rejects invalid rows. |
| `milp_cost`, `hybrid_cost` | Positive total schedule costs under the same cost model. Discuss cost differences in the paragraph below the chart. |

Record the CPU, QPU if used, device queue policy, software versions, shot count, seeds, time limit, and cost model in the page copy or a linked methods note. The current web app has one-hour local-simulator QAOA and full-day MILP; it does **not** yet implement the proposed QAOA–MILP hybrid. Do not fill this CSV with timings from those separate algorithms and label them as a hybrid.

## QPU histogram: `hardware_results.csv`

One row per measured bitstring from **one verified physical QPU job**. The CSV label alone is not proof of a hardware run; check the provider job record and device ID. Do not use a local or remote simulator job for this chart.

| Column | What to enter |
| --- | --- |
| `device_type` | `qpu` on every row. |
| `device_id`, `job_id` | Actual qBraid device and job IDs, repeated on every row. |
| `hour` | Zero-based scheduling hour used to build the circuit, repeated on every row. |
| `bitstring` | Full measured binary string including leading zeroes; qubit 0 is on the right in Qiskit bitstrings. |
| `count` | Nonnegative whole-number shots for that bitstring. |
| `shots` | Positive total shots for the job, repeated on each row; all `count` values must sum to it. |

The histogram shows the 20 most common bitstrings and groups the remaining counts into “Other bitstrings.” Add validity rates and simulator comparisons to the page once those measurements and analysis are available. Only the quantum sampling step runs on the QPU; the MILP step remains classical.
