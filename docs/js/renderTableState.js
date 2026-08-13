import { fetchTableState } from "./api.js";
import { getDate } from "./dateUtils.js";

const STALE_THRESHOLD_MS = 5 * 60 * 1000; // collector polls every ~60s; 5x that is a generous "still alive" window

export async function updateTableState() {
  const card = document.getElementById("tableStateCard");
  const body = document.getElementById("tableStateBody");

  try {
    const status = await fetchTableState();

    if (!status || status.confirmedCount == null) {
      const html = "<i>No confirmed count yet.</i>";
      if (body.innerHTML !== html) body.innerHTML = html;
      card.classList.remove("status-alert");
      return;
    }

    const updatedAt = new Date(getDate(status.updatedAt));
    const isStale = Date.now() - updatedAt.getTime() > STALE_THRESHOLD_MS;

    const html = `
      <b>Logs on Table:</b> ${status.confirmedCount}
      ${isStale
        ? `<div class="stale-warning">&#9888; Last updated ${updatedAt.toLocaleTimeString()} -- collector may not be running</div>`
        : ""}
    `;

    if (body.innerHTML !== html) body.innerHTML = html;
    card.classList.toggle("status-alert", isStale);
  } catch (err) {
    console.error("Table state check failed:", err);
  }
}
