import { state } from "./state.js";
import { getDate } from "./dateUtils.js";
import { getId } from "./bsonUtils.js";
import { fetchCampaignDetails } from "./api.js";

export function renderCampaigns() {
  const select = document.getElementById("campaignSelect");

  if (!state.campaigns.length) {
    select.innerHTML = "<option>No campaigns found</option>";
    return;
  }

  const previousId = state.selectedCampaignId;

  select.innerHTML = "";
  state.campaigns.forEach((campaign, index) => {
    const option = document.createElement("option");

    option.value = index;

    const status = campaign.active ? " (Current)" : "";

    option.text =
      `${campaign.plexPart}${status} - ${new Date(getDate(campaign.startedAt)).toLocaleString()}`;

    select.appendChild(option);
  });

  const previousIndex = previousId
    ? state.campaigns.findIndex(c => getId(c._id) === previousId)
    : -1;

  const index = previousIndex >= 0 ? previousIndex : 0;
  select.value = index;

  const selectionChanged = previousIndex < 0;
  const selectedCampaign = state.campaigns[index];

  // Re-fetch/re-render the detail panel when the selection actually changed,
  // or when the still-selected campaign is the active one (its stats keep
  // changing as new logs come in). A completed campaign's numbers are final,
  // so background refreshes leave the panel alone instead of flashing it.
  if (selectionChanged || selectedCampaign.active) {
    showCampaign(index);
  }
}

export async function showCampaign(index) {
  const campaign = state.campaigns[index];

  if (!campaign) return;

  const campaignId = getId(campaign._id);
  const isNewSelection = state.selectedCampaignId !== campaignId;
  state.selectedCampaignId = campaignId;

  const summaryHtml = `
        <b>Plex Part:</b> ${campaign.plexPart}<br>
        <b>Alloy Code:</b> ${campaign.alloyCode}<br>
        <b>Started:</b> ${new Date(getDate(campaign.startedAt)).toLocaleString()}<br>
        <b>Ended:</b> ${campaign.active
      ? "Currently Running"
      : new Date(getDate(campaign.endedAt)).toLocaleString()
    }<br>
        <b>Status:</b> ${campaign.active ? "Active" : "Complete"}
    `;

  const summaryEl = document.getElementById("campaignSummary");
  if (summaryEl.innerHTML !== summaryHtml) summaryEl.innerHTML = summaryHtml;

  const logsEl = document.getElementById("campaignLogs");

  // Only show the interim loading state when switching to a campaign we
  // haven't already displayed -- a background refresh of the same campaign
  // should silently swap in new numbers, not flash blank first.
  if (isNewSelection) {
    logsEl.innerHTML = "<i>Loading details...</i>";
  }

  try {
    const { stats } = await fetchCampaignDetails(campaignId);

    const html = `
      <b>Logs Run:</b> ${stats.logCount}<br>
      <b>Cumulative Length:</b> ${stats.totalLength.toLocaleString()} in<br>
      <b>Total Weight:</b> ${stats.totalWeight.toLocaleString()} lbs
    `;

    if (logsEl.innerHTML !== html) logsEl.innerHTML = html;
  } catch (err) {
    console.error("Campaign details failed:", err);

    if (isNewSelection) {
      logsEl.innerHTML = "<i>Failed to load campaign details.</i>";
    }
  }
}
