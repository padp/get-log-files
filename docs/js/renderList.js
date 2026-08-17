import { state, getSortedEntries } from "./state.js";
import { getDate } from "./dateUtils.js";
import { showObject } from "./renderRecord.js";
import { isFlaggedRemoval } from "./flagUtils.js";
import { fetchInventoryItem } from "./api.js";

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

      div.onclick = async () => {
        state.selectedId = row._id;
        container.querySelectorAll(".item.selected").forEach(el => el.classList.remove("selected"));
        div.classList.add("selected");

        // Show what's already on hand immediately -- the list payload
        // no longer includes each item's full move history (dropped for
        // onload speed), so fetch that separately and fill it in once it
        // arrives rather than block the click on it.
        showObject(row);

        try {
          const full = await fetchInventoryItem(row._id);
          if (full && state.selectedId === row._id) showObject(full);
        } catch (e) {
          console.error("Failed to load full record detail", e);
        }
      };
    }

    const flagHtml = isFlaggedRemoval(row)
      ? `<div class="item-flag">&#9888; Moved without being run at the press</div>`
      : "";

    const html = `
      <div class="item-title">${row._id}</div>
      <div class="item-meta">${new Date(getDate(row.timeMoved)).toLocaleString()}</div>
      ${flagHtml}
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
