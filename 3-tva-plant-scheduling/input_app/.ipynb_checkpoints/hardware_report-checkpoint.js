// The R template writes this chart only when a QPU results CSV is available.
// Reload the page after rerunning hardware_report.R to request the latest SVG.
const reportStatus = document.querySelector("#hardware-report-status");
const reportFigure = document.querySelector("#hardware-report-figure");
const reportHistogram = document.querySelector("#hardware-report-histogram");

reportStatus.textContent = "No quantum hardware results have been loaded yet.";
// The SVG route returns 404 until the developer runs hardware_report.R.
// Keep the figure hidden in that expected empty state.
reportHistogram.addEventListener("load", () => {
  reportFigure.hidden = false;
  reportStatus.textContent = "QPU histogram generated from the supplied CSV.";
});
reportHistogram.addEventListener("error", () => {
  reportFigure.hidden = true;
  reportStatus.textContent = "No quantum hardware results have been loaded yet.";
});
// A new URL on each page load avoids displaying an older cached histogram
// after the R template is rerun with a newer verified job CSV.
reportHistogram.src = `hardware-histogram.svg?version=${Date.now()}`;
