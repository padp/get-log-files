import { getDate } from "./dateUtils.js";
import { isFlaggedRemoval } from "./flagUtils.js";

export function showObject(obj) {
  const flagHtml = isFlaggedRemoval(obj)
    ? `<div class="record-flag">&#9888; Moved out of ${obj.Location || "this location"} without being run at the press
        (last action: ${(obj.lastMove && obj.lastMove.Action) || "unknown"})</div>`
    : "";

  document.getElementById("recordSummary").innerHTML = `
    ${flagHtml}
    <b>Serial:</b> ${obj.SerialNo || ""}<br>
    <b>Part:</b> ${obj.PartNo || ""}<br>
    <b>Heat:</b> ${obj.HeatNo || ""}<br>
    <b>Location:</b> ${obj.Location || ""}<br>
    <b>Quantity:</b> ${obj.Quantity || ""}<br>
    <b>Time Moved:</b> ${new Date(getDate(obj.timeMoved)).toLocaleString()}
  `;

  document.getElementById("rawJson").textContent = JSON.stringify(obj, null, 2);
}
