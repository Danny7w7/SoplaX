"use strict";

(() => {
  const creatives = document.querySelectorAll("[data-ad-url]");
  if (!creatives.length || !("IntersectionObserver" in window)) {
    return;
  }

  const start = () => {
    const observer = new IntersectionObserver((entries) => {
      for (const { target, isIntersecting } of entries) {
        if (!isIntersecting || target.querySelector(".ad-slot__frame")) {
          continue;
        }

        const { width, height } = target.getBoundingClientRect();
        const { adWidth, adHeight, adUrl } = target.dataset;
        if (width < Number(adWidth) || height < Number(adHeight)) {
          continue;
        }

        observer.unobserve(target);
        const frame = document.createElement("iframe");
        frame.className = "ad-slot__frame";
        frame.title = "Publicidad";
        frame.width = adWidth;
        frame.height = adHeight;
        frame.referrerPolicy = "no-referrer";
        frame.sandbox.add("allow-scripts", "allow-popups");
        frame.src = adUrl;
        target.append(frame);
      }
    }, { rootMargin: "200px 0px" });
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
