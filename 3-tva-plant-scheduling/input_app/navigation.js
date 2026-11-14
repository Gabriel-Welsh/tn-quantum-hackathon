// Page router for the four sections in index.html. Nav links set #plants,
// #demand, #schedule, or #hardware-report; no page reload is needed, so unsaved form edits survive
// tab switches. Add a link, section ID, and value in the list below together.
// Unknown or empty fragments open Power plants so the starter fleet is visible.
function showPage() {
  const requested = location.hash.slice(1);
  const active = ["plants", "demand", "schedule", "hardware-report"].includes(requested) ? requested : "plants";
  // Keep all sections mounted and toggle only visibility; their JS modules can
  // still read and update their own controls while another section is shown.
  document.querySelector("#plants-page").hidden = active !== "plants";
  document.querySelector("#demand-page").hidden = active !== "demand";
  document.querySelector("#schedule-page").hidden = active !== "schedule";
  document.querySelector("#hardware-report-page").hidden = active !== "hardware-report";
  // aria-current marks the selected tab for assistive technology and the
  // highlighted nav style in styles.css. data-page-link must match the hash.
  for (const link of document.querySelectorAll("[data-page-link]")) {
    if (link.dataset.pageLink === active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener("hashchange", showPage); // Respond to tab clicks and browser back/forward.
showPage(); // Apply the initial URL when the page first loads.
