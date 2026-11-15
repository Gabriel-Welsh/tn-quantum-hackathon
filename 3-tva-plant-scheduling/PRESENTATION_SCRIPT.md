# Speaking script: Quantum warm start for TVA plant scheduling

**Length:** about 9–10 minutes, plus questions. Each part has a suggested speaker time.
**What to have open:** `explanation/TVA_quantum_warm_start.ipynb` (already run, outputs saved), scrolled to the top.
**How to read this script:** plain text is what you say. Lines starting with **[SHOW]** tell you what to put on screen. Lines starting with **[CHECK IT]** tell the audience (or a judge) where to verify the number themselves.

Every number in this script comes from the saved run of `explanation/TVA_quantum_warm_start.ipynb`, or from `explanation/results/*.json` for the history part. If you re-run the notebook, millisecond timings will change slightly. Costs and counts will not.

---

## Part 1. The problem (about 1 minute)

**[SHOW]** Notebook section 1: the plant table and the demand chart.

Every day, TVA has to decide which power plants to switch on for each hour of tomorrow. It sounds simple, but it's a hard yes-or-no puzzle.

Big plants, like coal, are cheap per megawatt-hour, but expensive to start, and once they're on they have to stay on for hours. Small "peaker" plants start fast but cost more to run. Every hour, the plants that are on must exactly meet demand, and must be able to cover demand plus a safety margin called the reserve.

Think of a pizzeria with several ovens. The big oven is cheap per pizza but takes hours to heat up and has to stay lit. The small ovens heat instantly but cost more per pizza. You plan tomorrow's ovens against tomorrow's order forecast.

Our toy version has 5 plants and 24 hours. The cost we care about is the whole day: startups, plus the hourly cost of keeping a plant running, plus fuel.

---

## Part 2. How it's solved today (about 45 seconds)

**[SHOW]** Notebook section 2.

Utilities solve this today with a MILP, a mixed-integer linear program. It's an exact solver: it finds the cheapest legal day and *proves* nothing cheaper exists. On our day, the optimum is **$327,924**, found and proven in about 30 milliseconds.

We also built the simple rule a person might use: "switch on the cheapest plants first until there's enough capacity." It ignores startup costs and minimum on/off times, and it breaks a rule. It switches a peaker off after 2 hours when it has to stay on for 3.

**[CHECK IT]** Notebook section 2 prints both costs and the broken rule. A side note we found along the way: the starter notebook's version of this rule had a small formula mistake, `(marginal + no_load) / pmax` instead of `marginal + no_load / pmax`. That's where the often-quoted +13.80% comes from. Correctly ranked, the rule is +0.81% but still breaks a rule.

---

## Part 3. What we tried, and why we changed direction (about 2 minutes)

**[SHOW]** Notebook section 3: the table, then the summary figure below it (`explanation/figures/07_summary.png`).

We didn't start with our final idea. Here's the honest path, on the 10-plant fleet.

**Attempt 1: QAOA alone, one hour at a time.** QAOA is a quantum algorithm that makes cheap answers more likely to be measured. We gave it one hour at a time, with no classical help. It came out **48% more expensive than the optimum, and broke 28 rules.** The reason: a one-hour problem can't see that a plant started an hour ago must stay on for 8 hours. So plants flicker on and off, and every flicker costs a startup and breaks a rule.

**[CHECK IT]** `explanation/README.md` sections 1 and 1b, and `explanation/figures/01_pure_qaoa_vs_milp.png` and `08_why_pure_qaoa_breaks_rules.png`.

**Attempt 2: add rule checking.** We added classical locks for min up/down times, threw away invalid samples, and polished with local search. Every day became legal, and the cost gap dropped to **about 7.5%**. But it got stuck there, because each hour still can't see the rest of the day. It won't pay to start the gas plant at 5 am, even though it'll be needed anyway from 8 am. And most of the work was now classical.

**[CHECK IT]** `explanation/figures/02_rule_checking.png`.

