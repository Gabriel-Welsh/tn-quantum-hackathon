# notebooks

Supporting notebooks. **The submission notebook is [`../TVA_quantum_warm_start.ipynb`](../TVA_quantum_warm_start.ipynb), in the project folder.** Use the **qBraid-SDK (v0.12.2)** kernel. Each notebook finds the project folder itself, so it runs from here.

| File | What it is |
|---|---|
| `starter.ipynb` | The organizers' starter, with our TODOs filled in: MILP baseline, cheapest-first rule, one-hour QUBO, QAOA hour by hour (+7.06%), IonQ simulator cell |
| `qaoa_primer.ipynb` | Organizers' QAOA primer on Max-Cut (cost layer, mixer, optimizer) |
| `qaoa_improvements.ipynb` | Diagnosis of the hour-by-hour loop, a look-ahead QUBO, and INTERP angle initialization |
| `warm_start_vs_milp.ipynb` | Deeper benchmark of our warm start: QAOA vs random across shots and seeds, 5/10/20/40-plant cold vs warm HiGHS, random-start control, hardware vs simulator |
| `hybrid_uc_interface.ipynb` | Interactive front end for `../hybrid_uc/`: enter a fleet, run Lagrangian incentives + QAOA + repair, compare with the MILP |
