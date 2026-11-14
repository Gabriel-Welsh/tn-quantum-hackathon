// Switch views with a URL fragment. qBraid Canvas keeps the same preview frame,
// so clicking a tab does not request a new top-level page from Lab.
function showPage() {
  const active = location.hash === "#plants" ? "plants" : "demand";
  document.querySelector("#plants-page").hidden = active !== "plants";
  document.querySelector("#demand-page").hidden = active !== "demand";
  for (const link of document.querySelectorAll("[data-page-link]")) {
    if (link.dataset.pageLink === active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener("hashchange", showPage);
showPage();
