
let jsonData = [];
let selectedDiv = null;

const API_BASE = "https://get-log-files.onrender.com";

//--------------------------------------------------
// Load data
//--------------------------------------------------
async function loadData() {

  try {

    const response = await fetch(`${API_BASE}/api/inventory`);
    jsonData = await response.json();

    renderKeys();
    updateDashboard();

  } catch (err) {
    console.error("Load error:", err);
  }
}

//--------------------------------------------------
// Sort
//--------------------------------------------------
function getSortedEntries() {
  return [...jsonData].sort((a, b) =>
    new Date(b.timeMoved.$date) - new Date(a.timeMoved.$date)
  );
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
          ${new Date(row.timeMoved.$date).toLocaleString()}
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

  const s1 = new Date(now); s1.setHours(7,0,0,0);
  const s2 = new Date(now); s2.setHours(15,0,0,0);
  const s3 = new Date(now); s3.setHours(23,0,0,0);

  if (now >= s3) return s3;
  if (now >= s2) return s2;
  if (now >= s1) return s1;

  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  y.setHours(23,0,0,0);

  return y;
}

//--------------------------------------------------
// Dashboard
//--------------------------------------------------
function updateDashboard() {

  const entries = getSortedEntries();
  const shiftStart = getCurrentShiftStart();

  const shiftCount = entries.filter(v =>
    new Date(v.timeMoved.$date) >= shiftStart
  ).length;

  document.getElementById("shiftCount").textContent =
    `Logs This Shift: ${shiftCount}`;

  const recent = document.getElementById("recentLogs");
  recent.innerHTML = "";

  entries.slice(0, 12).forEach(v => {

    const row = document.createElement("div");
    row.style.padding = "4px";
    row.style.borderBottom = "1px solid #eee";

    row.innerHTML = `
      <b>${v.SerialNo || ""}</b>
      &nbsp;&nbsp;
      ${v.PartNo || ""}
      <span style="float:right;color:#666;">
        ${new Date(v.timeMoved.$date).toLocaleTimeString()}
      </span>
    `;

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
    <b>Time Moved:</b> ${new Date(obj.timeMoved.$date).toLocaleString()}
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
