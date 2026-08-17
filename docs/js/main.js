import { fetchDashboard, fetchCampaigns } from "./api.js";
import { state } from "./state.js";
import { getDate } from "./dateUtils.js";
import { loadKeyList } from "./renderList.js";
import { updateDashboard } from "./renderDashboard.js";
import { renderCampaigns, showCampaign } from "./renderCampaigns.js";
import { updateScheduleStatus } from "./renderScheduleStatus.js";
import { updateTableState, updateLoadEvents } from "./renderTableState.js";

//--------------------------------------------------
// Load data
//--------------------------------------------------
async function loadData() {
  try {
    // Search-panel list and dashboard shift stats are independent fetches
    // now -- the list is paginated/server-searched (renderList.js owns its
    // own fetching), and the dashboard is scoped server-side to just the
    // current shift, so neither needs the other's data.
    try {
      await loadKeyList();
    } catch (e) {
      console.error("loadKeyList failed", e);
    }

    try {
      updateDashboard(await fetchDashboard());
    } catch (e) {
      console.error("updateDashboard failed", e);
    }

    updateScheduleStatus();
    updateTableState();
    updateLoadEvents();

    const unsortedCampaigns = await fetchCampaigns();

    state.campaigns = [...unsortedCampaigns].sort(
      (a, b) => new Date(getDate(b.startedAt)) - new Date(getDate(a.startedAt))
    );

    renderCampaigns();
  } catch (err) {
    console.error("Load error:", err);
  }
}

//--------------------------------------------------
// Campaign select
//--------------------------------------------------
document.getElementById("campaignSelect").addEventListener("change", e => {
  showCampaign(Number(e.target.value));
});

//--------------------------------------------------
// Mobile panel nav
//--------------------------------------------------
const panels = {
  list: document.getElementById("left"),
  dashboard: document.getElementById("right"),
  campaigns: document.getElementById("rightmost"),
};

function showPanel(name) {
  Object.entries(panels).forEach(([key, el]) => {
    el.classList.toggle("active-panel", key === name);
  });

  document.querySelectorAll(".mobile-nav button").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.panel === name);
  });
}

document.querySelectorAll(".mobile-nav button").forEach(btn => {
  btn.addEventListener("click", () => showPanel(btn.dataset.panel));
});

//--------------------------------------------------
// Init
//--------------------------------------------------
window.addEventListener("load", async () => {
  await loadData();
  setInterval(loadData, 30000);
});
