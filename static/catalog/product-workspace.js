/* Shared checkout theme and small catalogue-only progressive enhancements. */
(function () {
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem("lashpro-checkout-theme") || localStorage.getItem("lashpro-theme");
    if (saved === "dark" || saved === "light") root.dataset.theme = saved;
  } catch (_) {}
  document.addEventListener("DOMContentLoaded", () => {
    const theme = document.getElementById("theme-toggle");
    const applyTheme = () => {
      const dark = root.dataset.theme === "dark";
      root.style.colorScheme = dark ? "dark" : "light";
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = getComputedStyle(root).getPropertyValue("--ui-canvas").trim();
      if (theme) {
        const label = dark ? "Switch to light theme" : "Switch to dark theme";
        theme.setAttribute("aria-label", label);
        theme.title = label;
        theme.setAttribute("aria-pressed", String(dark));
        theme.innerHTML = '<i data-lucide="' + (dark ? "sun" : "moon") + '" aria-hidden="true"></i><span class="sr-only">' + label + '</span>';
      }
      if (window.lucide) window.lucide.createIcons();
    };
    applyTheme();
    if (theme) theme.addEventListener("click", () => {
      root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("lashpro-checkout-theme", root.dataset.theme);
        localStorage.setItem("lashpro-theme", root.dataset.theme);
      } catch (_) {}
      applyTheme();
    });
    const menu = document.getElementById("product-menu-toggle");
    const nav = document.getElementById("product-nav");
    if (menu && nav) {
      const compact = matchMedia("(max-width: 860px)");
      const setMenu = open => {
        nav.hidden = !open;
        menu.setAttribute("aria-expanded", String(open));
      };
      const layout = () => {
        menu.hidden = !compact.matches;
        setMenu(!compact.matches);
      };
      layout();
      compact.addEventListener("change", layout);
      menu.addEventListener("click", () => setMenu(nav.hidden));
      document.addEventListener("keydown", event => {
        if (event.key === "Escape" && compact.matches && !nav.hidden) {
          setMenu(false);
          menu.focus();
        }
      });
    }
    const form = document.getElementById("product-actions");
    const selectAll = document.getElementById("product-select-all");
    const selection = document.getElementById("product-selection");
    if (form && selectAll && selection) {
      const boxes = Array.from(form.querySelectorAll('input[name="_selected_action"]'));
      const action = form.querySelector('select[name="action"]');
      const submit = form.querySelector('button[name="index"]');
      const update = () => {
        const count = boxes.filter(box => box.checked).length;
        selection.textContent = count + " selected";
        selectAll.checked = boxes.length > 0 && count === boxes.length;
        selectAll.indeterminate = count > 0 && count < boxes.length;
        if (submit && action) submit.disabled = count === 0 || !action.value;
      };
      selectAll.addEventListener("change", () => {
        boxes.forEach(box => { box.checked = selectAll.checked; });
        update();
      });
      boxes.forEach(box => box.addEventListener("change", update));
      if (action) action.addEventListener("change", update);
      update();
    }
  });
})();
