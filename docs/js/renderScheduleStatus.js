import { fetchScheduleStatus } from "./api.js";
import { getDate } from "./dateUtils.js";

const STALE_THRESHOLD_MS = 5 * 60 * 1000; // collector polls every ~60s; 5x that is a generous "still alive" window

function formatDuration(seconds) {
  if (seconds == null) return "unknown";

  const totalMinutes = Math.round(seconds / 60);

  if (totalMinutes < 60) return `${totalMinutes}m`;

  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;

  return `${hours}h ${mins}m`;
}

export async function updateScheduleStatus() {
  const card = document.getElementById("scheduleStatusCard");
  const body = document.getElementById("scheduleStatusBody");

  try {
    const status = await fetchScheduleStatus();

    if (!status) {
      const html = "<i>No schedule data yet.</i>";
      if (body.innerHTML !== html) body.innerHTML = html;
      card.classList.remove("status-alert");
      return;
    }

    const updatedAt = new Date(getDate(status.updatedAt));
    const isStale = Date.now() - updatedAt.getTime() > STALE_THRESHOLD_MS;

    const html = `
      <b>Alloy:</b> ${status.alloy}<br>
      <b>Billets Remaining:</b> ${status.billetsRemaining}<br>
      <b>Jobs Remaining:</b> ${status.jobsRemaining}<br>
      <b>Est. Time to Change:</b> ${formatDuration(status.etaSeconds)}
      ${isStale
        ? `<div class="schedule-stale">&#9888; Last updated ${updatedAt.toLocaleTimeString()} -- collector may not be running</div>`
        : ""}
    `;

    if (body.innerHTML !== html) body.innerHTML = html;
    card.classList.toggle("status-alert", isStale);
  } catch (err) {
    console.error("Schedule status check failed:", err);
  }
}
