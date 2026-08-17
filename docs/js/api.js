export const API_BASE = "https://get-log-files.onrender.com";

export async function fetchInventory() {
  const response = await fetch(`${API_BASE}/api/inventory`);
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return JSON.parse(text);
}

export async function fetchCampaigns() {
  const response = await fetch(`${API_BASE}/api/campaigns`);
  return response.json();
}

export async function fetchCampaignDetails(campaignId) {
  const response = await fetch(`${API_BASE}/api/campaigns/${campaignId}`);
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return JSON.parse(text);
}

export async function fetchScheduleStatus() {
  const response = await fetch(`${API_BASE}/api/schedule-status`);

  // 404 means the collector hasn't produced a status doc yet -- a normal,
  // expected state (not deployed yet, or hasn't matched a job this cycle),
  // not an error worth throwing over.
  if (response.status === 404) return null;

  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return JSON.parse(text);
}

export async function fetchTableState() {
  const response = await fetch(`${API_BASE}/api/table-state`);

  // 404 means table_state.py hasn't reached a confirmed count yet (e.g. no
  // camera consensus since the collector last started) -- normal, not an error.
  if (response.status === 404) return null;

  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return JSON.parse(text);
}

export async function fetchTableStateEvents() {
  const response = await fetch(`${API_BASE}/api/table-state/events`);

  // 404 isn't actually possible here (the route always returns a list,
  // even an empty one) -- kept only for symmetry/defensiveness with the
  // other table-state fetchers if that ever changes
  if (response.status === 404) return [];

  const text = await response.text();

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${text}`);
  }

  return JSON.parse(text);
}

export function tableStateImageUrl() {
  // cache-busted so the <img> actually refetches each time the panel opens
  // rather than showing a stale browser-cached photo
  return `${API_BASE}/api/table-state/image?t=${Date.now()}`;
}

export async function submitTableStateOverride({ count, username, password, reason }) {
  const response = await fetch(`${API_BASE}/api/table-state/override`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count, username, password, reason }),
  });

  const text = await response.text();

  if (!response.ok) {
    let message = text;
    try {
      message = JSON.parse(text).error || text;
    } catch {
      // not JSON -- fall back to the raw text
    }
    throw new Error(message);
  }

  return JSON.parse(text);
}
