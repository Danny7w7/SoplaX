"use strict";

// Comportamientos comunes de SoplaX. Mejora progresiva: todo funciona sin JavaScript.

// Verificación de edad: convierte el diálogo en modal y recuerda la aceptación durante un año.
const ageGate = document.getElementById("age-gate");
if (ageGate && typeof ageGate.showModal === "function") {
  ageGate.removeAttribute("open");
  ageGate.showModal();
  ageGate.addEventListener("cancel", (event) => event.preventDefault());
  ageGate.addEventListener("close", () => {
    if (ageGate.returnValue !== "accept") {
      ageGate.showModal();
      return;
    }
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `soplax_age_ok=1; Max-Age=31536000; Path=/; SameSite=Lax${secure}`;
    ageGate.remove();
  });
}

// Cabecera: muestra el borde inferior al desplazarse.
const siteHeader = document.querySelector("[data-site-header]");
if (siteHeader) {
  const updateHeader = () => siteHeader.classList.toggle("is-scrolled", window.scrollY > 4);
  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });
}

// Menú de cuenta (Popover API): se alinea bajo su botón al abrirse.
const accountMenu = document.getElementById("account-menu");
const accountTrigger = document.querySelector('[popovertarget="account-menu"]');
if (accountMenu && accountTrigger && typeof accountMenu.showPopover === "function") {
  const placeMenu = () => {
    const rect = accountTrigger.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth;
    accountMenu.style.top = `${rect.bottom + 8}px`;
    accountMenu.style.right = `${Math.max(viewportWidth - rect.right, 8)}px`;
  };
  accountMenu.addEventListener("beforetoggle", (event) => {
    if (event.newState === "open") {
      placeMenu();
    }
  });
  window.addEventListener("resize", () => {
    if (accountMenu.matches(":popover-open")) {
      placeMenu();
    }
  });

  const actions = [...accountMenu.querySelectorAll(".menu__item")];
  const navigateMenu = (event) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
      return;
    }
    event.preventDefault();
    if (!accountMenu.matches(":popover-open")) {
      accountTrigger.click();
    }
    const current = actions.indexOf(document.activeElement);
    let next = current + 1;
    if (event.key === "ArrowUp") {
      next = current === -1 ? actions.length - 1 : current - 1;
    }
    actions[Math.max(0, Math.min(next, actions.length - 1))]?.focus();
  };
  accountTrigger.addEventListener("keydown", navigateMenu);
  accountMenu.addEventListener("keydown", navigateMenu);
}

// Miniaturas: detiene el skeleton cuando la imagen termina de cargar.
document.querySelectorAll("[data-skeleton] img").forEach((image) => {
  const markLoaded = () => image.closest("[data-skeleton]").classList.add("is-loaded");
  if (image.complete) {
    markLoaded();
  } else {
    image.addEventListener("load", markLoaded, { once: true });
    image.addEventListener("error", markLoaded, { once: true });
  }
});

// Formularios: indicador de carga en el botón de envío.
document.querySelectorAll("form[data-loading]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    const button = event.submitter || form.querySelector('[type="submit"]');
    if (!button || button.getAttribute("aria-busy") === "true") {
      return;
    }
    const loader = document.createElement("span");
    loader.className = "x-loader";
    loader.setAttribute("aria-hidden", "true");
    button.prepend(loader);
    button.setAttribute("aria-busy", "true");
  });
});

// Al volver con el botón Atrás, la página puede restaurarse con el botón aún ocupado.
window.addEventListener("pageshow", (event) => {
  if (!event.persisted) {
    return;
  }
  document.querySelectorAll('[aria-busy="true"]').forEach((button) => {
    button.removeAttribute("aria-busy");
    button.querySelector(".x-loader")?.remove();
  });
});

// Contraseñas: botón para mostrar u ocultar el texto.
document.querySelectorAll('.field__control input[type="password"]').forEach((input) => {
  const control = input.parentElement;
  const toggle = document.createElement("button");
  const label = document.createElement("span");
  const context = document.createElement("span");

  toggle.type = "button";
  toggle.className = "field__toggle";
  toggle.setAttribute("aria-controls", input.id);
  label.textContent = "Mostrar";
  context.className = "visually-hidden";
  context.textContent = " contraseña";
  toggle.append(label, context);

  toggle.addEventListener("click", () => {
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    label.textContent = reveal ? "Ocultar" : "Mostrar";
  });

  control.classList.add("field__control--password");
  control.append(toggle);
});

// Notificaciones: botón de cierre.
document.querySelectorAll("[data-dismiss-toast]").forEach((button) => {
  button.addEventListener("click", () => button.closest(".toast")?.remove());
});
