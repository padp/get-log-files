import { fetchTableState, fetchTableStateEvents, tableStateImageUrl, submitTableStateOverride } from "./api.js";
import { getDate } from "./dateUtils.js";

const STALE_THRESHOLD_MS = 5 * 60 * 1000; // collector polls every ~60s; 5x that is a generous "still alive" window

//--------------------------------------------------
// Supervisory override -- wired once at load, since the <details>/<form>
// live outside #tableStateBody and survive the 30s poll's innerHTML swaps
//--------------------------------------------------
const supervisoryPanel = document.getElementById("supervisoryPanel");
const supervisoryImage = document.getElementById("supervisoryImage");
const supervisoryForm = document.getElementById("supervisoryForm");
const supervisoryMessage = document.getElementById("supervisoryMessage");

supervisoryPanel.addEventListener("toggle", () => {
  if (!supervisoryPanel.open) return;

  // re-fetch (cache-busted) every time it's opened, not just the first --
  // a supervisor deciding whether to override wants the *current* photo
  supervisoryImage.innerHTML = `<img src="${tableStateImageUrl()}" alt="Most recent table photo" />`;
});

supervisoryForm.addEventListener("submit", async e => {
  e.preventDefault();

  const count = Number(document.getElementById("overrideCount").value);
  const username = document.getElementById("overrideUsername").value;
  const password = document.getElementById("overridePassword").value;
  const reason = document.getElementById("overrideReason").value;

  supervisoryMessage.textContent = "Saving...";

  try {
    await submitTableStateOverride({ count, username, password, reason });

    supervisoryMessage.textContent = `Saved -- confirmed count set to ${count}.`;
    supervisoryMessage.classList.remove("supervisory-error");
    document.getElementById("overrideCount").value = "";
    document.getElementById("overridePassword").value = "";
    document.getElementById("overrideReason").value = "";

    updateTableState();
  } catch (err) {
    supervisoryMessage.textContent = `Failed: ${err.message}`;
    supervisoryMessage.classList.add("supervisory-error");
  }
});

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

// reason -> a short, human label for what triggered this delivery's count increase
const REASON_LABEL = {
  camera_consensus: "camera",
  manual_override: "manual correction",
  furnace_decrement: "furnace", // shouldn't normally appear here (that reason only ever decreases), kept as a fallback label
};

function plexMatchHtml(ev) {
  if (ev.plexMatchCount >= ev.delta) {
    return `<span class="plex-match plex-match-ok">&#10003; matched in Plex (${ev.plexMatchCount})</span>`;
  }

  if (ev.plexMatchCount > 0) {
    return `<span class="plex-match plex-match-partial">&#9888; only ${ev.plexMatchCount}/${ev.delta} matched in Plex</span>`;
  }

  return `<span class="plex-match plex-match-none">&#9888; no matching Plex scan found</span>`;
}

export async function updateLoadEvents() {
  const list = document.getElementById("loadEventsList");

  try {
    const events = await fetchTableStateEvents();

    if (!events || events.length === 0) {
      const html = "<i>No deliveries recorded yet.</i>";
      if (list.innerHTML !== html) list.innerHTML = html;
      return;
    }

    const html = events.map(ev => {
      const when = new Date(getDate(ev.recordedAt));
      const label = REASON_LABEL[ev.reason] || ev.reason || "unknown";

      return `
        <div class="load-event-row">
          <span class="load-event-delta">+${ev.delta}</span>
          <b>${ev.newCount} on table</b> (${label})
          <div class="load-event-time">${when.toLocaleString()}</div>
          <div class="load-event-plex">${plexMatchHtml(ev)}</div>
        </div>
      `;
    }).join("");

    if (list.innerHTML !== html) list.innerHTML = html;
  } catch (err) {
    console.error("Load events check failed:", err);
  }
}
