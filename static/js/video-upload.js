"use strict";

const uploadForm = document.querySelector(".video-upload form");
const publishButton = uploadForm.querySelector('button[type="submit"]');
uploadForm.addEventListener("submit", (event) => {
  if (publishButton.getAttribute("aria-busy") === "true") {
    event.preventDefault();
  }
}, { capture: true });

uploadForm.querySelectorAll("[data-max-bytes]").forEach((input) => {
  input.addEventListener("change", () => {
    const tooLarge = input.files[0]?.size > Number(input.dataset.maxBytes);
    input.setCustomValidity(tooLarge ? input.dataset.sizeError : "");
    if (tooLarge) {
      input.reportValidity();
    }
  });
});

const thumbnailInput = uploadForm.elements.miniatura;
const thumbnailPreview = uploadForm.querySelector("[data-thumbnail-preview]");
const thumbnailPlaceholder = thumbnailPreview.querySelector("[data-thumbnail-placeholder]");
const thumbnailImage = thumbnailPreview.querySelector("img");
thumbnailPreview.hidden = false;

thumbnailInput.addEventListener("change", () => {
  thumbnailImage.hidden = true;
  thumbnailImage.removeAttribute("src");
  thumbnailPlaceholder.hidden = false;

  const file = thumbnailInput.files[0];
  if (!file || !thumbnailInput.validity.valid) {
    return;
  }

  const reader = new FileReader();
  reader.addEventListener("load", () => {
    if (thumbnailInput.files[0] === file) {
      thumbnailImage.src = reader.result;
    }
  });
  reader.readAsDataURL(file);
});

thumbnailImage.addEventListener("load", () => {
  thumbnailImage.hidden = false;
  thumbnailPlaceholder.hidden = true;
});
