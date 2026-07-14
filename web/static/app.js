// Clickable table rows (whole row opens the trade). Keyboard-accessible.
(function () {
  function go(el) {
    var href = el.getAttribute("data-href");
    if (href) window.location.assign(href);
  }
  document.addEventListener("click", function (e) {
    var row = e.target.closest("[data-href]");
    if (!row) return;
    // don't hijack clicks on real interactive children
    if (e.target.closest("a,button,input,select,textarea,label,form")) return;
    go(row);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter") return;
    var row = e.target.closest("[data-href]");
    if (row && row.getAttribute("tabindex") !== null) {
      e.preventDefault();
      go(row);
    }
  });
})();
