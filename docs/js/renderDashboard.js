import { getSortedEntries } from "./state.js";
import { getDate } from "./dateUtils.js";

function getCurrentShiftStart() {
  const now = new Date();

  const s1 = new Date(now); s1.setHours(7, 0, 0, 0);
  const s2 = new Date(now); s2.setHours(15, 0, 0, 0);
  const s3 = new Date(now); s3.setHours(23, 0, 0, 0);

  if (now >= s3) return s3;
  if (now >= s2) return s2;
  if (now >= s1) return s1;

  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  y.setHours(23, 0, 0, 0);

  return y;
}

function logLength(data) {
  try {
    if (!data || !Array.isArray(data.history) || data.history.length === 0) {
      return "";
    }

    const startWeight = data.startWeight;
    if (!startWeight) {
      return "";
    }

    const calculatedLength = startWeight / 4.9375;

    const shortLengthTest = Math.abs(216 - calculatedLength);
    const longLengthTest = Math.abs(240 - calculatedLength);

    return shortLengthTest > longLengthTest ? 240 : 216;
  } catch (e) {
    return "";
  }
}

export function updateDashboard() {
  const entries = getSortedEntries();
  const shiftStart = getCurrentShiftStart();

  const shiftCount = entries.filter(
    v => new Date(getDate(v.timeMoved)) >= shiftStart
  ).length;

  document.getElementById("shiftCount").textContent = `Logs This Shift: ${shiftCount}`;

  const recent = document.getElementById("recentLogs");
  recent.innerHTML = "";

  entries.slice(0, shiftCount).forEach(v => {
    const row = document.createElement("div");
    row.style.padding = "6px";
    row.style.borderBottom = "1px solid #eee";

    // -----------------------------
    // MAIN ROW HEADER
    // -----------------------------
    const header = document.createElement("div");

    header.innerHTML = `
      <b>${v.SerialNo || ""}</b>
      &nbsp;&nbsp;
      ${v.PartNo || ""}
      &nbsp;&nbsp;
      ${`${logLength(v)} Inches`}
      <span style="float:right;color:#666;">
        ${new Date(getDate(v.timeMoved)).toLocaleTimeString()}
      </span>
    `;

    // -----------------------------
    // DROPDOWN (HISTORY)
    // -----------------------------
    const select = document.createElement("select");
    select.style.width = "100%";
    select.style.marginTop = "4px";
    select.style.padding = "4px";

    const defaultOption = document.createElement("option");
    defaultOption.text = "View History...";
    defaultOption.value = "";
    select.appendChild(defaultOption);

    if (Array.isArray(v.history)) {
      v.history.forEach(h => {
        const opt = document.createElement("option");

        const name = `${h.FirstName || ""} ${h.LastName || ""}`.trim();
        const action = h.LastAction || "";
        const loc = h.Location || "";

        opt.text = `${name} | ${action} | ${loc}`;
        opt.value = JSON.stringify(h);

        select.appendChild(opt);
      });
    }

    // -----------------------------
    // OPTIONAL DETAIL VIEW
    // -----------------------------
    const detail = document.createElement("div");
    detail.style.fontSize = "12px";
    detail.style.color = "#444";
    detail.style.marginTop = "4px";

    select.addEventListener("change", (e) => {
      if (!e.target.value) {
        detail.innerHTML = "";
        return;
      }

      const h = JSON.parse(e.target.value);

      detail.innerHTML = `
        <b>User:</b> ${h.FirstName || ""} ${h.LastName || ""}<br>
        <b>Action:</b> ${h.LastAction || ""}<br>
        <b>Location:</b> ${h.Location || ""}<br>
        <b>Update:</b> ${h.UpdateDate || ""}<br>
        <b>Change:</b> ${h.ChangeDate || ""}
      `;
    });

    // -----------------------------
    // ASSEMBLE ROW
    // -----------------------------
    row.appendChild(header);
    row.appendChild(select);
    row.appendChild(detail);

    recent.appendChild(row);
  });
}
