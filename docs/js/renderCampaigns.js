import { state } from "./state.js";
import { getDate } from "./dateUtils.js";

export function renderCampaigns() {
  const select = document.getElementById("campaignSelect");

  select.innerHTML = "";

  if (!state.campaigns.length) {
    select.innerHTML = "<option>No campaigns found</option>";
    return;
  }

  state.campaigns.forEach((campaign, index) => {
    const option = document.createElement("option");

    option.value = index;

    const status = campaign.active ? " (Current)" : "";

    option.text =
      `${campaign.plexPart}${status} - ${new Date(getDate(campaign.startedAt)).toLocaleString()}`;

    select.appendChild(option);
  });

  showCampaign(0);
}

export function showCampaign(index) {
  const campaign = state.campaigns[index];

  if (!campaign) return;

  document.getElementById("campaignSummary").innerHTML = `
        <b>Plex Part:</b> ${campaign.plexPart}<br>
        <b>Alloy Code:</b> ${campaign.alloyCode}<br>
        <b>Started:</b> ${new Date(getDate(campaign.startedAt)).toLocaleString()}<br>
        <b>Ended:</b> ${campaign.active
      ? "Currently Running"
      : new Date(getDate(campaign.endedAt)).toLocaleString()
    }<br>
        <b>Status:</b> ${campaign.active ? "Active" : "Complete"}
    `;

  document.getElementById("campaignLogs").innerHTML =
    "<i>Campaign details coming soon...</i>";
}
