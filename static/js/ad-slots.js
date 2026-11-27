"use strict";

(() => {
  const creatives = document.querySelectorAll("[data-ad-url]");
  if (!creatives.length) {
    return;
  }

  const start = () => {
    const observer = new ResizeObserver((entries) => {
      for (const { target, contentRect } of entries) {
        const minimumWidth = Number(target.dataset.adWidth);
        if (!contentRect.width || !contentRect.height || contentRect.width < minimumWidth) {
          continue;
        }

        // El slot reserva su tamaño antes de cargar y los ocultos no tienen dimensiones.
        observer.unobserve(target);
        const frame = document.createElement("iframe");
        frame.className = "ad-slot__frame";
        frame.title = "Publicidad";
        frame.referrerPolicy = "no-referrer";
        frame.sandbox.add("allow-scripts", "allow-popups");
        frame.loading = target.hasAttribute("data-ad-eager") ? "eager" : "lazy";
        frame.src = target.dataset.adUrl;
        target.append(frame);
      }
    });
    creatives.forEach((creative) => observer.observe(creative));
  };

  const ageGate = document.getElementById("age-gate");
  if (!ageGate) {
    start();
    return;
  }

  // El script común retira el diálogo solo después de aceptar la verificación.
  const gateObserver = new MutationObserver(() => {
    if (!ageGate.isConnected) {
      gateObserver.disconnect();
      start();
    }
  });
  gateObserver.observe(ageGate.parentNode, { childList: true });
})();
