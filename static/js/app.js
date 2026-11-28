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

// Miniaturas: al dejar el cursor un segundo encima, reproduce en bucle la vista previa sin sonido.
// Solo con ratón; no se activa en pantallas táctiles, con «Reducir movimiento» ni con ahorro de datos.
{
  const PREVIEW_DELAY_MS = 1000;
  const finePointer = window.matchMedia("(hover: hover) and (pointer: fine)");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let active = null;

  const previewAllowed = (event) =>
    event.pointerType === "mouse" && finePointer.matches && !reducedMotion.matches &&
    !navigator.connection?.saveData;

  const stopPreview = () => {
    if (!active) {
      return;
    }
    const { host, timer, video, progress } = active;
    active = null;
    window.clearTimeout(timer);
    host.classList.remove("is-previewing");
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.load();
      video.remove();
    }
    progress?.remove();
  };

  const startPreview = (preview) => {
    const { host } = preview;
    const video = document.createElement("video");
    const progress = document.createElement("span");
    video.className = "thumb-preview";
    video.muted = true;
    video.defaultMuted = true;
    video.loop = true;
    video.playsInline = true;
    video.preload = "auto";
    video.disablePictureInPicture = true;
    video.setAttribute("aria-hidden", "true");
    video.tabIndex = -1;
    progress.className = "thumb-preview__progress";
    progress.setAttribute("aria-hidden", "true");

    const isCurrent = () => active === preview;
    const trackProgress = () => {
      if (!isCurrent()) {
        return;
      }
      if (video.duration > 0) {
        progress.style.setProperty("--preview-progress", String(video.currentTime / video.duration));
      }
      window.requestAnimationFrame(trackProgress);
    };
    video.addEventListener("playing", () => {
      if (isCurrent()) {
        host.classList.add("is-previewing");
        window.requestAnimationFrame(trackProgress);
      }
    }, { once: true });
    video.addEventListener("error", () => isCurrent() && stopPreview(), { once: true });

    preview.video = video;
    preview.progress = progress;
    video.src = host.dataset.previewSrc;
    host.append(video, progress);
    video.play().catch(() => isCurrent() && stopPreview());
  };

  document.addEventListener("pointerover", (event) => {
    const host = event.target.closest?.("[data-preview-src]");
    if (!host || host === active?.host || !previewAllowed(event)) {
      return;
    }
    stopPreview();
    const preview = { host };
    preview.timer = window.setTimeout(() => active === preview && startPreview(preview), PREVIEW_DELAY_MS);
    active = preview;
  });

  document.addEventListener("pointerout", (event) => {
    if (active && !active.host.contains(event.relatedTarget)) {
      stopPreview();
    }
  });

  document.addEventListener("visibilitychange", () => document.hidden && stopPreview());
  window.addEventListener("pagehide", stopPreview);
}

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
