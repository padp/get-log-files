import { fetchScannerHealth } from "./api.js";

function formatGap(minutes) {
  if (minutes == null) return "unknown";

  if (minutes < 60) return `${Math.round(minutes)}m`;

  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);

  return `${hours}h ${mins}m`;
}

export async function updateScannerHealth() {
  const card = document.getElementById("scannerHealthCard");
  const body = document.getElementById("scannerHealthBody");

  try {
    const health = await fetchScannerHealth();
    const gapText = formatGap(health.gapMinutes);

    let html;

    if (health.likelyScannerIssue) {
      const count = health.billetsSinceLastLog;

      html = `
        <b>&#9888; Possible scanner outage</b><br>
        No new logs scanned in for ${gapText}, but the press has run
        ${count} billet${count === 1 ? "" : "s"} in that time.
      `;

      card.classList.remove("status-ok");
      card.classList.add("status-alert");
    } else {
      html = `
        <b>Scanner OK</b><br>
        Last log arrived ${gapText} ago.
      `;

      card.classList.remove("status-alert");
      card.classList.add("status-ok");
    }

    if (body.innerHTML !== html) body.innerHTML = html;
  } catch (err) {
    console.error("Scanner health check failed:", err);
  }
}
