/* Progressive enhancement; links and native POST forms work without this script. */
document.addEventListener("DOMContentLoaded", () => {
  const filters = [...document.querySelectorAll(".register-filter")];
  filters.forEach(filter => {
    filter.addEventListener("toggle", () => {
      if (filter.open) filters.forEach(other => { if (other !== filter) other.open = false; });
    });
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    filters.filter(filter => filter.open).forEach(filter => {
      filter.open = false;
      filter.querySelector("summary").focus();
    });
  });
});
