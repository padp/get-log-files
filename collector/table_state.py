"""
Reconciles the camera-based log count (log_count.py) against the furnace
PLC's queue state (furnace.py) into a single "confirmed" count of logs on
the Log Pusher table -- the two signals cover each other's blind spot:

- The camera sees deliveries onto the table, but any single frame can be
  wrong (background bleed, low contrast, etc.) -- log_count.py's confidence
  score exists precisely because no single reading should be trusted alone.
- The furnace PLC sees a log leave the table and enter its queue completely
  unambiguously, but has no visibility into the table itself.

Per the user (2026-08-13): logs move from table to furnace queue only every
15-30 minutes, so this doesn't need to resolve on every 60s camera cycle --
it can wait for the camera to reach *consensus* (several consecutive
high-confidence readings agreeing) before trusting a new count, while the
furnace signal supplies an unambiguous decrement independent of any of that.

This module also owns the lifecycle of the annotated snapshot images
(camera.py just saves each cycle's to ANNOTATED_DIR and hands over the
path): most get deleted within a cycle or two once they've dropped out of
the consensus window unused; only the ones that actually contributed to a
consensus, or coincided with a confirmed count change, get renamed with a
reason/count/confidence tag and kept (camera.py's longer
ANNOTATED_RETENTION_DAYS prune expires those eventually too).

State persists in Mongo (database.table_state, a single upserted document)
so it survives collector restarts; every time the confirmed count actually
changes, an audit row is appended to database.table_events recording why.
"""
import os
from datetime import datetime
from database import table_state as state_collection, table_events as events_collection
from furnace import read_furnace_state

_STATE_ID = "current"

# require this many consecutive camera readings to agree, all at or above
# this confidence, before trusting them enough to move the confirmed count
_CONSENSUS_WINDOW = 3
_CONSENSUS_MIN_CONFIDENCE = 0.85

# new logs load in at index 2 or higher (indices 0-1 are the actively
# depleting/next-up logs) -- see furnace.py
_NEW_LOG_MIN_INDEX = 2

# SUM_OF_ALL_LOG_LENGTHS only increases on a real load; a full log is ~240in
# but per the user, use a more sensitive bar than the full length so a
# smaller-than-expected jump still registers
_SUM_INCREASE_THRESHOLD = 165

# Minimum time between accepted furnace-decrements. Found live (2026-08-13):
# a single real load event's PLC values can cross our decrement threshold
# gradually across two consecutive ~60s polls rather than in one clean jump,
# which was double-counted as two separate decrements only 67s apart --
# physically impossible given logs move to the queue every 15-30 min. This
# cooldown is set well below that real cadence (leaves room for genuine
# back-to-back loads) but well above a single poll cycle, so a same-event
# double-trigger gets suppressed without risking missing a real one.
_DECREMENT_COOLDOWN_SECONDS = 300


def _get_state():
    doc = state_collection.find_one({"_id": _STATE_ID})
    if doc:
        return doc
    return {
        "_id": _STATE_ID,
        "confirmedCount": None,
        "lastFurnaceSum": None,
        "lastFurnaceSlots": None,
        "lastDecrementAt": None,
        "recentCameraReadings": [],  # [{path, count, confidence, kept}]
    }


def _save_state(state):
    state_collection.replace_one({"_id": _STATE_ID}, state, upsert=True)


def _log_event(reason, old_count, new_count, detail):
    events_collection.insert_one({
        "reason": reason,
        "oldCount": old_count,
        "newCount": new_count,
        "detail": detail,
        "recordedAt": datetime.utcnow(),
    })


def _delete_photo(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"[TABLE] Failed to delete unused annotated photo {path}: {e}")


def _tag_and_keep(entry, reason, confirmed_count=None):
    """Renames an annotated photo in place to mark why it was kept -- e.g.
    logpusher_20260813_071735.jpg -> logpusher_20260813_071735__consensus__count6__conf0.92.jpg
    -- so the user can filter the annotated directory by reason or count
    later without opening every file.

    confirmed_count is only meaningful (and only passed) for the
    furnace-decrement case: this photo's own camera reading (entry['count'])
    is NOT the same thing as the confirmed table count that resulted from
    the decrement -- it's just whatever the camera happened to see in that
    one frame, which can differ a lot (found live 2026-08-13: a filename
    read as "confirmed count dropped to 4" when it actually meant "the
    camera misread this one frame as 4"). Spelling out both avoids that
    confusion. For the consensus case entry['count'] already *is* the new
    confirmed count, so there's nothing ambiguous to add."""
    if entry.get("kept") or not entry.get("path") or not os.path.exists(entry["path"]):
        return

    directory, fname = os.path.split(entry["path"])
    stem, ext = os.path.splitext(fname)
    if confirmed_count is not None:
        new_name = f"{stem}__{reason}__confirmed{confirmed_count}__cameraSaw{entry['count']}__conf{entry['confidence']:.2f}{ext}"
    else:
        new_name = f"{stem}__{reason}__count{entry['count']}__conf{entry['confidence']:.2f}{ext}"
    new_path = os.path.join(directory, new_name)
    try:
        os.rename(entry["path"], new_path)
        entry["path"] = new_path
        entry["kept"] = True
    except Exception as e:
        print(f"[TABLE] Failed to tag/keep annotated photo {entry['path']}: {e}")


