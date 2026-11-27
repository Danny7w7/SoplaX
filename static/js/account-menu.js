const accountMenu = document.querySelector("[data-account-menu]");

if (accountMenu) {
  const summary = accountMenu.querySelector("summary");
  const actions = [...accountMenu.querySelectorAll(".account-menu__items :is(a, button)")];

  document.addEventListener("click", (event) => {
    if (accountMenu.open && !accountMenu.contains(event.target)) {
      accountMenu.open = false;
    }
  });

  accountMenu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && accountMenu.open) {
      event.preventDefault();
      accountMenu.open = false;
      summary.focus();
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      accountMenu.open = true;
      const current = actions.indexOf(document.activeElement);
      const next = event.key === "ArrowDown"
        ? Math.min(current + 1, actions.length - 1)
        : current < 0 ? actions.length - 1 : Math.max(current - 1, 0);
      actions[next].focus();
    }
  });

  accountMenu.addEventListener("focusout", (event) => {
    if (event.relatedTarget && !accountMenu.contains(event.relatedTarget)) {
      accountMenu.open = false;
    }
  });
}
