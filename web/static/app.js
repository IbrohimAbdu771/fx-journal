// Clickable table rows + AJAX calendar month navigation.
(function () {
  function go(el) {
    var href = el.getAttribute("data-href");
    if (href) window.location.assign(href);
  }

  async function swapCalendar(nav) {
    var card = document.getElementById("calendar-card");
    if (!card) return;
    var q = "/calendar?y=" + nav.dataset.y + "&m=" + nav.dataset.m +
            "&period=" + (nav.dataset.period || "all");
    card.classList.add("loading");
    try {
      var res = await fetch(q, { headers: { "X-Requested-With": "fetch" } });
      if (res.ok) card.innerHTML = await res.text();
    } catch (e) {
      window.location.assign(nav.getAttribute("href")); // graceful fallback
    } finally {
      card.classList.remove("loading");
    }
  }

  document.addEventListener("click", function (e) {
    var nav = e.target.closest(".cal-nav");
    if (nav) {
      e.preventDefault();
      swapCalendar(nav);
      return;
    }
    var row = e.target.closest("[data-href]");
    if (!row) return;
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
