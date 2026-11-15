/*
 * Public build: all code and data live in this folder. No API, CDN, framework,
 * quantum hardware, or Python runtime is needed. Keep the labels in index.html
 * aligned with the plant fields and chart IDs used here.
 */
"use strict";

const STORAGE_KEY = "plant-schedule-public-v1";
const PLANT_FIELDS = [
  { key: "plant_id", label: "Plant ID", type: "text" },
  { key: "type", label: "Plant type", type: "text" },
  { key: "pmin_mw", label: "Minimum output (MW)", type: "number", min: 0, step: "any" },
  { key: "pmax_mw", label: "Maximum output (MW)", type: "number", min: 0, step: "any" },
  { key: "marginal_cost_per_mwh", label: "Marginal cost ($/MWh)", type: "number", min: 0, step: "any" },
  { key: "no_load_cost_per_h", label: "No-load cost ($/h)", type: "number", min: 0, step: "any" },
  { key: "startup_cost", label: "Startup cost ($)", type: "number", min: 0, step: "any" },
  { key: "min_up_h", label: "Minimum hours on", type: "number", min: 0, step: 1 },
  { key: "min_down_h", label: "Minimum hours off", type: "number", min: 0, step: 1 },
  { key: "ramp_mw_per_h", label: "Ramp (MW/h) · not checked in this demo", type: "number", min: 0, step: "any" },
  { key: "on_at_start", label: "On at start?", type: "select" },
  { key: "rts_gen_uid", label: "RTS generator ID · optional", type: "text", optional: true },
  { key: "scale", label: "Scale · metadata", type: "number", min: 0, step: "any" },
];

// This is the 10-plant example from the source app. Embedding it allows file://
// use on a laptop and removes network requests during an audience demo.
const EXAMPLE_PLANTS_CSV = `plant_id,type,pmin_mw,pmax_mw,marginal_cost_per_mwh,no_load_cost_per_h,startup_cost,min_up_h,min_down_h,ramp_mw_per_h,on_at_start,rts_gen_uid,scale
COAL,coal steam,140,350,21.69,546,36750,24,48,240,1,123_STEAM_3,1.0
GAS_CC,gas combined cycle,168,350,26.84,206,27650,8,5,245,0,107_CC_1,0.986
PEAKER_A,gas combustion turbine,20,50,28.89,443,5150,3,3,202,0,113_CT_1,0.909
PEAKER_B,gas combustion turbine (older),20,50,39.51,749,5150,3,3,202,0,223_CT_4,0.909
OIL,oil combustion turbine,20,50,101.02,694,130,1,1,450,0,101_CT_1,2.5
COAL_MID,coal steam (mid size),60,150,21.68,378,22050,8,8,174,1,116_STEAM_1,0.968
COAL_SMALL,coal steam (small),39,100,23.8,145,14700,8,4,158,0,201_STEAM_3,1.316
GAS_CC_2,gas combined cycle,144,300,28.59,262,23700,8,5,210,0,213_CC_3,0.845
PEAKER_C,gas combustion turbine,20,50,25.91,420,5150,3,3,202,0,322_CT_5,0.909
OIL_2,oil combustion turbine,20,50,101.02,694,130,1,1,450,0,101_CT_2,2.5`;
const EXAMPLE_DEMAND = [272, 289, 280, 281, 298, 331, 382, 436, 480, 525, 559, 631,
  654, 677, 697, 700, 634, 585, 547, 529, 508, 448, 391, 346];
const BENCHMARKS = [
  { plants: 5, time: [0.202, 0.195], integral: [0.097, 0.086] },
  { plants: 10, time: [0.198, 0.187], integral: [0.121, 0.098] },
  { plants: 20, time: [0.607, 0.505], integral: [0.400, 0.260] },
  { plants: 40, time: [3.081, 3.021], integral: [1.468, 1.347] },
];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const svgNS = "http://www.w3.org/2000/svg";
const money = (value) => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
const number = (value) => new Intl.NumberFormat().format(value);

/* CSV parsing is shared by the bundled example and audience uploads. Quoted
 * commas, newlines, and doubled quote characters are handled without a library.
 * Data goes into textContent or form values; uploaded text never becomes HTML. */
