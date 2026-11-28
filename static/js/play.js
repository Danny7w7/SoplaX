"use strict";

function formatVideoTime(seconds) {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(total / 60);
  const remainder = String(total % 60).padStart(2, "0");
  if (minutes < 60) {
    return `${minutes}:${remainder}`;
  }
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${remainder}`;
}

// Vista previa de la barra: un segundo <video> pausado y silenciado reutiliza la URL firmada.
// No hace lecturas hasta 120 ms de interacción sostenida y limita las búsquedas a una cada 250 ms,
// con una en curso y solo el destino más reciente pendiente.
function createTimelinePreview(video, preview) {
  const previewVideo = preview.querySelector("video");
  const timestamp = preview.querySelector("[data-preview-time]");
  const activationDelay = 120;
  const seekInterval = 250;
  let openedAt;
  let lastSeekAt = -Infinity;
  let timer;
  let targetTime = null;
  let lastRequestedTime = -Infinity;

  function showFrame() {
    if (targetTime !== null && previewVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      preview.classList.add("has-frame");
    }
  }

  function updateFrame() {
    timer = undefined;
    if (targetTime === null || previewVideo.error || previewVideo.seeking) {
      return;
    }
    if (!previewVideo.hasAttribute("src")) {
      if (video.currentSrc) {
        previewVideo.preload = "metadata";
        previewVideo.src = video.currentSrc;
      } else {
        preview.classList.add("is-time-only");
      }
      return;
    }
    if (!Number.isFinite(previewVideo.duration)) {
      return;
    }

    const destination = Math.min(targetTime, Math.max(0, previewVideo.duration - 0.05));
    const alreadyRequested = Math.abs(lastRequestedTime - destination) < 0.1;
    const alreadyAvailable = Math.abs(previewVideo.currentTime - destination) < 0.1 &&
      previewVideo.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA;
    if (alreadyRequested || alreadyAvailable) {
      showFrame();
      return;
    }
    lastRequestedTime = destination;
    lastSeekAt = performance.now();
    previewVideo.currentTime = destination;
  }

  function scheduleFrame() {
    if (targetTime === null || timer !== undefined || previewVideo.error || previewVideo.seeking ||
        (previewVideo.hasAttribute("src") && previewVideo.readyState < HTMLMediaElement.HAVE_METADATA)) {
      return;
    }
    const delay = Math.max(openedAt + activationDelay, lastSeekAt + seekInterval) - performance.now();
    timer = window.setTimeout(updateFrame, Math.max(0, Math.ceil(delay)));
  }

  previewVideo.addEventListener("loadedmetadata", scheduleFrame);
  previewVideo.addEventListener("loadeddata", scheduleFrame);
  previewVideo.addEventListener("seeked", () => {
    if (lastSeekAt >= openedAt) {
      showFrame();
    }
    scheduleFrame();
  });
  // Si el fotograma falla, el tiempo y la búsqueda siguen disponibles.
  previewVideo.addEventListener("error", () => {
    preview.classList.remove("has-frame");
    preview.classList.add("is-time-only");
  });

  return {
    show(time, fraction) {
      if (targetTime === null) {
        openedAt = performance.now();
      }
      targetTime = time;
      timestamp.textContent = formatVideoTime(time);
      preview.style.setProperty("--preview-position", `${fraction * 100}%`);
      preview.hidden = false;
      scheduleFrame();
    },
    hide() {
      window.clearTimeout(timer);
      timer = undefined;
      targetTime = null;
      preview.hidden = true;
      preview.classList.remove("has-frame");
    },
  };
}

function setPlayerLabel(button, label) {
  button.setAttribute("aria-label", label);
  button.title = label;
}

function initializePlayer(video, player, controls) {
  const seek = controls.querySelector(".player__seek");
  const preview = createTimelinePreview(video, controls.querySelector(".player__preview"));
  const play = controls.querySelector("[data-player-play]");
  const currentLabel = controls.querySelector("[data-player-current]");
  const durationLabel = controls.querySelector("[data-player-duration]");
  const mute = controls.querySelector("[data-player-mute]");
  const volume = controls.querySelector(".player__volume");
  const rate = controls.querySelector(".player__rate");
  const pictureInPicture = controls.querySelector("[data-player-pip]");
  const fullscreen = controls.querySelector("[data-player-fullscreen]");
  const isIPhone = /\biPhone\b|\biPod\b/.test(navigator.userAgent);
  const useContainerFullscreen = !isIPhone && document.fullscreenEnabled &&
    typeof player.requestFullscreen === "function";
  const useNativeFullscreen = typeof video.webkitEnterFullscreen === "function";
  const idleDelay = 2500;
  let dragPointer = null;
  let idleTimer;
  let lastPointerType = "mouse";

  // Visibilidad de los controles: se ocultan durante la reproducción tras un tiempo sin actividad.
  function canHideControls() {
    return !video.paused && !video.ended && dragPointer === null && document.activeElement !== rate &&
      !(lastPointerType === "mouse" && controls.matches(":hover"));
  }

  function hideControls() {
    window.clearTimeout(idleTimer);
    if (canHideControls()) {
      player.dataset.controls = "hidden";
    }
  }

  function showControls() {
    player.dataset.controls = "shown";
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(hideControls, idleDelay);
  }

  player.addEventListener("pointerdown", (event) => {
    lastPointerType = event.pointerType;
  }, { capture: true });
  player.addEventListener("pointermove", (event) => {
    lastPointerType = event.pointerType;
    if (event.pointerType === "mouse") {
      showControls();
    }
  });
  player.addEventListener("pointerleave", (event) => {
    if (event.pointerType === "mouse") {
      hideControls();
    }
  });
  controls.addEventListener("pointerup", showControls);
  controls.addEventListener("focusin", showControls);
  controls.addEventListener("keydown", showControls);

  function updateSeek(time) {
    const fraction = seek.disabled ? 0 : time / video.duration;
    seek.value = fraction * Number(seek.max);
    seek.style.setProperty("--seek-progress", `${fraction * 100}%`);
    seek.setAttribute("aria-valuetext", `${formatVideoTime(time)} de ${formatVideoTime(video.duration)}`);
  }

  function updateBuffered() {
    let end = 0;
    for (let index = 0; index < video.buffered.length; index += 1) {
      if (video.buffered.start(index) <= video.currentTime + 0.5) {
        end = Math.max(end, video.buffered.end(index));
      }
    }
    const fraction = seek.disabled ? 0 : Math.min(1, end / video.duration);
    seek.style.setProperty("--seek-buffered", `${fraction * 100}%`);
  }

  function updateTime() {
    seek.disabled = !Number.isFinite(video.duration) || video.duration <= 0;
    fullscreen.disabled = !useContainerFullscreen && video.readyState < HTMLMediaElement.HAVE_METADATA;
    pictureInPicture.disabled = video.readyState < HTMLMediaElement.HAVE_METADATA;
    currentLabel.textContent = formatVideoTime(video.currentTime);
    durationLabel.textContent = formatVideoTime(video.duration);
    if (dragPointer === null) {
      updateSeek(video.currentTime);
    }
    updateBuffered();
  }

  function pointerFraction(event) {
    const { left, width } = seek.getBoundingClientRect();
    return width > 0 ? Math.min(1, Math.max(0, (event.clientX - left) / width)) : 0;
  }

  function showPosition(event) {
    if (seek.disabled || (dragPointer !== null && dragPointer !== event.pointerId)) {
      return;
    }
    if (dragPointer === null && (event.pointerType === "touch" || event.buttons !== 0)) {
      return;
    }
    const fraction = pointerFraction(event);
    const time = fraction * video.duration;
    preview.show(time, fraction);
    if (dragPointer !== null) {
      updateSeek(time);
    }
  }

  // El salto ocurre una sola vez al soltar; si el gesto se cancela, la reproducción sigue donde estaba.
  function endDrag(event) {
    if (event.pointerId !== dragPointer) {
      return;
    }
    dragPointer = null;
    delete player.dataset.scrubbing;
    const commit = event.type === "pointerup" && !seek.disabled;
    if (commit) {
      video.currentTime = pointerFraction(event) * video.duration;
    }
    updateTime();
    showControls();

    const bounds = seek.getBoundingClientRect();
    if (commit && event.pointerType === "mouse" && event.clientX >= bounds.left && event.clientX <= bounds.right &&
        event.clientY >= bounds.top && event.clientY <= bounds.bottom) {
      showPosition(event);
    } else {
      preview.hide();
    }
  }

  seek.addEventListener("pointerdown", (event) => {
    if (seek.disabled || dragPointer !== null || !event.isPrimary || event.button !== 0) {
      return;
    }
    event.preventDefault();
    dragPointer = event.pointerId;
    player.dataset.scrubbing = "";
    seek.setPointerCapture(event.pointerId);
    if (event.pointerType !== "touch") {
      seek.focus({ preventScroll: true });
    }
    showControls();
    showPosition(event);
  });
  seek.addEventListener("pointerenter", showPosition);
  seek.addEventListener("pointermove", showPosition);
  seek.addEventListener("pointerleave", () => {
    if (dragPointer === null) {
      preview.hide();
    }
  });
  seek.addEventListener("pointerup", endDrag);
  seek.addEventListener("pointercancel", endDrag);
  seek.addEventListener("lostpointercapture", endDrag);
  seek.addEventListener("input", () => {
    if (dragPointer === null && !seek.disabled) {
      preview.hide();
      video.currentTime = seek.valueAsNumber / Number(seek.max) * video.duration;
      updateTime();
    }
  });
  seek.addEventListener("keydown", (event) => {
    if (dragPointer !== null || seek.disabled) {
      return;
    }
    const backwards = event.key === "ArrowLeft" || event.key === "ArrowDown";
    const forwards = event.key === "ArrowRight" || event.key === "ArrowUp";
    if (backwards || forwards) {
      event.preventDefault();
      preview.hide();
      const time = video.currentTime + (backwards ? -5 : 5);
      video.currentTime = Math.min(video.duration, Math.max(0, time));
      updateTime();
    }
  });
  video.addEventListener("loadedmetadata", updateTime);
  video.addEventListener("durationchange", updateTime);
  video.addEventListener("timeupdate", updateTime);
  video.addEventListener("progress", updateBuffered);

  function restoreNativeControls() {
    preview.hide();
    window.clearTimeout(idleTimer);
    delete player.dataset.enhanced;
    player.dataset.controls = "shown";
    controls.hidden = true;
    video.controls = true;
  }

  function updatePlayButton() {
    const playing = !video.paused && !video.ended;
    play.querySelector('[data-icon="play"]').hidden = playing;
    play.querySelector('[data-icon="pause"]').hidden = !playing;
    player.dataset.state = playing ? "playing" : "paused";
    setPlayerLabel(play, playing ? "Pausar" : "Reproducir");
    showControls();
  }

  function togglePlayback() {
    if (video.paused || video.ended) {
      video.play().catch((error) => {
        if (error.name !== "AbortError" && error.name !== "NotAllowedError") {
          restoreNativeControls();
        }
      });
    } else {
      video.pause();
    }
  }

  play.addEventListener("click", togglePlayback);
  // Con el dedo, el primer toque muestra los controles ocultos; el siguiente alterna la reproducción.
  video.addEventListener("click", (event) => {
    if (video.controls) {
      return;
    }
    const pointerType = event.pointerType || lastPointerType;
    if (pointerType !== "mouse" && player.dataset.controls === "hidden") {
      showControls();
      return;
    }
    togglePlayback();
  });
  for (const event of ["play", "pause", "ended"]) {
    video.addEventListener(event, updatePlayButton);
  }
  video.addEventListener("error", restoreNativeControls);
  video.querySelector("source")?.addEventListener("error", restoreNativeControls);

  function updateVolume() {
    const muted = video.muted || video.volume === 0;
    volume.value = video.muted ? 0 : video.volume;
    volume.style.setProperty("--volume-level", `${volume.valueAsNumber * 100}%`);
    mute.dataset.muted = String(muted);
    setPlayerLabel(mute, muted ? "Activar sonido" : "Silenciar");
  }

  mute.addEventListener("click", () => {
    const muted = video.muted || video.volume === 0;
    if (muted && video.volume === 0) {
      video.volume = 1;
    }
    video.muted = !muted;
  });
  volume.hidden = isIPhone || (CSS.supports("selector(video:volume-locked)") && video.matches(":volume-locked"));
  volume.addEventListener("input", () => {
    video.volume = volume.valueAsNumber;
    video.muted = false;
  });
  video.addEventListener("volumechange", updateVolume);
  rate.addEventListener("change", () => { video.playbackRate = Number(rate.value); });
  video.addEventListener("ratechange", () => { rate.value = String(video.playbackRate); });

  if (document.pictureInPictureEnabled && typeof video.requestPictureInPicture === "function") {
    pictureInPicture.hidden = false;
    pictureInPicture.addEventListener("click", async () => {
      try {
        if (document.pictureInPictureElement === video) {
          await document.exitPictureInPicture();
        } else {
          await video.requestPictureInPicture();
        }
      } catch {
        // El navegador puede rechazar este modo durante la carga o en pantalla completa.
      }
    });
  }

  fullscreen.hidden = !useContainerFullscreen && !useNativeFullscreen;
  fullscreen.addEventListener("click", async () => {
    preview.hide();
    try {
      if (document.fullscreenElement === player) {
        await document.exitFullscreen();
      } else if (useContainerFullscreen) {
        await player.requestFullscreen();
      } else if (useNativeFullscreen && video.readyState >= HTMLMediaElement.HAVE_METADATA) {
        video.controls = true;
        video.webkitEnterFullscreen();
      }
    } catch {
      video.controls = false;
    }
  });
  document.addEventListener("fullscreenchange", () => {
    const active = document.fullscreenElement === player;
    preview.hide();
    fullscreen.dataset.active = String(active);
    setPlayerLabel(fullscreen, active ? "Salir de pantalla completa" : "Pantalla completa");
    showControls();
  });
  // iPhone: pantalla completa nativa de iOS; la miniatura queda disponible en la vista normal.
  video.addEventListener("webkitbeginfullscreen", () => {
    preview.hide();
    controls.hidden = true;
  });
  video.addEventListener("webkitendfullscreen", () => {
    if (!video.error) {
      video.controls = false;
      controls.hidden = false;
      showControls();
      fullscreen.focus({ preventScroll: true });
    }
  });
  window.addEventListener("pagehide", preview.hide);

  player.dataset.enhanced = "";
  updatePlayButton();
  updateVolume();
  updateTime();
  video.controls = false;
  controls.hidden = false;
}

const video = document.getElementById("my-video");
video?.addEventListener("contextmenu", (event) => event.preventDefault());
const player = video?.closest(".player");
const playerControls = player?.querySelector(".player__controls");
if (playerControls && "PointerEvent" in window && !video.error) {
  try {
    initializePlayer(video, player, playerControls);
  } catch (error) {
    // Si la inicialización falla, el navegador conserva sus controles nativos.
    playerControls.hidden = true;
    video.controls = true;
    console.error(error);
  }
}

// Descripción: se recorta a cuatro líneas y se expande bajo demanda.
const description = document.querySelector("[data-clamp]");
const descriptionToggle = document.querySelector("[data-clamp-toggle]");
if (description && descriptionToggle) {
  description.classList.add("is-clamped");

  const updateToggle = () => {
    if (description.classList.contains("is-clamped")) {
      descriptionToggle.hidden = description.scrollHeight <= description.clientHeight + 1;
    }
  };

  updateToggle();
  window.addEventListener("resize", updateToggle, { passive: true });
  document.fonts?.ready.then(updateToggle);

  descriptionToggle.addEventListener("click", () => {
    const expanded = !description.classList.toggle("is-clamped");
    descriptionToggle.setAttribute("aria-expanded", String(expanded));
    descriptionToggle.textContent = expanded ? "Mostrar menos" : "Mostrar más";
    updateToggle();
  });
}
