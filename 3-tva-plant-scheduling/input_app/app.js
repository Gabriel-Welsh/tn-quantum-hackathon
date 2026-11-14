const form = document.querySelector("#demand-form");
const hoursBody = document.querySelector("#hours");
const chart = document.querySelector("#demand-chart");
const status = document.querySelector("#demand-status");
const SVG_NS = "http://www.w3.org/2000/svg";

function svgElement(tag, attributes, text) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text !== undefined) element.textContent = text;
  chart.append(element);
  return element;
}

function getRows() {
  return [...hoursBody.querySelectorAll("tr")].map((tr) => {
    const demandInput = tr.querySelector('[data-field="demand_mw"]');
    const reserveInput = tr.querySelector('[data-field="reserve_mw"]');
    const demand = Number(demandInput.value);
    const reserve = Number(reserveInput.value);
    if (!demandInput.value || !reserveInput.value ||
        !Number.isInteger(demand) || !Number.isInteger(reserve) ||
        demand < 0 || reserve < 0) return null;
    return { hour: Number(tr.dataset.hour), demand_mw: demand, reserve_mw: reserve };
  });
}

function drawChart() {
  const rows = getRows();
  chart.replaceChildren();
  if (rows.some((row) => row === null)) {
    svgElement("text", { x: 40, y: 150, class: "axis-label" }, "Enter valid demand and reserve values to see the chart.");
    return;
  }
  const width = 760, height = 300, left = 55, right = 20, top = 18, bottom = 36;
  const plotWidth = width - left - right, plotHeight = height - top - bottom;
  const maximum = Math.max(1, ...rows.map((row) => row.demand_mw + row.reserve_mw));
  const yMaximum = Math.max(100, Math.ceil(maximum / 100) * 100);
  const x = (index) => left + index * plotWidth / Math.max(1, rows.length - 1);
  const y = (value) => top + plotHeight * (1 - value / yMaximum);

  // Add another chart series here if you add an hourly field to demand.csv.
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
  const pathFor = (value) => rows.map((row, index) =>
    (index === 0 ? "M" : "L") + x(index) + " " + y(value(row))).join(" ");
  svgElement("path", { d: pathFor((row) => row.demand_mw), class: "demand-line" });
  svgElement("path", { d: pathFor((row) => row.demand_mw + row.reserve_mw), class: "reserve-line" });
}

function updateRequired(tr) {
  const demand = Number(tr.querySelector('[data-field="demand_mw"]').value);
  const reserve = Number(tr.querySelector('[data-field="reserve_mw"]').value);
  tr.querySelector(".required-capacity").textContent =
    Number.isInteger(demand) && Number.isInteger(reserve) && demand >= 0 && reserve >= 0
      ? demand + reserve : "—";
  drawChart();
}

async function loadDemand() {
  const response = await fetch("api/demand");
  if (!response.ok) throw new Error("Could not load demand.csv");
  const rows = await response.json();
  hoursBody.replaceChildren();
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.dataset.hour = row.hour;
    const hour = document.createElement("td");
    hour.textContent = row.hour;
    tr.append(hour);
    for (const field of ["demand_mw", "reserve_mw"]) {
      const cell = document.createElement("td");
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.step = "1";
      input.required = true;
      input.value = row[field];
      input.dataset.field = field;
      input.setAttribute("aria-label", `${field === "demand_mw" ? "Demand" : "Reserve"} for hour ${row.hour} in MW`);
      input.addEventListener("input", () => updateRequired(tr));
      cell.append(input);
      tr.append(cell);
    }
    const required = document.createElement("td");
    required.className = "required-capacity";
    tr.append(required);
    hoursBody.append(tr);
    updateRequired(tr);
  }
  drawChart();
}

document.querySelector("#reserve-ten").addEventListener("click", () => {
  for (const tr of hoursBody.querySelectorAll("tr")) {
    const demand = Number(tr.querySelector('[data-field="demand_mw"]').value);
    tr.querySelector('[data-field="reserve_mw"]').value = Math.round(demand * 0.1);
    updateRequired(tr);
  }
  status.textContent = "Reserve values changed. Click Save demand.csv to keep them.";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const rows = getRows();
  if (rows.some((row) => row === null)) {
    status.textContent = "Enter nonnegative whole numbers for demand and reserve.";
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

loadDemand().catch((error) => { status.textContent = error.message; });
