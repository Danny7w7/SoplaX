const video = document.getElementById("my-video");

video.addEventListener("contextmenu", (event) => {
  event.preventDefault();
});

// Descripción: se recorta a cuatro líneas y se expande bajo demanda.
const description = document.querySelector("[data-clamp]");
const descriptionToggle = document.querySelector("[data-clamp-toggle]");
if (description && descriptionToggle) {
  description.classList.add("is-clamped");
  if (description.scrollHeight > description.clientHeight + 1) {
    descriptionToggle.hidden = false;
    descriptionToggle.addEventListener("click", () => {
      const expanded = !description.classList.toggle("is-clamped");
      descriptionToggle.setAttribute("aria-expanded", String(expanded));
      descriptionToggle.textContent = expanded ? "Mostrar menos" : "Mostrar más";
    });
  } else {
    description.classList.remove("is-clamped");
  }
}
