// Jupyter checkpoint of schedule.js, not served by server.py. This snapshot
// discovers Python algorithms, requests a saved-input schedule, and renders
// the hourly table, stacked capacity chart, and editable quantum case draft.
// The live renderer is ../schedule.js; change it, ../index.html, and
// ../server.py as needed. Jupyter may overwrite this checkpoint automatically.
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

try { caseBox.value = localStorage.getItem(caseStorageKey) || caseBox.value; } catch (_) { /* Storage is optional. */ }
caseBox.addEventListener("input", () => {
  try { localStorage.setItem(caseStorageKey, caseBox.value); } catch (_) { /* Keep editing available. */ }
});

function showDescription() {
  description.textContent = algorithms.find((item) => item.id === algorithmSelect.value)?.description || "";
}

function svgElement(tag, attributes) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

function showChart(result) {
  chart.replaceChildren();
  chartLegend.replaceChildren();
  const left = 55;
  const top = 18;
  const plotWidth = 885;
  const plotHeight = 300;
  const bottom = top + plotHeight;
  const highest = Math.max(0, ...result.hours.map((hour) =>
    Math.max(hour.capacity_mw, hour.demand_mw + hour.reserve_mw)));
  const maxMW = Math.max(100, Math.ceil(highest / 100) * 100);
  const slot = plotWidth / result.hours.length;
  const barWidth = slot * 0.68;
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
  chart.append(svgElement("polyline", {
    points: requiredPoints.join(" "), class: "schedule-chart-required",
  }));

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
    for (const issue of result.violations.slice(0, 10)) {
      const item = document.createElement("li");
      item.textContent = `Hour ${issue.hour}: ${issue.plant} — ${issue.rule}: ${issue.detail}`;
      list.append(item);
    }
    summary.append(list);
  }
}

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

document.querySelector("#run-schedule").addEventListener("click", runSchedule);
algorithmSelect.addEventListener("change", showDescription);

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

loadAlgorithms();
