"""
Pure gap-detection logic for the delivered-vs-moved reconciliation, kept
deliberately free of Flask (no `request`, no `dumps`) so a future
notification channel (SMS/email) can import and poll compute_gap_status /
get_gap_status directly, on its own cadence, without duplicating the
timeline-replay algorithm or depending on a running Flask app. Dashboard-
only for now -- api/app.py's /api/table-state/reconciliation route is the
only current caller -- but this module's shape is what keeps that door
open rather than boxing it out.

Validated 2026-08-18 against a real 20-hour production sample (58
delivered, 59 moved, one genuine gap-opening incident that stayed open
17.5 minutes before closing on its own). GAP_ALERT_THRESHOLD_MINUTES is
set with a comfortable margin above that observed worst case, not an
arbitrary guess.
"""
from datetime import datetime, timedelta

GAP_ALERT_THRESHOLD_MINUTES = 30

# Deliberately decoupled from the display "since" window callers use for
# the aggregate delivered/moved/netDifference numbers (shift-scoped, or an
# arbitrary ?hours=). If a gap genuinely opened before that boundary,
# replaying only from "since" would understate -- or miss entirely -- how
# long it's actually been open. Real gaps close within tens of minutes per
# validated data (worst case seen: 17.5 min), so a generous, independent
# lookback comfortably covers any real gap regardless of where the display
# window happens to start.
GAP_LOOKBACK_HOURS = 4


def compute_gap_status(delivered_events, moved_timestamps, now=None,
                        alert_threshold_minutes=GAP_ALERT_THRESHOLD_MINUTES):
    """Replays delivered-vs-moved as one merged, time-ordered timeline and
    finds the start of the CURRENTLY open gap (delivered running ahead of
    moved), if any -- the same replay the 20-hour dataset was manually
    checked against before this threshold was chosen.

    delivered_events: iterable of {"recordedAt": datetime, "delta": int}
    moved_timestamps: iterable of datetime (one per Plex move)
    now: injectable for testability, defaults to datetime.utcnow()

    Returns {"gapOpenSince", "gapOpenMinutes", "gapAlert", "netDifference"}.
    """
    now = now or datetime.utcnow()

    timeline = (
        [(e["recordedAt"], "deliver", e["delta"]) for e in delivered_events]
        + [(ts, "move", 1) for ts in moved_timestamps]
    )
    timeline.sort(key=lambda t: t[0])

    delivered_total = 0
    moved_total = 0
    gap_open_since = None

    for ts, kind, qty in timeline:
        if kind == "deliver":
            delivered_total += qty
        else:
            moved_total += qty

        diff = delivered_total - moved_total
        if diff > 0 and gap_open_since is None:
            gap_open_since = ts
        elif diff <= 0:
            gap_open_since = None

    gap_open_minutes = None
    gap_alert = False
    if gap_open_since is not None:
        gap_open_minutes = (now - gap_open_since).total_seconds() / 60
        gap_alert = gap_open_minutes >= alert_threshold_minutes

    return {
        "gapOpenSince": gap_open_since,
        "gapOpenMinutes": round(gap_open_minutes, 1) if gap_open_minutes is not None else None,
        "gapAlert": gap_alert,
        "netDifference": delivered_total - moved_total,
    }


def get_gap_status(lf_collection, table_events_collection, now=None):
    """Thin Mongo-fetching wrapper around compute_gap_status -- takes
    plain collection handles (not app.py's globals) so this stays callable
    from any process with a Mongo connection, not just the Flask app."""
    now = now or datetime.utcnow()
    since = now - timedelta(hours=GAP_LOOKBACK_HOURS)

    delivered_docs = table_events_collection.find(
        {"$expr": {"$gt": ["$newCount", {"$ifNull": ["$oldCount", -1]}]}, "recordedAt": {"$gte": since}}
    )
    delivered_events = [
        {"recordedAt": d["recordedAt"], "delta": d.get("newCount", 0) - (d.get("oldCount") or 0)}
        for d in delivered_docs
    ]

    moved_timestamps = [
        d["timeMoved"] for d in lf_collection.find({"timeMoved": {"$gte": since}}, {"timeMoved": 1})
    ]

    return compute_gap_status(delivered_events, moved_timestamps, now=now)
