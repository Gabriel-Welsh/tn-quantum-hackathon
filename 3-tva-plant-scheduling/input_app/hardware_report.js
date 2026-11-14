// Archived medians from QUANTUM_WARM_START.md, Results. These are HiGHS-only
// measurements, not end-to-end hybrid timings or QPU results.
const LOCAL_BENCHMARKS = [
  { label: "5 plants", seconds: [0.202, 0.195], integral: [0.097, 0.086] },
  { label: "10 plants", seconds: [0.198, 0.187], integral: [0.121, 0.098] },
  { label: "20 plants", seconds: [0.607, 0.505], integral: [0.400, 0.260] },
  { label: "40 plants", seconds: [3.081, 3.021], integral: [1.468, 1.347] },
];

function drawLocalBenchmark(selector, field, max, tickLabel) {
  const svg = document.querySelector(selector);
  const ns = "http://www.w3.org/2000/svg";
  const left = 145;
  const width = 500;
  const baseline = 354;
  svg.setAttribute("viewBox", "0 0 760 390");
  function add(tag, attributes, value) {
    const node = document.createElementNS(ns, tag);
    for (const [name, text] of Object.entries(attributes)) node.setAttribute(name, text);
    if (value !== undefined) node.textContent = value;
    svg.append(node);
  }
  for (let tick = 0; tick <= 4; tick++) {
    const x = left + width * tick / 4;
    add("line", { x1: x, y1: 58, x2: x, y2: baseline, class: "report-chart-grid" });
    add("text", { x, y: 378, "text-anchor": "middle" }, tickLabel(max * tick / 4));
  }
  add("rect", { x: left, y: 13, width: 14, height: 14, class: "report-milp-key" });
  add("text", { x: left + 22, y: 26 }, "Cold HiGHS");
  add("rect", { x: left + 170, y: 13, width: 14, height: 14, class: "report-hybrid-key" });
  add("text", { x: left + 192, y: 26 }, "Warm-start HiGHS");
  LOCAL_BENCHMARKS.forEach((row, index) => {
    const y = 70 + index * 72;
    add("text", { x: left - 13, y: y + 23, "text-anchor": "end" }, row.label);
    row[field].forEach((value, mode) => {
      const barY = y + mode * 21;
      add("rect", { x: left, y: barY, width: width * value / max,
        height: 16, class: mode ? "report-hybrid-key" : "report-milp-key" });
      add("text", { x: left + width * value / max + 7, y: barY + 13,
        class: "report-chart-value" }, value.toFixed(3));
    });
  });
}

drawLocalBenchmark("#highs-time-chart", "seconds", 3.5, value => value.toFixed(1) + " s");
drawLocalBenchmark("#highs-integral-chart", "integral", 1.7, value => value.toFixed(1));

// R generates the two additional charts only from supplied, checked CSVs.
// The inline SVG templates in index.html stay visible when a chart is missing.
function loadReportChart(imageId, placeholderId, statusId, file, readyText, emptyText) {
  const image = document.querySelector(imageId);
  const placeholder = document.querySelector(placeholderId);
  const status = document.querySelector(statusId);
  image.addEventListener("load", () => {
    image.hidden = false;
    placeholder.hidden = true;
    status.textContent = readyText;
  });
  image.addEventListener("error", () => {
    image.hidden = true;
    placeholder.hidden = false;
    status.textContent = emptyText;
  });
  // A fresh URL avoids showing an old graph after R regenerates its SVG.
  image.src = `${file}?version=${Date.now()}`;
}

loadReportChart(
  "#speed-chart", "#speed-placeholder", "#speed-status", "runtime-comparison.svg",
  "Measured benchmark chart loaded. Check the case definitions and timing method below.",
  "No matched end-to-end benchmark results added yet.",
);
loadReportChart(
  "#hardware-report-histogram", "#qpu-placeholder", "#hardware-report-status", "hardware-histogram.svg",
  "Measured QPU histogram loaded. Verify the job and device IDs below.",
  "No QPU results added yet.",
);