**Attempt 3: let the QUBO see more of the day.** We grouped hours into blocks, so one quantum problem covers many hours. That worked: **under 1% gap** with blocks, and **0.24%** with the whole day in one problem. The catch is size. The whole day for 10 plants needs **701 qubits**, and the good block versions need 34 or more. That is beyond what we can simulate and beyond today's quantum hardware, so those results came from simulated annealing, a classical stand-in.

**[CHECK IT]** `explanation/figures/03_hour_grouping.png` and `04_qubit_growth.png` (shown in notebook section 3).

**Attempt 4: classical incentives.** A teammate built Lagrangian price signals plus hour-by-hour QAOA plus repair. It reached 0.00% to 0.34%, but the classical parts alone already reached 0.00%.

**[CHECK IT]** `hybrid_uc/ANALYSIS.md` and `hybrid_uc/RESULTS.md`.

**What we learned:** problems small enough for quantum give rough schedules, and problems that give great schedules need hundreds of qubits. So we stopped asking quantum to *replace* the exact solver, and asked it to *help* it.

---

## Part 4. Our solution: the quantum warm start (about 2 minutes)

**[SHOW]** Notebook top cell: the one-sentence idea and the step table.

Our solution has four steps. Here's the analogy: imagine a sudoku contest where you must prove your answer is the best one. If a friend hands you a nearly finished grid at the start, you can skip every line of attack that can't beat it. Quantum is the friend. The classical solver still does the proof.

**Step 1. Make the whole day fit on 20 qubits.**
**[SHOW]** Section 4, the block chart.
Instead of one qubit per plant per hour, which would be 120 qubits, we group the day into 4 blocks of similar demand: night, morning ramp, afternoon peak, evening. Each plant gets one qubit per block: on or off for that block. 5 plants × 4 blocks = 20 qubits.

**Be upfront about this:**
**[SHOW]** Section 4, the "honest check" output.
We checked every one of the million possible answers. The quantum problem's own best answer is **not a legal day.** It's cheap because it leaves the afternoon short of capacity. The penalty for being short is soft, and blocks are coarse. So we never use quantum's answer directly.

**Step 2. Run QAOA.**
**[SHOW]** Section 5, the histogram.
We run QAOA on a simulator and measure it 4,000 times. Next to it is the fair comparison: 4,000 random guesses. Green is QAOA, yellow is random. **69% of QAOA's shots land in the cheapest 5% of all possible schedules, against about 6% for random guessing.** So QAOA is really doing something.

**Step 3. Repair it into a legal day: the start state.**
**[SHOW]** Section 6, the three schedule strips.
We take the 50 cheapest QAOA answers and repair them with simple rules: switch on the cheapest plant where capacity is short, keep a plant on for its minimum time, and so on. Then we keep the cheapest legal one. The top strip is QAOA's raw answer, with red crosses where rules are broken. The middle strip is after repair: legal, **$331,596, just 1.12% above the optimum.** The bottom strip is the true optimum, for comparison.

**Step 4. Hand it to the exact solver.**
**[SHOW]** Section 7, the three timeline charts.
We give that legal day to the same MILP solver utilities use, as its starting point. Look at the left chart, 5 plants. The dashed blue line is the solver on its own. For the first 14 milliseconds (the shaded area) it has no legal day at all, and its first answer is about 18% too expensive. The green line is with our quantum start: a legal day within about 1% from time zero. **Both finish at the proven optimum, $327,924.** The quantum start can never make the answer worse, because the solver still proves it's the best.

---

## Part 5. Results: the judges' checklist (about 1.5 minutes)

**[SHOW]** Notebook section 9, "All results on one page."

**Daily cost.**
- Exact MILP: $327,924, 0 rules broken.
- Cheapest-first rule: $330,594, +0.81%, **1 rule broken**.
- QAOA's raw best answer: −4.39%, but **7 rules broken**. It's only "cheap" because it's illegal.
- QAOA plus repair, our start state: $331,596, +1.12%, 0 rules broken.
- Warm-started MILP, our final answer: **$327,924, the proven optimum, 0 rules broken.**