def _apply_furnace_state(state, furnace):
    slots = [furnace[f"LOG_FILE[{i}]"] for i in range(5)]
    total = furnace["SUM_OF_ALL_LOG_LENGTHS"]

    if state["lastFurnaceSum"] is None:
        # first read ever -- nothing to diff against yet, just establish
        # the baseline
        state["lastFurnaceSum"] = total
        state["lastFurnaceSlots"] = slots
        return

    sum_increase = total - state["lastFurnaceSum"]
    new_slot_filled = any(
        state["lastFurnaceSlots"][i] == 0 and slots[i] != 0
        for i in range(_NEW_LOG_MIN_INDEX, len(slots))
    )

    if new_slot_filled or sum_increase > _SUM_INCREASE_THRESHOLD:
        now = datetime.utcnow()
        last = state.get("lastDecrementAt")
        seconds_since_last = (now - last).total_seconds() if last else None

        if seconds_since_last is not None and seconds_since_last < _DECREMENT_COOLDOWN_SECONDS:
            # almost certainly the same real event crossing the threshold
            # across two consecutive polls rather than a second real load --
            # see _DECREMENT_COOLDOWN_SECONDS
            print(f"[TABLE] Suppressed furnace decrement -- only {seconds_since_last:.0f}s since the last one "
                  f"(cooldown is {_DECREMENT_COOLDOWN_SECONDS}s)")
        elif state["confirmedCount"] is not None and state["confirmedCount"] > 0:
            old = state["confirmedCount"]
            state["confirmedCount"] = old - 1
            state["lastDecrementAt"] = now
            detail = {"sumIncrease": sum_increase, "newSlotFilled": new_slot_filled, "slots": slots}
            _log_event("furnace_decrement", old, state["confirmedCount"], detail)
            print(f"[TABLE] Furnace decrement: {old} -> {state['confirmedCount']} ({detail})")

            # tag whatever the most recent camera photo was as evidence
            # alongside this change, even though the furnace -- not the
            # camera -- is what triggered it
            readings = state["recentCameraReadings"]
            if readings:
                _tag_and_keep(readings[-1], "furnace-decrement", confirmed_count=state["confirmedCount"])

            # Reset the consensus window (2026-08-13, per the user): once a
            # log is confirmed gone via the furnace, camera consensus should
            # never be able to push the count back up using readings taken
            # *before* the log actually left -- those still show the old,
            # larger pile and would otherwise look like a legitimate
            # "greater than current" consensus even though they're stale.
            # Only fresh readings taken after this point should be able to
            # count toward the next consensus.
            for entry in readings:
                if not entry.get("kept"):
                    _delete_photo(entry.get("path"))
            state["recentCameraReadings"] = []

    state["lastFurnaceSum"] = total
    state["lastFurnaceSlots"] = slots


def _apply_camera_result(state, camera_result, annotated_path):
    readings = state["recentCameraReadings"]
    readings.append({
        "path": annotated_path,
        "count": camera_result.count,
        "confidence": camera_result.confidence,
        "kept": False,
    })

    # anything sliding out of the window now was never part of a consensus
    # and never coincided with a furnace-triggered keep -- safe to delete
    overflow = len(readings) - _CONSENSUS_WINDOW
    if overflow > 0:
        for entry in readings[:overflow]:
            if not entry.get("kept"):
                _delete_photo(entry.get("path"))
        readings = readings[overflow:]

    state["recentCameraReadings"] = readings

    if len(readings) < _CONSENSUS_WINDOW:
        return

    counts = {r["count"] for r in readings}
    min_confidence = min(r["confidence"] for r in readings)

    if len(counts) == 1 and min_confidence >= _CONSENSUS_MIN_CONFIDENCE:
        consensus = next(iter(counts))
        old = state["confirmedCount"]

        # Per the user (2026-08-13): once a strong consensus is established,
        # the camera signal can only ever move the count *up* (a new
        # delivery, which the furnace can't see) -- it should never be able
        # to move it down. Decreases are the furnace's job exclusively,
        # since that's the only unambiguous signal for a log actually
        # leaving the table. A camera consensus below the current confirmed
        # count is far more likely a misread (background bleed, low
        # contrast) than a real decrease, and letting the furnace own all
        # decreases avoids exactly that failure mode.
        if old is None or consensus > old:
            state["confirmedCount"] = consensus
            _log_event("camera_consensus", old, consensus, {"readings": readings})
            print(f"[TABLE] Camera consensus: {old} -> {consensus}")

            for entry in readings:
                _tag_and_keep(entry, "consensus")
        elif consensus != old:
            print(f"[TABLE] Camera consensus ({consensus}) is not greater than confirmed count ({old}) -- ignored, decreases are the furnace's job")


def update_table_state(camera_result, annotated_path=None):
    """Runs one reconciliation cycle: folds in the latest camera reading
    (for consensus-based re-anchoring, and to manage that photo's lifecycle)
    and the latest furnace PLC state (for unambiguous decrements).
    Self-contained -- a furnace read failure (PLC offline, network hiccup)
    doesn't lose the camera-side update, and vice versa. Returns the current
    confirmed count (may be None if no consensus has been reached yet)."""
    state = _get_state()

    if camera_result is not None:
        _apply_camera_result(state, camera_result, annotated_path)

    try:
        furnace = read_furnace_state()
        _apply_furnace_state(state, furnace)
    except Exception as e:
        print(f"[TABLE] Furnace read failed: {e}")

    state["updatedAt"] = datetime.utcnow()
    _save_state(state)

    print(f"[TABLE] Confirmed count: {state['confirmedCount']}")
    return state["confirmedCount"]
