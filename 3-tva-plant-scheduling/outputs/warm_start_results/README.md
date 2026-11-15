# outputs/warm_start_results

| File | What it is |
|---|---|
| `hardware_runs.json` | Cache of every quantum-device job from the warm-start notebooks (`../../TVA_quantum_warm_start.ipynb` §8, `../../notebooks/warm_start_vs_milp.ipynb` §7). For each backend: device, job ID, shots, status, estimated credits, CX count and depth, submission/finish times, time from submission to result, and the raw counts |

The notebooks read this file first, so re-running them never resubmits a finished job. Delete an entry to force a fresh run. Jobs also appear in the qBraid **Quantum Jobs** panel.
