"use strict";

// Listas de SoplaX. Los select múltiples pasan a un selector de etiquetas con buscador; el select
// original queda oculto y sigue enviando los valores, así que sin JavaScript se usa el nativo.
// Iconos «check» y «x» de Lucide (https://lucide.dev), derivados de Feather. Licencia MIT.
// Copyright (c) 2013-present Cole Bemis. Copyright (c) 2026 Lucide Icons and Contributors.

const SVG_NS = "http://www.w3.org/2000/svg";
const CHOICE_ICONS = {
  check: ["M20 6 9 17l-5-5"],
  x: ["M18 6 6 18", "m6 6 12 12"],
};
const FILTER_THRESHOLD = 8;
let choicePickers = 0;

function choiceIcon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  const attributes = {
    width: "24", height: "24", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round",
    "aria-hidden": "true", focusable: "false",
  };
  for (const [attribute, value] of Object.entries(attributes)) {
    svg.setAttribute(attribute, value);
  }
  for (const d of CHOICE_ICONS[name]) {
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

function searchKey(text) {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text) {
    node.textContent = text;
  }
  return node;
}

function enhanceMultipleSelect(select) {
  choicePickers += 1;
  const id = select.id || `choices-${choicePickers}`;
  const label = select.id ? document.querySelector(`label[for="${CSS.escape(select.id)}"]`) : null;
  const labelText = label?.textContent.trim() || "las opciones";
  const options = [...select.options];

  const picker = element("div", "choice-picker");
  const list = element("div", "choice-picker__list");
  list.id = `${id}-opciones`;
  list.setAttribute("role", "group");
  if (label) {
    label.id ||= `${id}-etiqueta`;
    list.setAttribute("aria-labelledby", label.id);
  }

  let search = null;
  if (options.length > FILTER_THRESHOLD) {
    search = element("input", "input choice-picker__search");
    search.type = "search";
    search.id = `${id}-buscar`;
    search.placeholder = `Buscar en ${labelText.toLowerCase()}…`;
    search.autocomplete = "off";
    search.setAttribute("aria-controls", list.id);
    picker.append(search);
    if (label) {
      label.htmlFor = search.id;
    }
  } else if (label) {
    label.removeAttribute("for");
  }

  const status = element("p", "choice-picker__status");
  status.setAttribute("aria-live", "polite");
  const clear = element("button", "choice-picker__clear");
  clear.type = "button";
  clear.append(choiceIcon("x"), element("span", "", "Quitar todas"));
  const empty = element("p", "choice-picker__empty", "No hay coincidencias.");
  empty.hidden = true;

  const chips = options.map((option) => {
    const chip = element("label", "choice-picker__chip");
    const box = element("input", "choice-picker__box");
    box.type = "checkbox";
    box.checked = option.selected;
    box.disabled = option.disabled || select.disabled;
    chip.append(box, choiceIcon("check"), element("span", "", option.textContent.trim()));
    list.append(chip);
    return { chip, box, option, key: searchKey(option.textContent) };
  });

  function update() {
    const count = chips.filter(({ box }) => box.checked).length;
    status.textContent = count === 0 ? "Ninguna opción elegida" :
      count === 1 ? "1 opción elegida" : `${count} opciones elegidas`;
    clear.hidden = count === 0 || select.disabled;
  }

  function choose(choice, checked) {
    choice.box.checked = checked;
    choice.option.selected = checked;
  }

  for (const choice of chips) {
    choice.box.addEventListener("change", () => {
      choose(choice, choice.box.checked);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      update();
    });
  }

  clear.addEventListener("click", () => {
    for (const choice of chips) {
      choose(choice, false);
    }
    select.dispatchEvent(new Event("change", { bubbles: true }));
    update();
    (search || chips[0]?.box)?.focus();
  });

  search?.addEventListener("input", () => {
    const query = searchKey(search.value.trim());
    let visible = 0;
    for (const { chip, key } of chips) {
      chip.hidden = Boolean(query) && !key.includes(query);
      visible += chip.hidden ? 0 : 1;
    }
    empty.hidden = visible > 0;
  });

  // Enter en el buscador no envía el formulario: marca la opción si solo queda una visible.
  search?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    const visible = chips.filter(({ chip }) => !chip.hidden);
    if (visible.length === 1 && !visible[0].box.disabled) {
      visible[0].box.click();
    }
  });

  const footer = element("div", "choice-picker__footer");
  footer.append(status, clear);
  picker.append(list, empty, footer);
  select.hidden = true;
  select.after(picker);
  update();
}

// Selección simple: la opción vacía de Django («---------») pasa a un texto legible.
function relabelEmptyOption(select) {
  const empty = [...select.options].find((option) => option.value === "" && /^-+$/.test(option.textContent.trim()));
  if (empty) {
    empty.textContent = "Sin seleccionar";
  }
}

for (const select of document.querySelectorAll("select.input")) {
  if (select.multiple) {
    if (!select.required) {
      enhanceMultipleSelect(select);
    }
  } else {
    relabelEmptyOption(select);
  }
}
document.querySelectorAll("[data-choices-hint]").forEach((hint) => hint.remove());
