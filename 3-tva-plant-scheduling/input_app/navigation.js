// Switch views with a URL fragment. qBraid Canvas keeps the same preview frame,
// so clicking a tab does not request a new top-level page from Lab.
// Unknown or empty fragments open Power plants so the starter fleet is visible on launch.
function showPage() {
  const active = location.hash === "#demand" ? "demand" : "plants";
  // Keep both sections in the DOM so edits survive tab switches until Save or reload.
  document.querySelector("#plants-page").hidden = active !== "plants";
  document.querySelector("#demand-page").hidden = active !== "demand";
  // aria-current marks the selected tab for assistive technology and CSS.
  for (const link of document.querySelectorAll("[data-page-link]")) {
    if (link.dataset.pageLink === active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener("hashchange", showPage);
showPage();
