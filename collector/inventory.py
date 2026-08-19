from datetime import datetime
from pymongo import UpdateOne
from database import inventory as collection

def make_key(row):
    return f"{row.get('PartNo')}|{row.get('Location')}|{row.get('SerialNo')}"

def upsert_inventory(rows, campaign=None):

    if not rows:
        return None

    now = datetime.utcnow()

    ops = []
    seen_ids = []

    for row in rows:

        key = make_key(row)
        seen_ids.append(key)

        if campaign:
            row["campaign"] = campaign

        ops.append(
            UpdateOne(
                {"_id": key},
                {
                    "$set": {
                        **row,
                        "lastSeen": now,
                        "missingSince": None,
                        "removedAt": None,
                    },
                    "$setOnInsert": {
                        "timeMoved": now,
                        "historyLoaded": False,
                        "historyLoadedAt": None,
                        "historyAttempts": 0,
                        "historyLastAttempt": None
                    }
                },
                upsert=True
            )
        )

    result = collection.bulk_write(ops, ordered=False)

    _mark_missing_items(seen_ids, now)

    return result


def _mark_missing_items(seen_ids, now):
    """
    Flags items that have dropped out of the polled location -- e.g. moved
    elsewhere by mistake, or genuinely consumed at the press. Requires TWO
    consecutive misses before confirming removedAt, so a single flaky or
    partial Plex response can't wrongly flag a batch of items that are
    actually still there. Reappearing (matched in upsert_inventory's own
    $set above) clears both fields.
    """

    # already missing last cycle and still missing now -- confirm removal,
    # preserving the original first-missing timestamp
    collection.update_many(
        {
            "_id": {"$nin": seen_ids},
            "missingSince": {"$ne": None},
            "removedAt": None,
        },
        [{"$set": {"removedAt": "$missingSince"}}]
    )

    # missing for the first time -- record it, don't confirm yet
    collection.update_many(
        {
            "_id": {"$nin": seen_ids},
            "missingSince": None,
            "removedAt": None,
        },
        {"$set": {"missingSince": now}}
    )
