import { fetchInventory, fetchCampaigns } from "./api.js";
import { state } from "./state.js";
import { getDate } from "./dateUtils.js";
import { renderKeys } from "./renderList.js";
import { updateDashboard } from "./renderDashboard.js";
import { renderCampaigns, showCampaign } from "./renderCampaigns.js";

//--------------------------------------------------
// Load data
//--------------------------------------------------
async function loadData() {
  try {
    state.jsonData = await fetchInventory();
    console.log("JSON loaded:", state.jsonData.length);

    try {
      renderKeys();
    } catch (e) {
      console.error("renderKeys failed", e);
    }

    try {
      updateDashboard();
    } catch (e) {
      console.error("updateDashboard failed", e);
    }

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
// Search
//--------------------------------------------------
document.getElementById("search").addEventListener("input", renderKeys);

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
