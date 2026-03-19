document.addEventListener("DOMContentLoaded", () => {
  // Phase 1: lightweight placeholder behavior for hub search UI.
  const hubSearch = document.getElementById("hubSearch");
  if (!hubSearch) return;

  const cards = Array.from(document.querySelectorAll(".hub-card"));

  const filter = () => {
    const q = hubSearch.value.trim().toLowerCase();
    for (const card of cards) {
      const name = (card.dataset.hubName || "").toLowerCase();
      const haystack = `${name} ${card.textContent || ""}`.toLowerCase();
      const matches = q === "" || haystack.includes(q);
      card.classList.toggle("hidden", !matches);
    }
  };

  hubSearch.addEventListener("input", filter);
  filter();
});

