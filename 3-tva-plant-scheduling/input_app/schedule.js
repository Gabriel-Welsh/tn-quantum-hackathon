// Plant schedule view for #schedule in index.html. /api/algorithms lists the
// Python files discovered in algorithms/; /api/schedule runs the selected
// function on saved CSVs and returns plants, hourly on/off choices, cost, and
// checker violations. This file renders that result but never changes inputs.
// Keep these IDs aligned with index.html if the page markup changes.
const algorithmSelect = document.querySelector("#schedule-algorithm");
const description = document.querySelector("#schedule-description");
const status = document.querySelector("#schedule-status");
const summary = document.querySelector("#schedule-summary");
const table = document.querySelector("#schedule-table");
const rows = document.querySelector("#schedule-rows");
const chartPanel = document.querySelector("#schedule-chart-panel");
const chart = document.querySelector("#schedule-chart");
const chartLegend = document.querySelector("#schedule-chart-legend");
const caseBox = document.querySelector("#quantum-case");
const caseStorageKey = "plant-scheduling-quantum-case";
let algorithms = [];

// The HTML textarea contains the starter pitch. A browser-local edit overrides
// it on later visits; storage failures should never block scheduling.
try { caseBox.value = localStorage.getItem(caseStorageKey) || caseBox.value; } catch (_) { /* Storage is optional. */ }
caseBox.addEventListener("input", () => {
  try { localStorage.setItem(caseStorageKey, caseBox.value); } catch (_) { /* Keep editing available. */ }
});

// The selector IDs come from Python filenames; labels and descriptions come
// from each module's NAME and DESCRIPTION constants.
function showDescription() {
  description.textContent = algorithms.find((item) => item.id === algorithmSelect.value)?.description || "";
}

