import { fetchTableState, fetchTableStateEvents, fetchTableStateReconciliation, fetchNearbyMoves, tableStateImageUrl, submitTableStateOverride } from "./api.js";
import { getDate } from "./dateUtils.js";

const STALE_THRESHOLD_MS = 5 * 60 * 1000; // collector polls every ~60s; 5x that is a generous "still alive" window

// updateTableState() and updateReconciliation() both run every 30s cycle
// and both have their own reason to flag #tableStateCard as alerting
// (staleness, gap-open-too-long). Each independently calling
// classList.toggle("status-alert", ...) would let whichever one runs last
// silently clobber the other's decision -- this shared state + single
// toggle point is what keeps both reasons visible at once.
const alertReasons = { stale: false, gapAlert: false };
function refreshStatusAlert() {
  const card = document.getElementById("tableStateCard");
  card.classList.toggle("status-alert", alertReasons.stale || alertReasons.gapAlert);
}

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

//--------------------------------------------------
// Per-delivery drill-down -- wired once here (not inside updateLoadEvents,
// which replaces #loadEventsList's children every poll cycle whenever the
// event set actually changes) via delegation on the parent, which persists
// across those innerHTML swaps. "toggle" doesn't bubble, so this needs
// capture:true to catch it on the way down from whichever <details> the
// user actually opened.
//--------------------------------------------------
document.getElementById("loadEventsList").addEventListener("toggle", async (e) => {
  const details = e.target;
  if (!details.matches || !details.matches(".load-event-row") || !details.open) return;

  const container = details.querySelector(".nearby-moves");
  if (container.dataset.loaded) return; // fetched once already; don't re-fetch on every re-open

  try {
    const delta = Number(details.dataset.delta);
    const { bestFit } = await fetchNearbyMoves(details.dataset.recordedAt, delta);
    container.dataset.loaded = "true";

    if (!bestFit) {
      container.innerHTML = "<i>No Plex moves found nearby.</i>";
      return;
    }

    const when = new Date(getDate(bestFit.timeMoved)).toLocaleString();
    const countNote = bestFit.count === delta
      ? `matches this delivery's count of ${delta}`
      : `this delivery was ${delta}, closest batch found was ${bestFit.count}`;
    const serialList = bestFit.serials.map(s => s.serialNo).join(", ");

    container.innerHTML = `
      <div class="nearby-move-row">
        <b>${bestFit.count} moved</b> at ${when} (${countNote})
        <div class="load-event-time">${serialList}</div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<i>Failed to load: ${err.message}</i>`;
  }
}, true);

export async function updateTableState() {
  const body = document.getElementById("tableStateBody");

  try {
    const status = await fetchTableState();

    if (!status || status.confirmedCount == null) {
      const html = "<i>No confirmed count yet.</i>";
      if (body.innerHTML !== html) body.innerHTML = html;
      alertReasons.stale = false;
      refreshStatusAlert();
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
    alertReasons.stale = isStale || !hasUpdatedAt;
    refreshStatusAlert();
  } catch (err) {
    console.error("Table state check failed:", err);
  }
}

//--------------------------------------------------
// Gap alert sound -- a repeating chime while gapAlert is active, so
// someone in the room (not necessarily looking at the screen) notices,
// not just a silent color change. Generated with the Web Audio API
// directly rather than an audio file to host. Repeats every
// ALARM_REPEAT_MS while unresolved (a single one-shot beep could be
// missed by exactly the "wasn't looking right then" person this is for)
// and stops automatically the moment gapAlert clears.
//--------------------------------------------------
const ALARM_REPEAT_MS = 5 * 60 * 1000;

let audioCtx = null;
let lastAlarmPlayedAt = 0;
let gapWasActive = false;

function playAlarmTone() {
  // Lazily created (and resumed) here rather than at module load -- most
  // browsers block audio until there's been some user interaction on the
  // page, so creating it at load time would just create it in a
  // permanently suspended state anyway. Any click/tap anywhere on an
  // already-open dashboard (or just loading it via a normal navigation)
  // satisfies that requirement for the rest of the tab's lifetime.
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();

  const beepAt = (startOffset, freq) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = "square";
    osc.frequency.value = freq;
    gain.gain.value = 0.15;
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    const startTime = audioCtx.currentTime + startOffset;
    osc.start(startTime);
    osc.stop(startTime + 0.15);
  };

  // three short beeps, alternating pitch -- distinct enough to notice
  // without being an actual siren
  beepAt(0, 880);
  beepAt(0.2, 880);
  beepAt(0.4, 880);
}

function maybePlayGapAlarm(gapAlert) {
  if (!gapAlert) {
    gapWasActive = false; // next incident, even minutes later, gets its own immediate alert
    return;
  }

  const now = Date.now();
  const justStarted = !gapWasActive;
  gapWasActive = true;

  if (!justStarted && now - lastAlarmPlayedAt < ALARM_REPEAT_MS) return;

  lastAlarmPlayedAt = now;
  try {
    playAlarmTone();
  } catch (err) {
    console.error("Gap alarm sound failed:", err);
  }
}