**How often answers were valid.** As sampled, only **2.4%** of QAOA's shots are legal days, against **0.1%** for random guessing. After repair, **100%** are legal, and that's true for random guesses too. So the "valid" number is mostly the repair's work, and we say so.

**Cold vs warm solver.** With the quantum start, a legal near-optimal day is available at **0 ms** at every size we tried. The primal-dual integral, which measures how long the solver spends without a good answer, drops **8%** at 5 plants, **37%** at 20 plants and **4%** at 40 plants. Time to the *proven* optimum barely changes: 34 → 32 ms at 5 plants.

**[CHECK IT]** Section 7's table: "1st answer", "proven opt.", "nodes", "P-D integral". For 20 and 40 plants the quantum step is simulated annealing, because 80 and 160 qubits are too many to simulate. The notebook labels it.

---

## Part 6. Hardware vs simulator (about 1 minute)

**[SHOW]** Notebook section 8: the table, then the curves.

Real hardware needs short circuits. So for the device run we use the smallest version of the same problem: 2 blocks, 10 qubits, one QAOA layer, **50 two-qubit gates**. We train the angles on the simulator and send the exact same circuit to each backend with 200 shots.

- Noiseless simulator: **34%** of shots in the cheapest 5% of schedules.
- **IonQ's simulator with the Forte-1 hardware noise model: 22%.** Noise costs some quality, but it's still far above random.
- Random guessing: **4%**.

All three still end at the same start, +1.12%, and the same proven optimum. That's the design point: noise makes the samples worse, but repair still makes them legal and the solver still proves the best answer.

The IonQ noisy-simulator job ID is printed in the table: `ionq:ionq:sim:simulator-842a-qjob-6af901e4c8f5265fb3f21de4`. It took **16 seconds** from submission to result, including the queue.

**[SAY ONE OF THESE, depending on whether the QPU run happened]**
- *If not run:* "We have not run the real IonQ Forte QPU yet. At 200 shots it's estimated at about 1,630 credits, which is more than our remaining balance. The notebook has the QPU cell ready, with a cost guard that refuses to submit above a set limit."
- *If run:* "On the real IonQ Forte QPU, job ID [from section 8], [X]% of shots landed in the cheapest 5%, and the whole run took [Y] seconds including the queue."

**[CHECK IT]** `warm_start_results/hardware_runs.json` has every job ID, the device, shots, status and raw counts. The jobs are also in the qBraid **Quantum Jobs** panel.

---

## Part 7. Honest assessment (about 1 minute)

**[SHOW]** Notebook section 10.

Here's where quantum honestly stands on this problem.

**What works:** the pipeline runs end to end, from QAOA to start state to proven optimum. QAOA clearly beats random guessing at finding cheap schedules, and that survives a realistic hardware noise model.

**What doesn't, yet:**
- **No real speed-up on this data.** The solver proves the optimum without any branching (1 node) at every size we tried, so there's nothing for a head start to cut. And the quantum step takes about **8 seconds** on a simulator, while the exact solver alone takes about **30 milliseconds**. End to end, the classical solver is faster today.
- With 4,000 shots, random guessing plus repair finds the same start. QAOA's advantage shows when shots are limited.
- The repair step, which is classical, does a lot of the work.

**What would have to change:** problems that make the exact solver branch hard (ramp limits, multi-day horizons, many similar plants, transmission limits), quantum hardware big and clean enough to run finer versions of the problem, and queue times in seconds, not minutes.

---

## Part 8. Customer and value (about 45 seconds)

**Who would use it:** the day-ahead unit-commitment desk at a utility like TVA. Today they use a MILP solver like HiGHS or a commercial one. Our method doesn't replace that solver. It plugs in as a **starting-solution provider**, which these solvers already accept as a standard input. That makes it low-risk to trust: the solver still guarantees the optimum, so a bad quantum start can waste a little time but can't produce a wrong schedule.

**What it would take to trust it:** evidence on their own hard cases that it shortens time to a good answer, including the hardware queue time. That's exactly what we couldn't show on a toy day.