function parseCsv(text) {
  const records = [];
  let row = [], cell = "", quoted = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; }
      else if (quoted || cell === "") quoted = !quoted;
      else throw new Error("Invalid quote in CSV file.");
    } else if (char === "," && !quoted) {
      row.push(cell); cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      if (row.some((value) => value !== "")) records.push(row);
      row = []; cell = "";
    } else cell += char;
  }
  if (quoted) throw new Error("Unclosed quote in CSV file.");
  row.push(cell);
  if (row.some((value) => value !== "")) records.push(row);
  const header = records.shift();
  const keys = PLANT_FIELDS.map((field) => field.key);
  if (!header || header.length !== keys.length || new Set(header).size !== keys.length ||
      !keys.every((key) => header.includes(key))) {
    throw new Error("Plant CSV columns must match the downloadable example.");
  }
  if (!records.length || records.some((record) => record.length !== header.length)) {
    throw new Error("The CSV needs complete plant rows.");
  }
  return records.map((record) => Object.fromEntries(header.map((key, index) => [key, record[index]])));
}

function validatePlants(rows) {
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > 40) {
    throw new Error("Use between 1 and 40 plants.");
  }
  const ids = new Set();
  return rows.map((raw, index) => {
    const plant = {};
    for (const field of PLANT_FIELDS) {
      const value = raw[field.key];
      if (field.type === "text") {
        plant[field.key] = String(value ?? "").trim();
        if (!field.optional && !plant[field.key]) throw new Error(`Plant ${index + 1}: ${field.label} is required.`);
      } else {
        if (value === "" || value == null || !Number.isFinite(Number(value))) {
          throw new Error(`Plant ${index + 1}: enter a valid ${field.label.toLowerCase()}.`);
        }
        plant[field.key] = Number(value);
        if (plant[field.key] < 0) throw new Error(`Plant ${index + 1}: ${field.label} cannot be negative.`);
        if (field.step === 1 && !Number.isInteger(plant[field.key])) {
          throw new Error(`Plant ${index + 1}: ${field.label} must be a whole number.`);
        }
      }
    }
    if (ids.has(plant.plant_id)) throw new Error(`Duplicate plant ID: ${plant.plant_id}.`);
    ids.add(plant.plant_id);
    if (plant.pmax_mw <= 0 || plant.pmin_mw > plant.pmax_mw) {
      throw new Error(`${plant.plant_id}: maximum output must exceed zero and minimum output.`);
    }
    if (plant.scale <= 0) throw new Error(`${plant.plant_id}: scale must be greater than zero.`);
    if (![0, 1].includes(plant.on_at_start)) throw new Error(`${plant.plant_id}: starting state must be Yes or No.`);
    return plant;
  });
}

function csvForPlants(plants) {
  const keys = PLANT_FIELDS.map((field) => field.key);
  const quote = (value) => /[",\n\r]/.test(String(value)) ? `"${String(value).replaceAll('"', '""')}"` : String(value);
  return [keys.join(","), ...plants.map((plant) => keys.map((key) => quote(plant[key])).join(","))].join("\r\n") + "\r\n";
}

const examplePlants = validatePlants(parseCsv(EXAMPLE_PLANTS_CSV));
const exampleState = () => ({ plants: structuredClone(examplePlants), demand: [...EXAMPLE_DEMAND], reservePercent: 10 });
function validateSavedState(value) {
  const plants = validatePlants(value.plants);
  if (!Array.isArray(value.demand) || value.demand.length !== 24 ||
      value.demand.some((n) => !Number.isInteger(n) || n < 0)) throw new Error("Invalid saved demand.");
  if (!Number.isInteger(value.reservePercent) || value.reservePercent < 0 || value.reservePercent > 50) {
    throw new Error("Invalid saved reserve.");
  }
  return { plants, demand: [...value.demand], reservePercent: value.reservePercent };
}

let state = exampleState();
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) state = validateSavedState(JSON.parse(saved));
} catch (_) {
  // Private browsing, file:// policies, or stale data may block storage.
  // The example still works for this visit; applying edits reports the limit.
}
function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); return true; }
  catch (_) { return false; }
}
function appliedMessage(subject) {
  return `${subject} applied. ${persist() ? "Saved in this browser." : "Browser storage is unavailable; changes last until this page closes."}`;
}

/* Navigation uses normal links, so browser history, copied URLs, and keyboard
 * activation work. A hidden section leaves the accessibility tree as well. */
const PAGES = ["overview", "plants", "demand", "schedule", "report"];
function route(moveFocus = false) {
  const page = location.hash.slice(1);
  const active = PAGES.includes(page) ? page : "overview";
  for (const id of PAGES) document.getElementById(id).hidden = id !== active;
  for (const link of $$('[data-page]')) {
    if (link.dataset.page === active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (moveFocus) {
    const heading = document.getElementById(active).querySelector("h1");
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "auto" });
  }
}
window.addEventListener("hashchange", () => route(true));

