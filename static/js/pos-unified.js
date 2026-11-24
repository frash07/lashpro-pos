(() => {
  const root = document.documentElement;
  const storageKeys = ["lashpro-theme", "lashpro-checkout-theme"];

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    root.dataset.theme = next;
    root.style.colorScheme = next;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      const token = getComputedStyle(root).getPropertyValue("--ui-canvas").trim();
      meta.setAttribute("content", token || (next === "dark" ? "#121114" : "#F8F3EE"));
    }
    document.querySelectorAll(".pos-theme-toggle").forEach(button => {
      button.setAttribute("aria-label", next === "dark" ? "Switch to light theme" : "Switch to dark theme");
      button.setAttribute("title", next === "dark" ? "Switch to light theme" : "Switch to dark theme");
      button.setAttribute("aria-pressed", String(next === "dark"));
      button.innerHTML = '<i data-lucide="' + (next === "dark" ? "sun" : "moon") + '" aria-hidden="true"></i>';
    });
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
    storageKeys.forEach(key => {
      try { localStorage.setItem(key, next); } catch (_) { /* Storage can be unavailable in private mode. */ }
    });
  }

  function restoreTheme() {
    let saved = "";
    for (const key of storageKeys) {
      try {
        const value = localStorage.getItem(key);
        if (value === "dark" || value === "light") { saved = value; break; }
      } catch (_) { break; }
    }
    applyTheme(saved || (root.dataset.theme === "dark" ? "dark" : "light"));
  }

  document.addEventListener("click", event => {
    const button = event.target.closest(".pos-theme-toggle");
    if (!button) return;
    applyTheme(root.dataset.theme === "dark" ? "light" : "dark");
  });

  document.addEventListener("DOMContentLoaded", () => {
    restoreTheme();
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }
  });
})();
