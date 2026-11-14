// R generates charts only after a developer supplies and checks measured CSVs.
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
  "No benchmark results added yet.",
);
loadReportChart(
  "#hardware-report-histogram", "#qpu-placeholder", "#hardware-report-status", "hardware-histogram.svg",
  "Measured QPU histogram loaded. Verify the job and device IDs below.",
  "No QPU results added yet.",
);