// reason -> a short, human label for what triggered this delivery's count increase
const REASON_LABEL = {
  camera_consensus: "camera",
  manual_override: "manual correction",
  furnace_decrement: "furnace", // shouldn't normally appear here (that reason only ever decreases), kept as a fallback label
};

// Aggregate reconciliation for the current shift, replacing the old
// per-event Plex-match indicator -- a delivery's recordedAt lags the real
// delivery by an unpredictable amount (consensus takes a few readings to
// confirm, and every furnace decrement resets that window), so comparing
// individual event *timing* was unreliable. This compares running totals
// instead, for the same shift "Logs loaded this shift" already uses: logs
// delivered (summed count-increases, per the camera/table_state) vs logs
// moved in Plex (log_files.timeMoved -- scanned in by the material
// handler) -- a real, if coarser, traceability signal.
export async function updateReconciliation() {
  const el = document.getElementById("reconciliationSummary");
  const banner = document.getElementById("gapAlertBanner");

  try {
    const r = await fetchTableStateReconciliation();
    const windowLabel = r.sinceHours == null ? "this shift" : `last ${r.sinceHours}h`;

    const html = r.netDifference > 0
      ? `<span class="reconciliation-bad">&#9888; ${r.delivered} delivered ${windowLabel}, ${r.moved} moved in Plex -- net +${r.netDifference} unaccounted</span>`
      : `<span class="reconciliation-ok">&#10003; ${r.delivered} delivered ${windowLabel}, ${r.moved} moved in Plex -- reconciled</span>`;

    if (el.innerHTML !== html) el.innerHTML = html;

    // A short-lived gap (camera consensus catching up to a Plex move that
    // already happened) is normal and doesn't get a banner -- gapAlert
    // only turns true once the gap has stayed open past
    // reconciliation.GAP_ALERT_THRESHOLD_MINUTES, which is the real signal
    // something's actually wrong rather than just still resolving.
    const bannerHtml = r.gapAlert
      ? `&#9888; Gap open for ${Math.round(r.gapOpenMinutes)} min (since ${new Date(getDate(r.gapOpenSince)).toLocaleTimeString()}) -- check the physical tags at the table against recent deliveries below`
      : "";
    if (banner.innerHTML !== bannerHtml) banner.innerHTML = bannerHtml;

    alertReasons.gapAlert = r.gapAlert;
    refreshStatusAlert();
    maybePlayGapAlarm(r.gapAlert);
  } catch (err) {
    console.error("Reconciliation check failed:", err);
  }
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

    // Node-level diff, same pattern as renderList.js's renderRows() --
    // rows are <details> the user can expand into a lazy-fetched best-fit
    // lookup (see the delegated toggle listener above); wholesale
    // innerHTML replacement on every 30s poll was collapsing any row the
    // user had open and discarding its already-fetched content. Keying on
    // recordedAt (unique per event, to the millisecond) lets untouched
    // rows -- the common case, since events rarely change once written --
    // survive a refresh completely undisturbed.
    const existing = new Map();
    list.querySelectorAll(".load-event-row").forEach(el => existing.set(el.dataset.recordedAt, el));

    // Anything else -- the initial static "Checking..." placeholder, or a
    // leftover "No deliveries recorded yet." message from a prior empty
    // state -- isn't tracked by the diff above and would otherwise just
    // sit there once real rows start getting appended.
    list.querySelectorAll(":scope > *:not(.load-event-row)").forEach(el => el.remove());

    const seen = new Set();

    events.forEach(ev => {
      const when = new Date(getDate(ev.recordedAt));
      const key = when.toISOString();
      seen.add(key);

      let details = existing.get(key);

      if (!details) {
        const label = REASON_LABEL[ev.reason] || ev.reason || "unknown";

        details = document.createElement("details");
        details.className = "load-event-row";
        details.dataset.recordedAt = key;
        details.dataset.delta = ev.delta;
        details.innerHTML = `
          <summary>
            <span class="load-event-delta">+${ev.delta}</span>
            <b>${ev.newCount} on table</b> (${label})
            <div class="load-event-time">${when.toLocaleString()}</div>
          </summary>
          <div class="nearby-moves"><i>Click to check nearby Plex activity...</i></div>
        `;
      }
      // else: an event we've already rendered -- leave it exactly as is,
      // whatever open/loaded/fetched state it's currently in.

      // appendChild on an already-attached node moves it -- iterating in
      // the API's own (newest-first) order keeps list order correct
      // without recreating untouched nodes.
      list.appendChild(details);
    });

    existing.forEach((el, key) => {
      if (!seen.has(key)) el.remove();
    });
  } catch (err) {
    console.error("Load events check failed:", err);
  }
}
