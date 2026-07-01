import { state, getSortedEntries } from "./state.js";
import { getDate } from "./dateUtils.js";
import { showObject } from "./renderRecord.js";

export function renderKeys() {
  const filter = document.getElementById("search").value.toLowerCase();
  const container = document.getElementById("keyList");

  container.innerHTML = "";

  getSortedEntries()
    .filter(row => JSON.stringify(row).toLowerCase().includes(filter))
    .forEach(row => {
      const div = document.createElement("div");
      div.className = "item";

      div.innerHTML = `
        <div style="font-weight:bold;font-size:14px;">
          ${row._id}
        </div>
        <div style="color:#666;font-size:12px;">
          ${new Date(getDate(row.timeMoved)).toLocaleString()}
        </div>
      `;

      div.onclick = () => {
        if (state.selectedDiv) state.selectedDiv.classList.remove("selected");
        div.classList.add("selected");
        state.selectedDiv = div;

        showObject(row);
      };

      container.appendChild(div);
    });
}
