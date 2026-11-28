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
  previewVideo.addEventListener("error", () => preview.classList.remove("has-frame"));

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
  const timeLabel = controls.querySelector("[data-player-time]");
  const mute = controls.querySelector("[data-player-mute]");
  const volume = controls.querySelector(".player__volume");
  const rate = controls.querySelector(".player__rate");
  const pictureInPicture = controls.querySelector("[data-player-pip]");
  const fullscreen = controls.querySelector("[data-player-fullscreen]");
  const isIPhone = /\biPhone\b|\biPod\b/.test(navigator.userAgent);
  const useContainerFullscreen = !isIPhone && document.fullscreenEnabled &&
    typeof player.requestFullscreen === "function";
  const useNativeFullscreen = typeof video.webkitEnterFullscreen === "function";
  let dragPointer = null;

  function updateSeek(time) {
    const fraction = seek.disabled ? 0 : time / video.duration;
    seek.value = fraction * Number(seek.max);
    seek.style.setProperty("--seek-progress", `${fraction * 100}%`);
    seek.setAttribute("aria-valuetext", `${formatVideoTime(time)} de ${formatVideoTime(video.duration)}`);
  }

  function updateTime() {
    seek.disabled = !Number.isFinite(video.duration) || video.duration <= 0;
    fullscreen.disabled = !useContainerFullscreen && video.readyState < HTMLMediaElement.HAVE_METADATA;
    pictureInPicture.disabled = video.readyState < HTMLMediaElement.HAVE_METADATA;
    timeLabel.textContent = `${formatVideoTime(video.currentTime)} / ${formatVideoTime(video.duration)}`;
    if (dragPointer === null) {
      updateSeek(video.currentTime);
    }
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

  function endDrag(event) {
    if (event.pointerId !== dragPointer) {
      return;
    }
    dragPointer = null;
    const commit = event.type === "pointerup" && !seek.disabled;
    if (commit) {
      video.currentTime = pointerFraction(event) * video.duration;
    }
    updateTime();

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
    seek.setPointerCapture(event.pointerId);
    seek.focus({ preventScroll: true });
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

  function restoreNativeControls() {
    preview.hide();
    controls.hidden = true;
    video.controls = true;
  }

  function updatePlayButton() {
    const playing = !video.paused && !video.ended;
    play.querySelector(".icon-play").hidden = playing;
    play.querySelector(".player__pause-icon").hidden = !playing;
    setPlayerLabel(play, playing ? "Pausar" : "Reproducir");
  }

  function togglePlayback() {
    if (video.paused || video.ended) {
      video.play().catch((error) => {
        if (error.name !== "AbortError") {
          restoreNativeControls();
        }
      });
    } else {
      video.pause();
    }
  }

  play.addEventListener("click", togglePlayback);
  video.addEventListener("click", () => {
    if (!video.controls) {
      togglePlayback();
    }
  });
  for (const event of ["play", "pause", "ended"]) {
    video.addEventListener(event, updatePlayButton);
  }
  video.addEventListener("error", restoreNativeControls);
  video.querySelector("source")?.addEventListener("error", restoreNativeControls);

  function updateVolume() {
    const muted = video.muted || video.volume === 0;
    volume.value = video.muted ? 0 : video.volume;
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
    preview.hide();
    setPlayerLabel(fullscreen, document.fullscreenElement === player ? "Salir de pantalla completa" : "Pantalla completa");
  });
  video.addEventListener("webkitbeginfullscreen", () => {
    preview.hide();
    controls.hidden = true;
  });
  video.addEventListener("webkitendfullscreen", () => {
    if (!video.error) {
      video.controls = false;
      controls.hidden = false;
      fullscreen.focus({ preventScroll: true });
    }
  });
  window.addEventListener("pagehide", preview.hide);

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
  initializePlayer(video, player, playerControls);
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
