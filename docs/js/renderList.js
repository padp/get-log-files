import { state } from "./state.js";
import { getDate } from "./dateUtils.js";
import { showObject } from "./renderRecord.js";
import { isFlaggedRemoval } from "./flagUtils.js";
import { fetchInventory, fetchInventoryItem } from "./api.js";

const PAGE_SIZE = 100;
const SEARCH_DEBOUNCE_MS = 300;

function renderRows(rows) {
  const container = document.getElementById("keyList");

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

        // Show what's already on hand immediately -- list rows never
        // include each item's full move history (dropped for onload
        // speed), so fetch that separately and fill it in once it arrives
        // rather than block the click on it.
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

  updateLoadMoreButton();
}

function updateLoadMoreButton() {
  let btn = document.getElementById("loadMoreKeys");
  const hasMore = state.jsonData.length < state.listTotal;

  if (!hasMore) {
    if (btn) btn.remove();
    return;
  }

  if (!btn) {
    btn = document.createElement("button");
    btn.id = "loadMoreKeys";
    btn.className = "load-more-btn";
    btn.addEventListener("click", () => {
      state.listLimit += PAGE_SIZE;
      loadKeyList({ reset: false });
    });
    document.getElementById("keyList").after(btn);
  }

  btn.textContent = `Load more (${state.jsonData.length} of ${state.listTotal})`;
}

// Fetches the list panel's data server-side (paginated, and server-filtered
// by state.listQuery when set) and renders it -- this is the *only* thing
// that talks to /api/inventory now; the full collection is never loaded
// into the browser just to filter it client-side.
export async function loadKeyList({ reset = false } = {}) {
  if (reset) state.listLimit = PAGE_SIZE;

  try {
    const { total, rows } = await fetchInventory({ q: state.listQuery, limit: state.listLimit, skip: 0 });
    state.jsonData = rows;
    state.listTotal = total;
    renderRows(rows);
  } catch (err) {
    console.error("Failed to load inventory list:", err);
  }
}

let searchDebounceTimer = null;

document.getElementById("search").addEventListener("input", e => {
  clearTimeout(searchDebounceTimer);
  const value = e.target.value;

  searchDebounceTimer = setTimeout(() => {
    state.listQuery = value;
    loadKeyList({ reset: true });
  }, SEARCH_DEBOUNCE_MS);
});
