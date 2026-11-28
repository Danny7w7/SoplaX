"use strict";

// Atajo «/»: enfoca el buscador de la cabecera salvo que se esté escribiendo en otro campo.
const searchInput = document.getElementById("search-input");

if (searchInput) {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) {
      return;
    }
    const target = event.target;
    if (target instanceof HTMLElement &&
        (target.isContentEditable || target.closest("input, textarea, select, [role='textbox']"))) {
      return;
    }
    event.preventDefault();
    searchInput.focus();
    searchInput.select();
  });

  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !searchInput.value) {
      searchInput.blur();
    }
  });
}
