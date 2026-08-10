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

export async function fetchScannerHealth() {
  const response = await fetch(`${API_BASE}/api/scanner-health`);
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