// SVG elements need their own namespace. This helper sets attributes without
// building HTML strings, so plant IDs are always treated as text.
function svgElement(tag, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

// Draw a stacked bar for each hour. Every colored segment is an online plant's
// pmax_mw (available capacity), not its actual dispatched output. The overlaid
// line is demand_mw + reserve_mw. Update the SVG viewBox in index.html if these
// plot coordinates change; styles.css owns axes and line styling.
function showChart(result) {
  chart.replaceChildren();
  chartLegend.replaceChildren();
  const left = 55;
  const top = 18;
  const plotWidth = 885;
  const plotHeight = 300;
  const bottom = top + plotHeight;
  // Give the Y axis headroom above both the tallest stack and requirement line.
  const highest = Math.max(0, ...result.hours.map((hour) =>
    Math.max(hour.capacity_mw, hour.demand_mw + hour.reserve_mw)));
  const maxMW = Math.max(100, Math.ceil(highest / 100) * 100);
  const slot = plotWidth / result.hours.length;
  const barWidth = slot * 0.68;
  // Plant order is stable in the API response, so a plant keeps one color
  // across all hours. The golden-angle spacing accommodates additional plants.
  const colors = new Map(result.plants.map((plant, index) =>
    [plant.id, `hsl(${(210 + index * 137.5) % 360} 62% 43%)`]));

  for (let step = 0; step <= 4; step++) {
    const y = bottom - step * plotHeight / 4;
    chart.append(svgElement("line", {
      x1: left, x2: left + plotWidth, y1: y, y2: y, class: "schedule-chart-grid",
    }));
    const label = svgElement("text", {
      x: left - 8, y: y + 4, "text-anchor": "end", class: "schedule-chart-axis",
    });
    label.textContent = Math.round(maxMW * step / 4).toLocaleString();
    chart.append(label);
  }
  const units = svgElement("text", { x: 7, y: 14, class: "schedule-chart-axis" });
  units.textContent = "MW";
  chart.append(units);

  // Draw bar layers from the bottom upward. Each rect gets a native SVG title
  // for hover details; only every third hour is labeled to avoid crowding.
  const requiredPoints = [];
  result.hours.forEach((hour, index) => {
    const x = left + index * slot + (slot - barWidth) / 2;
    const on = new Set(hour.plants_on);
    let stackTop = bottom;
    for (const plant of result.plants) {
      if (!on.has(plant.id)) continue;
      const height = plant.pmax_mw / maxMW * plotHeight;
      stackTop -= height;
      const bar = svgElement("rect", {
        x, y: stackTop, width: barWidth, height, fill: colors.get(plant.id),
      });
      const title = svgElement("title", {});
      title.textContent = `${String(hour.hour).padStart(2, "0")}:00 · ${plant.id}: ${plant.pmax_mw} MW capacity`;
      bar.append(title);
      chart.append(bar);
    }
    const center = x + barWidth / 2;
    const requiredY = bottom - (hour.demand_mw + hour.reserve_mw) / maxMW * plotHeight;
    requiredPoints.push(`${center},${requiredY}`);
    if (index % 3 === 0 || index === result.hours.length - 1) {
      const tick = svgElement("text", {
        x: center, y: bottom + 22, "text-anchor": "middle", class: "schedule-chart-axis",
      });
      tick.textContent = `${String(hour.hour).padStart(2, "0")}:00`;
      chart.append(tick);
    }
  });
  // Draw the requirement line last so it remains visible over the colored bars.
  chart.append(svgElement("polyline", {
    points: requiredPoints.join(" "), class: "schedule-chart-required",
  }));

  // Build the legend from the same color map as the bars; no manual updates
  // are needed when a new plant is added to the saved CSV.
  for (const plant of result.plants) {
    const item = document.createElement("span");
    const swatch = document.createElement("i");
    swatch.style.backgroundColor = colors.get(plant.id);
    item.append(swatch, plant.id);
    chartLegend.append(item);
  }
  const requiredItem = document.createElement("span");
  const line = document.createElement("i");
  line.className = "required-key";
  requiredItem.append(line, "Demand + reserve");
  chartLegend.append(requiredItem);
  chartPanel.hidden = false;
}

// Pair the chart with an explicit hourly table and checker summary. The
// backend checks demand, reserve, operating limits, and ramps; schedules with
// rule violations remain visible so developers can inspect the first issues.
function showSchedule(result) {
  showChart(result);
  rows.replaceChildren();
  for (const hour of result.hours) {
    const tr = document.createElement("tr");
    for (const value of [`${String(hour.hour).padStart(2, "0")}:00`, hour.demand_mw, hour.reserve_mw,
                         hour.plants_on.join(", ") || "None", hour.capacity_mw]) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    rows.append(tr);
  }
  table.hidden = false;
  summary.replaceChildren();
  const report = document.createElement("p");
  report.textContent = result.valid
    ? `${result.name}: valid for the modeled demand, reserve, plant limits, and ramps. Estimated day cost: $${result.total_cost.toLocaleString()}.`
    : `${result.name}: ${result.violations.length} rule violation(s). Review this schedule before using it.`;
  summary.append(report);
  if (!result.valid) {
    const list = document.createElement("ul");
    // Limit the visible list so a poor algorithm does not bury the schedule.
    for (const issue of result.violations.slice(0, 10)) {
      const item = document.createElement("li");
      item.textContent = `Hour ${issue.hour}: ${issue.plant} — ${issue.rule}: ${issue.detail}`;
      list.append(item);
    }
    summary.append(list);
  }
}

// Recompute from saved plants.csv and demand.csv. Clear old results before
// fetching so they cannot be mistaken for the current algorithm's output.
async function runSchedule() {
  if (!algorithmSelect.value) return;
  status.textContent = "Generating schedule…";
  table.hidden = true;
  chartPanel.hidden = true;
  summary.replaceChildren();
  try {
    const response = await fetch(`api/schedule?algorithm=${encodeURIComponent(algorithmSelect.value)}`);
    if (!response.ok) throw new Error(await response.text());
    showSchedule(await response.json());
    status.textContent = "Generated from the saved plants.csv and demand.csv files.";
  } catch (error) {
    status.textContent = `Schedule failed: ${error.message}`;
  }
}

// The button reruns after saved input changes; selecting an algorithm updates
// its description until the user explicitly generates its schedule.
document.querySelector("#run-schedule").addEventListener("click", runSchedule);
algorithmSelect.addEventListener("change", showDescription);

// Fill the selector from the server's automatic Python-module discovery.
// Prefer the classical baseline on initial load, then generate its schedule.
// Adding an algorithms/*.py file needs no JavaScript change; refresh the page
// to fetch the new list. Errors appear in the schedule status area.
async function loadAlgorithms() {
  try {
    const response = await fetch("api/algorithms");
    if (!response.ok) throw new Error(await response.text());
    algorithms = await response.json();
    algorithmSelect.replaceChildren();
    for (const algorithm of algorithms) {
      const option = document.createElement("option");
      option.value = algorithm.id;
      option.textContent = algorithm.name;
      algorithmSelect.append(option);
    }
    if (!algorithms.length) throw new Error("No algorithms are installed");
    algorithmSelect.value = algorithms.some((item) => item.id === "classical_baseline")
      ? "classical_baseline" : algorithms[0].id;
    showDescription();
    await runSchedule();
  } catch (error) {
    status.textContent = `Could not load algorithms: ${error.message}`;
  }
}

loadAlgorithms(); // Initialize the selector and first schedule on page open.
