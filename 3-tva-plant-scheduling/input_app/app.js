// Demand and reserve editor for the #demand section of index.html.
// Startup: GET saved demand.csv via /api/demand, build one input row per hour,
// and draw the chart. Edits stay in the browser until the form POSTs every hour
// to /api/demand; server.py validates and writes the CSV. Keep these selectors
// in sync with index.html when changing the page.
const form = document.querySelector("#demand-form");
const hoursBody = document.querySelector("#hours");
const chart = document.querySelector("#demand-chart");
const status = document.querySelector("#demand-status");
const reserveSlider = document.querySelector("#reserve-percent");
const reserveOutput = document.querySelector("#reserve-percent-value");
const SVG_NS = "http://www.w3.org/2000/svg";

// Create one SVG child using DOM APIs, then append it to the chart.
function svgElement(tag, attributes, text) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text !== undefined) element.textContent = text;
  chart.append(element);
  return element;
}

// One slider controls reserve in every row; round each hour to a whole MW.
function reserveFor(demand) {
  return Math.round(demand * Number(reserveSlider.value) / 100);
}

// Read the current form rather than storing a second copy of demand state.
// Reserve is derived from the slider; null marks an invalid row for chart and Save.
function getRows() {
  return [...hoursBody.querySelectorAll("tr")].map((tr) => {
    const demandInput = tr.querySelector('[data-field="demand_mw"]');
    const demand = Number(demandInput.value);
    if (!demandInput.value || !Number.isInteger(demand) || demand < 0) return null;
    return { hour: Number(tr.dataset.hour), demand_mw: demand, reserve_mw: reserveFor(demand) };
  });
}

// Rebuild the chart from current form values; no chart library or separate
// state is used. If changing dimensions, update index.html's SVG viewBox too.
function drawChart() {
  const rows = getRows();
  chart.replaceChildren();
  if (rows.some((row) => row === null)) {
    svgElement("text", { x: 40, y: 150, class: "axis-label" }, "Enter valid demand and reserve values to see the chart.");
    return;
  }
  // These margins and the SVG viewBox in index.html set the plotting area.
  const width = 760, height = 300, left = 55, right = 20, top = 18, bottom = 36;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  // Size the Y axis to the largest demand + reserve value, rounded to 100 MW.
  const maximum = Math.max(1, ...rows.map((row) => row.demand_mw + row.reserve_mw));
  const yMaximum = Math.max(100, Math.ceil(maximum / 100) * 100);
  const x = (index) => left + index * plotWidth / Math.max(1, rows.length - 1);
  const y = (value) => top + plotHeight * (1 - value / yMaximum);

  // Grid labels use MW. Add a chart series below, and a legend item in
  // index.html, if a new hourly field should be visualized.
  for (let tick = 0; tick <= 4; tick++) {
    const value = yMaximum * tick / 4;
    svgElement("line", { x1: left, x2: width - right, y1: y(value), y2: y(value), class: "grid-line" });
    svgElement("text", { x: left - 8, y: y(value) + 4, "text-anchor": "end", class: "axis-label" }, Math.round(value));
  }
  rows.forEach((row, index) => {
    if (index % 3 === 0 || index === rows.length - 1) {
      svgElement("text", { x: x(index), y: height - 8, "text-anchor": "middle", class: "axis-label" }, row.hour);
    }
  });
  // Each series is an SVG path; add or remove series here and in the legend.
  const pathFor = (value) => rows.map((row, index) =>
    (index === 0 ? "M" : "L") + x(index) + " " + y(value(row))).join(" ");
  svgElement("path", { d: pathFor((row) => row.demand_mw), class: "demand-line" });
  svgElement("path", { d: pathFor((row) => row.demand_mw + row.reserve_mw), class: "reserve-line" });
}

// Show the slider-derived reserve and required capacity for one hour.
function updateRequired(tr, redraw = true) {
  const demandInput = tr.querySelector('[data-field="demand_mw"]');
  const demand = Number(demandInput.value);
  const valid = demandInput.value !== "" && Number.isInteger(demand) && demand >= 0;
  tr.querySelector(".reserve-mw").textContent = valid ? reserveFor(demand) : "—";
  tr.querySelector(".required-capacity").textContent = valid ? demand + reserveFor(demand) : "—";
  if (redraw) drawChart();
}

// The API returns CSV rows as strings; number inputs and getRows convert them.
// The table rows are created here, not in index.html. To add an editable hourly
// field, add its cell here, read it in getRows(), and validate it in server.py.
async function loadDemand() {
  const response = await fetch("api/demand");
  if (!response.ok) throw new Error("Could not load demand.csv");
  const rows = await response.json();
  // Initialize the one slider from the saved day's overall reserve ratio.
  // Saved hourly reserves may differ slightly after whole-MW rounding.
  const totalDemand = rows.reduce((sum, row) => sum + Number(row.demand_mw), 0);
  const totalReserve = rows.reduce((sum, row) => sum + Number(row.reserve_mw), 0);
  reserveSlider.value = totalDemand > 0
    ? Math.max(0, Math.min(100, Math.round(totalReserve / totalDemand * 100))) : 10;
  reserveOutput.value = `${reserveSlider.value}%`;
  hoursBody.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.dataset.hour = row.hour;
    const hour = document.createElement("td");
    hour.textContent = row.hour;
    tr.append(hour);
    const demandCell = document.createElement("td");
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "1";
    input.required = true;
    input.value = row.demand_mw;
    input.dataset.field = "demand_mw";
    input.setAttribute("aria-label", `Demand for hour ${row.hour} in MW`);
    input.addEventListener("input", () => updateRequired(tr));
    demandCell.append(input);
    tr.append(demandCell);
    const reserve = document.createElement("td");
    reserve.className = "reserve-mw";
    tr.append(reserve);
    const required = document.createElement("td");
    required.className = "required-capacity";
    tr.append(required);
    hoursBody.append(tr);
    updateRequired(tr, false);
  }
  drawChart();
}

// Apply the selected percentage to every hour in the table and chart at once.
// This changes only browser state until the user presses Save demand.csv.
reserveSlider.addEventListener("input", () => {
  reserveOutput.value = `${reserveSlider.value}%`;
  for (const tr of hoursBody.querySelectorAll("tr")) updateRequired(tr, false);
  drawChart();
  status.textContent = "Reserve values changed. Click Save demand.csv to keep them.";
});

// Save sends every hour to server.py, where the complete set is checked before
// replacing demand.csv. The schedule tab reads the saved CSV on its next run.
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const rows = getRows();
  if (rows.some((row) => row === null)) {
    status.textContent = "Enter nonnegative whole numbers for demand.";
    return;
  }
  // Add new hourly fields to getRows(), then validate/save them in server.py.
  status.textContent = "Saving…";
  try {
    const response = await fetch("api/demand", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rows),
    });
    if (!response.ok) throw new Error(await response.text());
    await loadDemand();
    status.textContent = "Saved to input_app/demand.csv.";
  } catch (error) {
    status.textContent = `Save failed: ${error.message}`;
  }
});

// Load saved values on page open; errors are shown in the status area instead of the console.
loadDemand().catch((error) => { status.textContent = error.message; });
