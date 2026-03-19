document.addEventListener("DOMContentLoaded", () => {
  const loadingEl = document.getElementById("rw-loading");

  const showLoading = () => {
    if (!loadingEl) return;
    loadingEl.classList.remove("hidden");
  };

  const hideLoading = () => {
    if (!loadingEl) return;
    loadingEl.classList.add("hidden");
  };

  // Planner UX: show an overlay as the user submits the form.
  const plannerForm = document.getElementById("plannerForm");
  if (plannerForm) {
    plannerForm.addEventListener("submit", () => {
      // Let the navigation happen; the overlay avoids a jarring transition.
      showLoading();
    });
    // Hide after the page fully loads.
    window.addEventListener("load", hideLoading);
  }

  // Hubs UX: lightweight placeholder behavior for hub search UI.
  const hubSearch = document.getElementById("hubSearch");
  const hubType = document.getElementById("hubType");
  if (!hubSearch || !hubType) return;

  const cards = Array.from(document.querySelectorAll(".hub-card"));
  const emptyEl = document.getElementById("hubEmpty");

  const filter = () => {
    const q = hubSearch.value.trim().toLowerCase();
    const type = hubType.value;

    let visibleCount = 0;
    for (const card of cards) {
      const name = (card.dataset.hubName || "").toLowerCase();
      const hubTypeValue = (card.dataset.hubType || "").toLowerCase();
      const haystack = `${name} ${card.textContent || ""}`.toLowerCase();

      const matchesQuery = q === "" || haystack.includes(q);
      const matchesType = type === "all" || hubTypeValue === type;
      const matches = matchesQuery && matchesType;

      card.classList.toggle("hidden", !matches);
      if (matches) visibleCount += 1;
    }

    if (emptyEl) emptyEl.classList.toggle("hidden", visibleCount !== 0);
  };

  hubSearch.addEventListener("input", filter);
  hubType.addEventListener("change", filter);
  filter();
});

