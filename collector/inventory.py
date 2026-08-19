from datetime import datetime
from pymongo import UpdateOne
from database import inventory as collection, log_bay_inventory
from plex import get_inventory_rows

def make_key(row):
    return f"{row.get('PartNo')}|{row.get('Location')}|{row.get('SerialNo')}"

def _bulk_upsert(rows, target_collection, now, set_on_insert, campaign=None):
    """Shared upsert-by-key shape: refresh lastSeen/clear missing markers on
    every poll, stamp caller-supplied $setOnInsert fields only on first
    sight, and reconcile items that dropped out of this cycle's rows via
    _mark_missing_items. Used for both the PAD-Extrusion SHARED poll
    (log_files) and the PAD-Log Bay poll (log_bay_inventory) -- same shape,
    different target collection and different first-seen bookkeeping."""

    if not rows:
        return None

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
                    "$setOnInsert": set_on_insert,
                },
                upsert=True
            )
        )

    result = target_collection.bulk_write(ops, ordered=False)

    _mark_missing_items(seen_ids, now, target_collection)

    return result


def upsert_inventory(rows, campaign=None):
    now = datetime.utcnow()
    return _bulk_upsert(
        rows, collection, now, campaign=campaign,
        set_on_insert={
            "timeMoved": now,
            "historyLoaded": False,
            "historyLoadedAt": None,
            "historyAttempts": 0,
            "historyLastAttempt": None,
        },
    )


def upsert_log_bay_inventory(rows):
    """Same shape as upsert_inventory, scoped to PAD-Log Bay staging
    material instead of PAD-Extrusion SHARED. Deliberately no campaign
    tagging (Log Bay is polled in full regardless of the active job) and no
    history-queue bookkeeping (candidates only need "how long has this
    serial been sitting here", which firstSeenAt already answers -- not a
    full Plex container-history backfill). Named firstSeenAt rather than
    timeMoved specifically so it can't be confused with that field's
    different, already-established meaning over in log_files."""
    now = datetime.utcnow()
    return _bulk_upsert(
        rows, log_bay_inventory, now,
        set_on_insert={"firstSeenAt": now},
    )


def poll_log_bay_inventory():
    rows = get_inventory_rows(location="PAD-Log Bay")
    return upsert_log_bay_inventory(rows)


def _mark_missing_items(seen_ids, now, target_collection):
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
    target_collection.update_many(
        {
            "_id": {"$nin": seen_ids},
            "missingSince": {"$ne": None},
            "removedAt": None,
        },
        [{"$set": {"removedAt": "$missingSince"}}]
    )

    # missing for the first time -- record it, don't confirm yet
    target_collection.update_many(
        {
            "_id": {"$nin": seen_ids},
            "missingSince": None,
            "removedAt": None,
        },
        {"$set": {"missingSince": now}}
    )