/* Plant cards use real labels and native controls. Advanced fields remain
 * available inside details, while the main four are visible immediately. */
function makePlantCard(row, index) {
  const card = document.createElement("article");
  card.className = "plant-card panel";
  const top = document.createElement("div"); top.className = "plant-top";
  const heading = document.createElement("h3"); heading.textContent = row.plant_id || "New plant";
  const remove = document.createElement("button");
  remove.type = "button"; remove.className = "text-button danger"; remove.textContent = "Remove";
  remove.setAttribute("aria-label", `Remove ${heading.textContent}`);
  remove.addEventListener("click", () => {
    if ($$(".plant-card").length === 1) { $("#plants-status").textContent = "Keep at least one plant."; return; }
    const fallback = card.nextElementSibling || card.previousElementSibling;
    card.remove();
    $("#fleet-count").textContent = `Fleet · ${$$(".plant-card").length} plants`;
    $("#plants-status").textContent = `${heading.textContent} removed from the draft. Apply changes to use this fleet.`;
    fallback?.querySelector("input")?.focus();
  });
  top.append(heading, remove); card.append(top);
  const primary = document.createElement("div"); primary.className = "field-grid";
  const extra = document.createElement("div"); extra.className = "field-grid";
  PLANT_FIELDS.forEach((field, fieldIndex) => {
    const label = document.createElement("label"); label.textContent = field.label;
    let control;
    if (field.type === "select") {
      control = document.createElement("select");
      for (const [value, text] of [["0", "No"], ["1", "Yes"]]) {
        const option = document.createElement("option"); option.value = value; option.textContent = text; control.append(option);
      }
    } else {
      control = document.createElement("input"); control.type = field.type;
      if (field.type === "number") { control.min = String(field.min); control.step = String(field.step); }
      if (!field.optional) control.required = true;
    }
    control.value = String(row[field.key] ?? (field.key === "scale" ? 1 : ""));
    control.dataset.field = field.key;
    if (field.key === "plant_id") control.addEventListener("input", () => {
      heading.textContent = control.value.trim() || "New plant";
      remove.setAttribute("aria-label", `Remove ${heading.textContent}`);
    });
    label.append(control);
    (fieldIndex < 4 ? primary : extra).append(label);
  });
  card.append(primary);
  const details = document.createElement("details"); details.className = "advanced-fields";
  const summary = document.createElement("summary"); summary.textContent = "Cost, operating limits, and metadata";
  details.append(summary, extra); card.append(details);
  return card;
}
function renderPlants(rows) {
  const list = $("#plant-list"); list.replaceChildren();
  rows.forEach((row, index) => list.append(makePlantCard(row, index)));
  $("#fleet-count").textContent = `Fleet · ${rows.length} plant${rows.length === 1 ? "" : "s"}`;
}
function collectPlantDraft() {
  const rows = $$(".plant-card").map((card) => Object.fromEntries(
    PLANT_FIELDS.map((field) => [field.key, card.querySelector(`[data-field="${field.key}"]`).value])));
  return validatePlants(rows);
}
// Native validation messages are useful, but a failing advanced field may be
// inside a closed details element. Open it before moving focus to that field.
function checkForm(form) {
  const invalid = form.querySelector(":invalid");
  if (!invalid) return true;
  const details = invalid.closest("details");
  if (details) details.open = true;
  invalid.focus();
  invalid.reportValidity();
  return false;
}
$("#plants-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!checkForm(event.currentTarget)) return;
  try {
    state.plants = collectPlantDraft();
    renderPlants(state.plants);
    invalidateSchedule();
    $("#plants-status").textContent = appliedMessage("Plant changes");
  } catch (error) { $("#plants-status").textContent = error.message; }
});
$("#add-plant").addEventListener("click", () => {
  if ($$(".plant-card").length >= 40) { $("#plants-status").textContent = "This demo supports up to 40 plants."; return; }
  const card = makePlantCard({ scale: 1, on_at_start: 0 }, $$(".plant-card").length);
  $("#plant-list").append(card);
  $("#fleet-count").textContent = `Fleet · ${$$(".plant-card").length} plants`;
  card.querySelector("input").focus();
});
$("#reset-plants").addEventListener("click", () => {
  renderPlants(examplePlants);
  $("#plants-status").textContent = "Example fleet loaded into the form. Apply plant changes to use it.";
});
$("#import-plants").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 200_000) throw new Error("Choose a CSV smaller than 200 KB.");
    const rows = validatePlants(parseCsv(await file.text()));
    renderPlants(rows);
    $("#plants-status").textContent = `${rows.length} plants loaded into the form. Apply plant changes to use them.`;
  } catch (error) { $("#plants-status").textContent = `Import failed: ${error.message}`; }
  event.target.value = "";
});
$("#export-plants").addEventListener("click", () => {
  const blob = new Blob([csvForPlants(state.plants)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a"); link.href = url; link.download = "plants.csv";
  document.body.append(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  $("#plants-status").textContent = "Downloaded the applied plant fleet.";
});

/* Demand values are drafted in the table. Reserve is one percentage across
 * the day, matching the source app. Neither edit affects a schedule until Apply. */
function reserveFor(demand) { return Math.round(demand * Number($("#reserve-percent").value) / 100); }
function draftDemand() {
  return $$("#demand-rows input").map((input) => {
    const value = input.value.trim();
    return value && Number.isInteger(Number(value)) && Number(value) >= 0 ? Number(value) : null;
  });
}
function renderDemand() {
  $("#reserve-percent").value = String(state.reservePercent);
  $("#reserve-value").textContent = `${state.reservePercent}%`;
  const tbody = $("#demand-rows"); tbody.replaceChildren();
  state.demand.forEach((value, hour) => {
    const tr = document.createElement("tr");
    const heading = document.createElement("th"); heading.scope = "row"; heading.textContent = `${String(hour).padStart(2, "0")}:00`;
    const cell = document.createElement("td");
    const input = document.createElement("input"); input.type = "number"; input.min = "0"; input.step = "1";
    input.required = true; input.value = String(value); input.setAttribute("aria-label", `Demand at ${String(hour).padStart(2, "0")}:00 in megawatts`);
    input.addEventListener("input", updateDemandDraft); cell.append(input);
    const reserve = document.createElement("td"); reserve.className = "reserve-cell";
    const required = document.createElement("td"); required.className = "required-cell";
    tr.append(heading, cell, reserve, required); tbody.append(tr);
  });
  updateDemandDraft();
}
function updateDemandDraft() {
  $("#reserve-value").textContent = `${$("#reserve-percent").value}%`;
  const values = draftDemand();
  $$("#demand-rows tr").forEach((tr, index) => {
    const valid = values[index] !== null;
    tr.querySelector(".reserve-cell").textContent = valid ? number(reserveFor(values[index])) : "—";
    tr.querySelector(".required-cell").textContent = valid ? number(values[index] + reserveFor(values[index])) : "—";
  });
  drawDemandChart(values);
}
$("#reserve-percent").addEventListener("input", updateDemandDraft);
$("#demand-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!checkForm(event.currentTarget)) return;
  const values = draftDemand();
  if (values.length !== 24 || values.some((value) => value === null)) {
    $("#demand-status").textContent = "Enter a nonnegative whole number for every hour."; return;
  }
  state.demand = values; state.reservePercent = Number($("#reserve-percent").value);
  invalidateSchedule();
  $("#demand-status").textContent = appliedMessage("Demand changes");
});
$("#reset-demand").addEventListener("click", () => {
  const saved = state;
  state = { ...state, demand: [...EXAMPLE_DEMAND], reservePercent: 10 };
  renderDemand(); state = saved;
  $("#demand-status").textContent = "Example day loaded into the form. Apply demand changes to use it.";
});

/* SVG helpers retain the static title and description children. The visible
 * data tables provide exact values and remain usable with SVG disabled. */
function clearPlot(root) {
  for (const child of [...root.children]) {
    if (!["title", "desc"].includes(child.tagName.toLowerCase())) child.remove();
  }
}
function addSvg(root, tag, attributes, content) {
  const node = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (content !== undefined) node.textContent = String(content);
  root.append(node); return node;
}
function drawDemandChart(values) {
  const root = $("#demand-chart"); clearPlot(root);
  if (values.some((value) => value === null)) {
    addSvg(root, "text", { x: 380, y: 150, "text-anchor": "middle", class: "chart-label" }, "Enter valid hourly demand to draw the chart."); return;
  }
  const left = 56, right = 735, top = 20, bottom = 265;
  const required = values.map((value) => value + reserveFor(value));
  const max = Math.max(100, Math.ceil(Math.max(...required) / 100) * 100);
  const x = (i) => left + (right - left) * i / 23;
  const y = (n) => bottom - (bottom - top) * n / max;
  for (let tick = 0; tick <= 4; tick++) {
    const value = max * tick / 4;
    addSvg(root, "line", { x1: left, x2: right, y1: y(value), y2: y(value), class: "chart-grid" });
    addSvg(root, "text", { x: left - 9, y: y(value) + 4, "text-anchor": "end", class: "chart-label" }, Math.round(value));
  }
  for (const hour of [0, 6, 12, 18, 23]) addSvg(root, "text", { x: x(hour), y: 292, "text-anchor": "middle", class: "chart-label" }, `${hour}:00`);
  const path = (series) => series.map((value, i) => `${i ? "L" : "M"}${x(i)} ${y(value)}`).join(" ");
  addSvg(root, "path", { d: path(values), class: "demand-line" });
  addSvg(root, "path", { d: path(required), class: "required-line" });
}

/* Browser scheduling rules. The stable rule keeps plants on or off for
 * their minimum run times after a switch during this day; unknown pre-day
 * run time is not guessed. Cheapest-first deliberately ignores those limits. */
function plantScore(plant, demand, wasOn, stable) {
  const base = (plant.marginal_cost_per_mwh + plant.no_load_cost_per_h) / plant.pmax_mw;
  return base + (stable && !wasOn ? plant.startup_cost / Math.max(1, demand * 8) : 0);
}
function generateCommitments(mode) {
  const plants = state.plants;
  let previous = plants.map((plant) => Boolean(plant.on_at_start));
  const switchedAt = plants.map(() => -1);
  const result = [];
  state.demand.forEach((demand, hour) => {
    const required = demand + Math.round(demand * state.reservePercent / 100);
    const stable = mode === "stable";
    const on = stable ? [...previous] : plants.map(() => false);
    const locked = (i) => stable && switchedAt[i] >= 0 &&
      hour - switchedAt[i] < (previous[i] ? plants[i].min_up_h : plants[i].min_down_h);
    const capacity = () => plants.reduce((sum, plant, i) => sum + (on[i] ? plant.pmax_mw : 0), 0);
    const minimum = () => plants.reduce((sum, plant, i) => sum + (on[i] ? plant.pmin_mw : 0), 0);
    const ranked = plants.map((_, i) => i).sort((a, b) =>
      plantScore(plants[a], demand, previous[a], stable) - plantScore(plants[b], demand, previous[b], stable));
    for (const i of ranked) {
      if (capacity() >= required) break;
      if (!on[i] && !locked(i)) on[i] = true;
    }
    if (stable) {
      for (const i of [...ranked].reverse()) {
        if (on[i] && !locked(i) && capacity() - plants[i].pmax_mw >= required &&
            minimum() - plants[i].pmin_mw <= demand) on[i] = false;
      }
    }
    on.forEach((value, i) => { if (value !== previous[i]) switchedAt[i] = hour; });
    result.push(on); previous = on;
  });
  return result;
}

/* A one-layer QAOA statevector, simulated locally. Each qubit represents one
 * plant's on/off decision for one hour. The phase separator uses a simplified
 * hourly cost with penalties for capacity, minimum output, and run-time locks.
 * This is a teaching-sized model, distinct from the project's hardware run. */
const QAOA_MAX_PLANTS = 10;
const QAOA_SHOTS = 512;
function qaoaState(phases, gamma, beta) {
  const count = phases.length;
  const real = new Float64Array(count), imag = new Float64Array(count);
  const initial = 1 / Math.sqrt(count);
  for (let mask = 0; mask < count; mask++) {
    real[mask] = initial * Math.cos(gamma * phases[mask]);
    imag[mask] = -initial * Math.sin(gamma * phases[mask]);
  }
  const cosine = Math.cos(beta), sine = Math.sin(beta);
  for (let bit = 1; bit < count; bit *= 2) {
    for (let mask = 0; mask < count; mask++) {
      if (mask & bit) continue;
      const other = mask | bit;
      const ar = real[mask], ai = imag[mask], br = real[other], bi = imag[other];
      real[mask] = cosine * ar + sine * bi;
      imag[mask] = cosine * ai - sine * br;
      real[other] = cosine * br + sine * ai;
      imag[other] = cosine * bi - sine * ar;
    }
  }
  return { real, imag };
}
function qaoaHour(plants, demand, required, previous, switchedAt, hour) {
  const count = 1 << plants.length;
  const energies = new Float64Array(count);
  const feasible = new Uint8Array(count);
  let bestCost = Infinity, worstCost = 0;
  for (let mask = 0; mask < count; mask++) {
    let capacity = 0, minimum = 0, cost = 0, lockBreaks = 0;
    for (let i = 0; i < plants.length; i++) {
      const on = Boolean(mask & (1 << i));
      const plant = plants[i];
      if (on) {
        capacity += plant.pmax_mw;
        minimum += plant.pmin_mw;
        cost += plant.no_load_cost_per_h + plant.pmin_mw * plant.marginal_cost_per_mwh;
        if (!previous[i]) cost += plant.startup_cost;
      }
      if (on !== previous[i] && switchedAt[i] >= 0 &&
          hour - switchedAt[i] < (previous[i] ? plant.min_up_h : plant.min_down_h)) lockBreaks++;
    }
    // Include the dispatch energy above minimum output in the phase cost.
    if (minimum <= demand && capacity >= demand) {
      let remaining = demand - minimum;
      const order = plants.map((_, i) => i).filter((i) => mask & (1 << i))
        .sort((a, b) => plants[a].marginal_cost_per_mwh - plants[b].marginal_cost_per_mwh);
      for (const i of order) {
        const extra = Math.min(remaining, plants[i].pmax_mw - plants[i].pmin_mw);
        cost += extra * plants[i].marginal_cost_per_mwh;
        remaining -= extra;
      }
    }
    const shortfall = Math.max(0, required - capacity);
    const excessMinimum = Math.max(0, minimum - demand);
    feasible[mask] = Number(shortfall === 0 && excessMinimum === 0 && lockBreaks === 0);
    energies[mask] = cost + 100_000 * (shortfall + excessMinimum + lockBreaks);
    if (feasible[mask]) { bestCost = Math.min(bestCost, cost); worstCost = Math.max(worstCost, cost); }
  }
  if (!Number.isFinite(bestCost)) {
    bestCost = Math.min(...energies);
    worstCost = Math.max(...energies);
  }
  // Keep phase angles useful across fleets whose costs have different scales.
  const scale = Math.max(1, worstCost - bestCost);
  const phases = Float64Array.from(energies, (energy) => Math.min(4, (energy - bestCost) / scale));
  let bestExpectation = Infinity, bestReal = null, bestImag = null;
  for (const gamma of [0.5, 1, 2, 4, 6]) {
    for (const beta of [0.3, 0.6, 0.9, 1.2]) {
      const { real, imag } = qaoaState(phases, gamma, beta);
      let expectation = 0;
      for (let mask = 0; mask < count; mask++)
        expectation += (real[mask] ** 2 + imag[mask] ** 2) * phases[mask];
      if (expectation < bestExpectation) {
        bestExpectation = expectation; bestReal = real; bestImag = imag;
      }
    }
  }
  // Simulate finite measurement shots and keep the cheapest feasible sample.
  // If no sample passes the checks, return the lowest-penalty sampled state;
  // the existing rule checker will show any resulting problems.
  const cumulative = new Float64Array(count);
  let total = 0;
  for (let mask = 0; mask < count; mask++) {
    total += bestReal[mask] ** 2 + bestImag[mask] ** 2;
    cumulative[mask] = total;
  }
  let chosen = -1;
  for (let shot = 0; shot < QAOA_SHOTS; shot++) {
    const target = Math.random() * total;
    let low = 0, high = count - 1;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (target < cumulative[middle]) high = middle;
      else low = middle + 1;
    }
    const mask = low;
    if (chosen < 0 || (feasible[mask] && !feasible[chosen]) ||
        (feasible[mask] === feasible[chosen] && energies[mask] < energies[chosen])) chosen = mask;
  }
  return plants.map((_, i) => Boolean(chosen & (1 << i)));
}
function generateQaoaCommitments() {
  const plants = state.plants;
  if (plants.length > QAOA_MAX_PLANTS) {
    throw new Error(`Browser QAOA supports up to ${QAOA_MAX_PLANTS} plants. Choose another rule for larger fleets.`);
  }
  let previous = plants.map((plant) => Boolean(plant.on_at_start));
  const switchedAt = plants.map(() => -1);
  return state.demand.map((demand, hour) => {
    const required = demand + Math.round(demand * state.reservePercent / 100);
    const on = qaoaHour(plants, demand, required, previous, switchedAt, hour);
    on.forEach((value, i) => { if (value !== previous[i]) switchedAt[i] = hour; });
    previous = on;
    return on;
  });
}

function evaluateCommitments(schedule) {
  const plants = state.plants;
  let previous = plants.map((plant) => Boolean(plant.on_at_start));
  const switchedAt = plants.map(() => -1);
  let cost = 0, violationHours = 0, shortfallHours = 0;
  const rows = schedule.map((on, hour) => {
    const demand = state.demand[hour];
    const reserve = Math.round(demand * state.reservePercent / 100);
    const required = demand + reserve;
    const capacity = plants.reduce((sum, plant, i) => sum + (on[i] ? plant.pmax_mw : 0), 0);
    const minimum = plants.reduce((sum, plant, i) => sum + (on[i] ? plant.pmin_mw : 0), 0);
    const problems = [];
    if (capacity < required) { problems.push("Capacity shortfall"); shortfallHours++; }
    if (minimum > demand) problems.push("Minimum output exceeds demand");
    on.forEach((value, i) => {
      if (value === previous[i]) return;
      if (switchedAt[i] >= 0 && hour - switchedAt[i] <
          (previous[i] ? plants[i].min_up_h : plants[i].min_down_h)) {
        problems.push(`${plants[i].plant_id}: minimum ${previous[i] ? "on" : "off"} time`);
      }
      switchedAt[i] = hour;
    });
    // Approximate dispatch: run each online plant at its minimum, then send
    // remaining demand to the lowest marginal-cost plants first. Reserve is
    // available capacity, not energy generated, so it is not charged as MWh.
    if (minimum <= demand && capacity >= demand) {
      let remaining = demand - minimum;
      const order = plants.map((_, i) => i).filter((i) => on[i])
        .sort((a, b) => plants[a].marginal_cost_per_mwh - plants[b].marginal_cost_per_mwh);
      for (const i of order) {
        const extra = Math.min(remaining, plants[i].pmax_mw - plants[i].pmin_mw);
        remaining -= extra;
        cost += (plants[i].pmin_mw + extra) * plants[i].marginal_cost_per_mwh + plants[i].no_load_cost_per_h;
        if (!previous[i]) cost += plants[i].startup_cost;
      }
    }
    if (problems.length) violationHours++;
    previous = on;
    return { hour, demand, reserve, required, capacity, on: on.map((value, i) => value ? plants[i].plant_id : null).filter(Boolean), problems };
  });
  return { rows, cost, violationHours, shortfallHours };
}

function invalidateSchedule() {
  $("#schedule-results").hidden = true;
  $("#schedule-status").textContent = "Inputs changed. Generate a new schedule to see updated results.";
}
function drawScheduleChart(rows) {
  const root = $("#schedule-chart"); clearPlot(root);
  const left = 56, right = 735, top = 20, bottom = 265;
  const max = Math.max(100, Math.ceil(Math.max(...rows.map((row) => Math.max(row.capacity, row.required))) / 100) * 100);
  const slot = (right - left) / 24;
  const y = (n) => bottom - (bottom - top) * n / max;
  for (let tick = 0; tick <= 4; tick++) {
    const value = max * tick / 4;
    addSvg(root, "line", { x1: left, x2: right, y1: y(value), y2: y(value), class: "chart-grid" });
    addSvg(root, "text", { x: left - 9, y: y(value) + 4, "text-anchor": "end", class: "chart-label" }, Math.round(value));
  }
  const points = [];
  rows.forEach((row, i) => {
    const x = left + i * slot + slot * .14;
    addSvg(root, "rect", { x, y: y(row.capacity), width: slot * .72,
      height: bottom - y(row.capacity), class: row.problems.includes("Capacity shortfall") ? "capacity-bar shortfall" : "capacity-bar" });
    points.push(`${x + slot * .36},${y(row.required)}`);
  });
  addSvg(root, "polyline", { points: points.join(" "), class: "required-line" });
  for (const hour of [0, 6, 12, 18, 23]) addSvg(root, "text", {
    x: left + (hour + .5) * slot, y: 292, "text-anchor": "middle", class: "chart-label" }, `${hour}:00`);
}
function metric(label, value, detail) {
  const card = document.createElement("div"); card.className = "metric panel";
  const title = document.createElement("span"); title.textContent = label;
  const strong = document.createElement("strong"); strong.textContent = value;
  const small = document.createElement("small"); small.textContent = detail;
  card.append(title, strong, small); return card;
}
function showSchedule(report) {
  const metrics = $("#schedule-metrics"); metrics.replaceChildren();
  metrics.append(metric("Hours with enough capacity", `${24 - report.shortfallHours} / 24`, "Includes the reserve margin"));
  metrics.append(metric("Hours with a flagged rule", String(report.violationHours), "Capacity, minimum output, or run time"));
  metrics.append(metric("Approximate day cost", report.violationHours ? "—" : money(report.cost),
    report.violationHours ? "Unavailable when a checked rule fails" : "Simple dispatch estimate, not an optimum"));
  const warning = $("#schedule-warning");
  warning.hidden = report.violationHours === 0;
  warning.textContent = report.violationHours ? `${report.violationHours} hour${report.violationHours === 1 ? "" : "s"} need review. Open the hourly table for the reasons.` : "";
  drawScheduleChart(report.rows);
  const body = $("#schedule-rows"); body.replaceChildren();
  report.rows.forEach((row) => {
    const tr = document.createElement("tr");
    const values = [`${String(row.hour).padStart(2, "0")}:00`, number(row.demand), number(row.reserve),
      row.on.join(", ") || "None", number(row.capacity), row.problems.join("; ") || "No checked issue"];
    values.forEach((value, index) => {
      const cell = document.createElement(index === 0 ? "th" : "td");
      if (index === 0) cell.scope = "row";
      cell.textContent = value; tr.append(cell);
    });
    body.append(tr);
  });
  $("#schedule-results").hidden = false;
  $("#schedule-status").textContent = report.violationHours
    ? `Schedule generated. ${report.violationHours} hours have checked issues.`
    : "Schedule generated. No issues found by the demo checks.";
}
const DESCRIPTIONS = {
  stable: "Keeps plants on or off for their minimum run times after a change during the day, then fills demand by a cost ranking.",
  cheap: "Ranks plants by (marginal cost + no-load cost) divided by maximum MW, separately for every hour. It may break operating rules.",
  qaoa: "Classically simulates a one-layer QAOA circuit and 512 measurement shots per hour (up to 10 plants). Results can vary between runs. This is not the QAOA run we did on an actual quantum computer.",
};
$("#algorithm").addEventListener("change", () => {
  $("#algorithm-description").textContent = DESCRIPTIONS[$("#algorithm").value];
  invalidateSchedule();
});
$("#run-schedule").addEventListener("click", () => {
  try {
    const mode = $("#algorithm").value;
    showSchedule(evaluateCommitments(mode === "qaoa" ? generateQaoaCommitments() : generateCommitments(mode)));
  }
  catch (error) { $("#schedule-status").textContent = `Could not generate a schedule: ${error.message}`; }
});

/* These are fixed published medians, never computed from the audience's edited
 * fleet. The data table is intentionally present even when SVG is unsupported. */
function drawBenchmark(selector, key, max, unit) {
  const root = $(selector); clearPlot(root);
  const left = 145, width = 500, bottom = 350;
  for (let tick = 0; tick <= 4; tick++) {
    const x = left + width * tick / 4;
    addSvg(root, "line", { x1: x, x2: x, y1: 55, y2: bottom, class: "chart-grid" });
    addSvg(root, "text", { x, y: 380, "text-anchor": "middle", class: "chart-label" }, `${(max * tick / 4).toFixed(1)}${unit}`);
  }
  addSvg(root, "rect", { x: left, y: 12, width: 14, height: 14, class: "cold-bar" });
  addSvg(root, "text", { x: left + 22, y: 25, class: "chart-label" }, "Cold HiGHS");
  addSvg(root, "rect", { x: left + 175, y: 12, width: 14, height: 14, class: "warm-bar" });
  addSvg(root, "text", { x: left + 198, y: 25, class: "chart-label" }, "Warm-start HiGHS");
  BENCHMARKS.forEach((row, index) => {
    const y = 68 + index * 70;
    addSvg(root, "text", { x: left - 12, y: y + 23, "text-anchor": "end", class: "chart-label" }, `${row.plants} plants`);
    row[key].forEach((value, mode) => {
      const barY = y + mode * 21;
      addSvg(root, "rect", { x: left, y: barY, width: width * value / max, height: 16, class: mode ? "warm-bar" : "cold-bar" });
      addSvg(root, "text", { x: left + width * value / max + 7, y: barY + 13, class: "chart-label chart-value" }, value.toFixed(3));
    });
  });
}

// Initial render. Only applied data is used for the schedule; drafts require
// an explicit Apply action so audiences can see when results need regenerating.
renderPlants(state.plants);
renderDemand();
$("#algorithm-description").textContent = DESCRIPTIONS[$("#algorithm").value];
drawBenchmark("#time-chart", "time", 3.5, " s");
drawBenchmark("#integral-chart", "integral", 1.7, "");
route();
