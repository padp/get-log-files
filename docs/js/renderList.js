import { state, getSortedEntries } from "./state.js";
import { getDate } from "./dateUtils.js";
import { showObject } from "./renderRecord.js";

export function renderKeys() {
  const filter = document.getElementById("search").value.toLowerCase();
  const container = document.getElementById("keyList");

  const rows = getSortedEntries().filter(row =>
    JSON.stringify(row).toLowerCase().includes(filter)
  );

  const existing = new Map();
  container.querySelectorAll(".item").forEach(el => existing.set(el.dataset.id, el));

  const seen = new Set();

  rows.forEach(row => {
    seen.add(row._id);

    let div = existing.get(row._id);

    if (!div) {
      div = document.createElement("div");
      div.className = "item";
      div.dataset.id = row._id;

      div.onclick = () => {
        state.selectedId = row._id;
        container.querySelectorAll(".item.selected").forEach(el => el.classList.remove("selected"));
        div.classList.add("selected");
        showObject(row);
      };
    }

    const html = `
      <div style="font-weight:bold;font-size:14px;">
        ${row._id}
      </div>
      <div style="color:#666;font-size:12px;">
        ${new Date(getDate(row.timeMoved)).toLocaleString()}
      </div>
    `;

    if (div.innerHTML !== html) div.innerHTML = html;

    div.classList.toggle("selected", row._id === state.selectedId);

    // appendChild on an already-attached node moves it -- iterating rows in
    // order keeps DOM order correct without recreating untouched nodes.
    container.appendChild(div);
  });

  existing.forEach((div, id) => {
    if (!seen.has(id)) div.remove();
  });
}
