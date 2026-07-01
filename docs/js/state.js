import { getDate } from "./dateUtils.js";

export const state = {
  jsonData: [],
  campaigns: [],
  selectedId: null,
  selectedCampaignId: null,
};

export function getSortedEntries() {
  return [...state.jsonData].sort(
    (a, b) => new Date(getDate(b.timeMoved)) - new Date(getDate(a.timeMoved))
  );
}
