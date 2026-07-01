import { getDate } from "./dateUtils.js";

export function showObject(obj) {
  document.getElementById("recordSummary").innerHTML = `
    <b>Serial:</b> ${obj.SerialNo || ""}<br>
    <b>Part:</b> ${obj.PartNo || ""}<br>
    <b>Heat:</b> ${obj.HeatNo || ""}<br>
    <b>Location:</b> ${obj.Location || ""}<br>
    <b>Quantity:</b> ${obj.Quantity || ""}<br>
    <b>Time Moved:</b> ${new Date(getDate(obj.timeMoved)).toLocaleString()}
  `;

  document.getElementById("rawJson").textContent = JSON.stringify(obj, null, 2);
}
