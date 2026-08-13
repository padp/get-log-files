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

    // updatedAt is a newer field than confirmedCount -- an older deployed
    // collector can be writing a real confirmedCount without it yet. Don't
    // let that silently fall through to dateUtils.js's epoch-time fallback,
    // which reads as a nonsense "stale" timestamp (misread once already as
    // a real staleness warning) instead of what it actually means: the
    // collector needs updating, not that it's stopped running.
    const hasUpdatedAt = status.updatedAt != null;
    const updatedAt = hasUpdatedAt ? new Date(getDate(status.updatedAt)) : null;
    const isStale = hasUpdatedAt && Date.now() - updatedAt.getTime() > STALE_THRESHOLD_MS;

    const html = `
      <b>Logs on Table:</b> ${status.confirmedCount}
      ${isStale
        ? `<div class="stale-warning">&#9888; Last updated ${updatedAt.toLocaleTimeString()} -- collector may not be running</div>`
        : ""}
      ${!hasUpdatedAt
        ? `<div class="stale-warning">&#9888; No timestamp from collector -- update it to the latest version to enable staleness checks</div>`
        : ""}
    `;

    if (body.innerHTML !== html) body.innerHTML = html;
    card.classList.toggle("status-alert", isStale || !hasUpdatedAt);
  } catch (err) {
    console.error("Table state check failed:", err);
  }
}
