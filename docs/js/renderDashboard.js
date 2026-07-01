import { getSortedEntries } from "./state.js";
import { getDate } from "./dateUtils.js";
import { getId } from "./bsonUtils.js";

const WEIGHT_PER_INCH = 4.9375; // startWeight ~= length_in * WEIGHT_PER_INCH
const NONSENSE_TOLERANCE = 0.12; // how far (relatively) a weight may sit from both 216" and 240" before it's untrustworthy

function nearestLength(weight) {
  const length = weight / WEIGHT_PER_INCH;
  return Math.abs(length - 240) < Math.abs(length - 216) ? 240 : 216;
}

function isTrustworthy(weight) {
  if (!weight) return false;

  const length = weight / WEIGHT_PER_INCH;
  const off216 = Math.abs(length - 216) / 216;
  const off240 = Math.abs(length - 240) / 240;

  return Math.min(off216, off240) <= NONSENSE_TOLERANCE;
}

// Groups entries by campaign and finds each campaign's majority length, so
// entries with a missing/nonsensical startWeight can borrow it -- every
// entry in a campaign shares the same PartNo, so they're physically the
// same length.
function buildCampaignMajorityLengths(entries) {
  const trustworthyByCampaign = new Map();

  entries.forEach(v => {
    const campaignId = v.campaign && getId(v.campaign._id);
    if (!campaignId || !isTrustworthy(v.startWeight)) return;

    const lengths = trustworthyByCampaign.get(campaignId) || [];
    lengths.push(nearestLength(v.startWeight));
    trustworthyByCampaign.set(campaignId, lengths);
  });

  const majorityByCampaign = new Map();

  trustworthyByCampaign.forEach((lengths, campaignId) => {
    const counts = new Map();
    lengths.forEach(l => counts.set(l, (counts.get(l) || 0) + 1));
    const majority = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
    majorityByCampaign.set(campaignId, majority);
  });

  return majorityByCampaign;
}

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

function logLength(data, majorityByCampaign) {
  try {
    if (!data || !Array.isArray(data.history) || data.history.length === 0) {
      return "";
    }

    const startWeight = data.startWeight;
    if (!startWeight) {
      return "";
    }

    if (isTrustworthy(startWeight)) {
      return nearestLength(startWeight);
    }

    const campaignId = data.campaign && getId(data.campaign._id);
    const majority = campaignId && majorityByCampaign.get(campaignId);

    return majority || nearestLength(startWeight);
  } catch (e) {
    return "";
  }
}

function populateHistoryOptions(select, history) {
  select.innerHTML = "";

  const defaultOption = document.createElement("option");
  defaultOption.text = "View History...";
  defaultOption.value = "";
  select.appendChild(defaultOption);

  if (Array.isArray(history)) {
    history.forEach(h => {
      const opt = document.createElement("option");

      const name = `${h.FirstName || ""} ${h.LastName || ""}`.trim();
      const action = h.LastAction || "";
      const loc = h.Location || "";

      opt.text = `${name} | ${action} | ${loc}`;
      opt.value = JSON.stringify(h);

      select.appendChild(opt);
    });
  }
}

function buildLogRow(v) {
  const row = document.createElement("div");
  row.className = "log-row";
  row.dataset.id = v._id;

  const header = document.createElement("div");
  header.className = "log-row-header";
  row.appendChild(header);

  const select = document.createElement("select");
  select.className = "log-row-select";
  populateHistoryOptions(select, v.history);

  const detail = document.createElement("div");
  detail.className = "log-row-detail";

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

  row.appendChild(select);
  row.appendChild(detail);

  return row;
}

// Updates an existing row's header text and, if the log's history actually
// changed (e.g. the async backfill just populated it), its dropdown options.
// The select/detail nodes are otherwise left untouched so an open dropdown
// selection survives a background refresh.
function updateLogRow(row, v, majorityByCampaign) {
  const header = row.querySelector(".log-row-header");

  const html = `
    <b>${v.SerialNo || ""}</b>
    &nbsp;&nbsp;
    ${v.PartNo || ""}
    &nbsp;&nbsp;
    ${`${logLength(v, majorityByCampaign)} Inches`}
    <span class="log-row-time">
      ${new Date(getDate(v.timeMoved)).toLocaleTimeString()}
    </span>
  `;

  if (header.innerHTML !== html) header.innerHTML = html;

  const select = row.querySelector("select");
  const historyCount = Array.isArray(v.history) ? v.history.length : 0;

  if (select.options.length - 1 !== historyCount) {
    populateHistoryOptions(select, v.history);
  }
}

export function updateDashboard() {
  const entries = getSortedEntries();
  const shiftStart = getCurrentShiftStart();
  const majorityByCampaign = buildCampaignMajorityLengths(entries);

  const shiftCount = entries.filter(
    v => new Date(getDate(v.timeMoved)) >= shiftStart
  ).length;

  const shiftCountEl = document.getElementById("shiftCount");
  const shiftCountText = `Logs This Shift: ${shiftCount}`;
  if (shiftCountEl.textContent !== shiftCountText) shiftCountEl.textContent = shiftCountText;

  const recent = document.getElementById("recentLogs");
  const shiftEntries = entries.slice(0, shiftCount);

  const existing = new Map();
  recent.querySelectorAll(".log-row").forEach(el => existing.set(el.dataset.id, el));

  const seen = new Set();

  shiftEntries.forEach(v => {
    seen.add(v._id);

    let row = existing.get(v._id);

    if (!row) {
      row = buildLogRow(v);
    }

    updateLogRow(row, v, majorityByCampaign);

    // appendChild on an already-attached node moves it -- iterating entries
    // in order keeps DOM order correct without recreating untouched rows.
    recent.appendChild(row);
  });

  existing.forEach((row, id) => {
    if (!seen.has(id)) row.remove();
  });
}
