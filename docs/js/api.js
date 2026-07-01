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