**Value scenario. Fill in before presenting, with a real, dated, sourced number:**
> "TVA reported **$[X] billion** in fuel and purchased-power expense in fiscal year **[YEAR]** (source: **[TVA 10-K / annual report, page]**). Our method can only affect the part driven by commitment decisions, the fuel, startup and no-load costs of TVA's own plants, not contracted purchased power. If that part is **$[Y] billion**, a 1% change would be **$[Y × 0.01]** per year. This is a scenario, not proven savings, and we are not scaling our toy day up to TVA's size."

---

## Closing (about 15 seconds)

To sum up: quantum doesn't replace the exact solver, it gives it a head start. QAOA finds a near-optimal day, classical repair makes it legal, and the MILP proves the perfect answer. On today's toy problem the head start is real but small. On harder problems, with better hardware, that's where the speed-up would come from. Thank you.

---

## Likely questions and short answers

**"Why not just use QAOA's answer?"**
Its best answer breaks rules. We checked every possible answer, and the QUBO's own optimum leaves the afternoon short of capacity (notebook section 4). The QUBO is a coarse approximation, so repair and the exact solver guarantee correctness.

**"Is the quantum part doing anything, or is it all repair?"**
Both, and we measured it. QAOA puts 69% of shots in the cheapest 5% of schedules against 6% for random (section 5), and 2.4% of its raw shots are legal against 0.1%. But after repair, random guesses also become legal, and with 4,000 shots random plus repair finds the same start. QAOA's edge is when shots are scarce (`warm_start_vs_milp.ipynb` section 3: at 20–1,000 shots its median start is +1.8–3.0% against +4.4–6.0% for random).

**"Did it speed up the MILP?"**
It gives the solver a good legal answer at time zero, and lowers the primal-dual integral by 4–37%. Time to the proven optimum is within noise, because these problems solve without branching. The quantum step itself takes much longer than the MILP today.

**"Why does the starter notebook show no broken rules?"**
It also corrects its output classically. It locks plants with min up/down times and throws away invalid samples. It also uses one-hour problems with helper (slack) qubits that make the capacity rule exact. And in its own results, random guessing scored the same as QAOA (+7.06%).

**"How long including the hardware queue?"**
IonQ noisy simulator: 16 s submission to result. Real QPU: [fill in if run]. Exact MILP alone: about 30 ms.

**"How many qubits and gates?"**
Simulator: 20 qubits, 2 QAOA layers. Hardware circuit: 10 qubits, 1 layer, 50 two-qubit gates, within IonQ's "few dozen" guideline.

**"What did you get wrong along the way?"**
Pure QAOA scaled badly (+48%, 28 rules broken at 10 plants). Our block QUBO's best answer is illegal. And the starter's cheapest-first formula had a mistake we only caught late.

---

## Where to see everything yourself

| What | Where |
|---|---|
| The whole story, runnable, with outputs | `explanation/TVA_quantum_warm_start.ipynb` (sections 1–10) |
| Deeper comparison: shots-vs-seeds sweep, 10-plant case, random-start control | `warm_start_vs_milp.ipynb` |
| The pipeline code | `quantum_warm_start_milp.py` (`Qubo`, `solve_qaoa`, `repair`, `full_solution`, `run_highs`) |
| Plain-language explanation of the pipeline | `QUANTUM_WARM_START.md` |
| Official rule checker and MILP baseline | `check.py` (`check_schedule`, `solve_milp`) |
| History: pure QAOA → rules → blocks → warm start | `explanation/README.md`, `explanation/figures/01`–`08`, `explanation/results/*.json` |
| Lagrangian incentives experiment | `hybrid_uc/ANALYSIS.md`, `hybrid_uc/RESULTS.md` |
| Starter hour-by-hour QAOA (+7.06%) | `starter.ipynb` section 5 |
| Hardware job IDs, raw counts, timing | `warm_start_results/hardware_runs.json`, qBraid Quantum Jobs panel |
| Interactive schedule editor (what-if tool) | `input_app/` (see its README) |
