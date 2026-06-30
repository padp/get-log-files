
let jsonData = [];
let selectedDiv = null;
let campaigns = [];

const API_BASE = "https://get-log-files.onrender.com";

//--------------------------------------------------
// Load data
//--------------------------------------------------
async function loadData() {

  try {

    const response = await fetch(`${API_BASE}/api/inventory`);

    const text = await response.text();

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${text}`);
    }

    jsonData = JSON.parse(text);


    console.log("JSON loaded:", jsonData.length);

    try {
      renderKeys();
      console.log("renderKeys OK");
    } catch (e) {
      console.error("renderKeys failed", e);
    }

    try {
      updateDashboard();
      console.log("updateDashboard OK");
    } catch (e) {
      console.error("updateDashboard failed", e);
    }

    const campaignResponse = await fetch(`${API_BASE}/api/campaigns`);

    const unsortedCampaigns = await campaignResponse.json();

    campaigns = [...unsortedCampaigns].sort(
      (a, b) => new Date(b.startedAt) - new Date(a.startedAt)
    );
    console.log(campaigns);
    renderCampaigns();

  } catch (err) {
    console.error("Load error:", err);
  }
}

function renderCampaigns() {

  const select = document.getElementById("campaignSelect");

  select.innerHTML = "";

  if (!campaigns.length) {
    select.innerHTML = "<option>No campaigns found</option>";
    return;
  }
  console.log(campaigns);
  campaigns.forEach((campaign, index) => {

    const option = document.createElement("option");

    option.value = index;

    const status = campaign.active ? " (Current)" : "";

    option.text =
      `${campaign.plexPart}${status} - ${new Date(getDate(campaign.startedAt)).toLocaleString()}`;

    select.appendChild(option);
  });

  showCampaign(0);
}

//--------------------------------------------------
// Sort
//--------------------------------------------------
function getSortedEntries() {
  return [...jsonData].sort((a, b) =>
    new Date(getDate(b.timeMoved)) - new Date(getDate(a.timeMoved))
  );
}

function getDate(value) {

  if (!value) return new Date(0);

  if (typeof value === "string")
    return new Date(value);

  if (value.$date)
    return new Date(value.$date);

  return new Date(value);
}

//--------------------------------------------------
// Render list
//--------------------------------------------------
function renderKeys() {

  const filter = document.getElementById("search").value.toLowerCase();
  const container = document.getElementById("keyList");

  container.innerHTML = "";

  getSortedEntries()
    .filter(row =>
      JSON.stringify(row).toLowerCase().includes(filter)
    )
    .forEach(row => {

      const div = document.createElement("div");
      div.className = "item";

      div.innerHTML = `
        <div style="font-weight:bold;font-size:14px;">
          ${row._id}
        </div>
        <div style="color:#666;font-size:12px;">
          ${new Date(getDate(row.timeMoved)).toLocaleString()}
        </div>
      `;

      div.onclick = () => {
        if (selectedDiv) selectedDiv.classList.remove("selected");
        div.classList.add("selected");
        selectedDiv = div;

        showObject(row);
      };

      container.appendChild(div);
    });
}

//--------------------------------------------------
// Shift logic
//--------------------------------------------------
function getCurrentShiftStart() {

  const now = new Date();

  const s1 = new Date(now); s1.setHours(7, 0, 0, 0);
  const s2 = new Date(now); s2.setHours(15, 0, 0, 0);
  const s3 = new Date(now); s3.setHours(23, 0, 0, 0);

  if (now >= s3) return s3;
  if (now >= s2) return s2;
  if (now >= s1) return s1;

  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  y.setHours(23, 0, 0, 0);

  return y;
}

//--------------------------------------------------
// Dashboard
//--------------------------------------------------
function updateDashboard() {

  const entries = getSortedEntries();
  const shiftStart = getCurrentShiftStart();

  const logLength = (data) => {
    try {
      console.log("entry");
      if (!data || !Array.isArray(data.history) || data.history.length === 0) {
        console.log("if statement sent blank");
        return "";
      }

      const startWeight = data.startWeight;
      console.log(startWeight);
      if (!startWeight) {
        return "";
      }

      const calculatedLength = startWeight / 4.9375;

      const shortLengthTest = Math.abs(216 - calculatedLength);
      const longLengthTest = Math.abs(240 - calculatedLength);

      return shortLengthTest > longLengthTest ? 240 : 216;

    } catch (e) {
      return "";
    }
  };

  const shiftCount = entries.filter(v =>
    new Date(getDate(v.timeMoved)) >= shiftStart
  ).length;

  document.getElementById("shiftCount").textContent =
    `Logs This Shift: ${shiftCount}`;

  const recent = document.getElementById("recentLogs");
  recent.innerHTML = "";

  entries.slice(0, shiftCount).forEach(v => {

    const row = document.createElement("div");
    row.style.padding = "6px";
    row.style.borderBottom = "1px solid #eee";

    // -----------------------------
    // MAIN ROW HEADER
    // -----------------------------
    const header = document.createElement("div");

    header.innerHTML = `
      <b>${v.SerialNo || ""}</b>
      &nbsp;&nbsp;
      ${v.PartNo || ""}
      &nbsp;&nbsp;
      ${`${logLength(v, v.PartNo)} Inches`}
      <span style="float:right;color:#666;">
        ${new Date(getDate(v.timeMoved)).toLocaleTimeString()}
      </span>
    `;

    // -----------------------------
    // DROPDOWN (HISTORY)
    // -----------------------------
    const select = document.createElement("select");
    select.style.width = "100%";
    select.style.marginTop = "4px";
    select.style.padding = "4px";

    const defaultOption = document.createElement("option");
    defaultOption.text = "View History...";
    defaultOption.value = "";
    select.appendChild(defaultOption);

    if (Array.isArray(v.history)) {

      v.history.forEach(h => {

        const opt = document.createElement("option");

        const name = `${h.FirstName || ""} ${h.LastName || ""}`.trim();
        const action = h.LastAction || "";
        const loc = h.Location || "";

        opt.text = `${name} | ${action} | ${loc}`;
        opt.value = JSON.stringify(h);

        select.appendChild(opt);
      });
    }

    // -----------------------------
    // OPTIONAL DETAIL VIEW
    // -----------------------------
    const detail = document.createElement("div");
    detail.style.fontSize = "12px";
    detail.style.color = "#444";
    detail.style.marginTop = "4px";

    select.addEventListener("change", (e) => {

      if (!e.target.value) {
        detail.innerHTML = "";
        return;
      }

      const h = JSON.parse(e.target.value);

      detail.innerHTML = `
        <b>User:</b> ${h.FirstName || ""} ${h.LastName || ""}<br>
        <b>Action:</b> ${h.LastAction || ""}<br>
        <b>Location:</b> ${h.Location || ""}<br>
        <b>Update:</b> ${h.UpdateDate || ""}<br>
        <b>Change:</b> ${h.ChangeDate || ""}
      `;
    });

    // -----------------------------
    // ASSEMBLE ROW
    // -----------------------------
    row.appendChild(header);
    row.appendChild(select);
    row.appendChild(detail);

    recent.appendChild(row);
  });
}

//--------------------------------------------------
// Selected record
//--------------------------------------------------
function showObject(obj) {

  document.getElementById("recordSummary").innerHTML = `
    <b>Serial:</b> ${obj.SerialNo || ""}<br>
    <b>Part:</b> ${obj.PartNo || ""}<br>
    <b>Heat:</b> ${obj.HeatNo || ""}<br>
    <b>Location:</b> ${obj.Location || ""}<br>
    <b>Quantity:</b> ${obj.Quantity || ""}<br>
    <b>Time Moved:</b> ${new Date(getDate(obj.timeMoved)).toLocaleString()}
  `;

  document.getElementById("rawJson").textContent =
    JSON.stringify(obj, null, 2);
}

//--------------------------------------------------
// Search
//--------------------------------------------------
document.getElementById("search")
  .addEventListener("input", renderKeys);

//--------------------------------------------------
// Init
//--------------------------------------------------
window.addEventListener("load", async () => {

  await loadData();

  setInterval(loadData, 30000);
});

document
  .getElementById("campaignSelect")
  .addEventListener("change", e => {

    showCampaign(Number(e.target.value));

  });

function showCampaign(index) {

  const campaign = campaigns[index];

  if (!campaign)
    return;

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