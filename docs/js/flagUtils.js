// A record is flagged red only once we're CONFIDENT it left PAD-Extrusion
// SHARED without being run at the press -- not just because it's gone from
// current inventory, since that's also the normal, expected end of nearly
// every log's life (consumed at the press). Holding off until history has
// loaded avoids a premature wrong verdict on freshly-departed items.
export function isFlaggedRemoval(record) {
  if (!record || !record.removedAt || !record.historyLoaded) return false;

  const action = ((record.lastMove && record.lastMove.Action) || "").toLowerCase();
  const isNormalDepletion = action.includes("depleted") || action.includes("retired");

  return !isNormalDepletion;
}
