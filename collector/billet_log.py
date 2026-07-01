from datetime import datetime
from database import billets as collection
from press import get_press_state, ALLOY_MAP


def _extract_state(doc):
    return {
        "alloy": doc.get("Alloy"),
        "billetNumberPerOrder": doc.get("Billet Number (per Order)"),
        "billetNumberPerDie": doc.get("Billet Number (per Die)"),
        "jobNumber": doc.get("Job Number (#)"),
        "billetLengthActual": doc.get("Billet Length Actual (in)"),
        "billetLengthSetpoint": doc.get("Billet Length Setpoint (in)"),
        "scheduledBillets": doc.get("Scheduled Billets"),
        "fceLogFileAlloy": doc.get("FCE Log File Alloy"),
        "fceCurrentLogLengthRemaining": doc.get("FCE Current Log Length Remaining (in)"),
        "fceSumAllLoadedLogs": doc.get("FCE Sum All Loaded Logs (in)"),
        "fceBilletLength": doc.get("FCE Billet Length (in)"),
        "sourceDateTime": doc.get("Date/Time"),
    }


def record_billet_state():
    """
    Polls the press snapshot and appends a row to billet_log only when the
    alloy or billet number has changed since the last recorded entry.
    press_data only ever holds current state (no history), so this is what
    builds a queryable, append-only ledger of what was actually run --
    the source data collector.py's 60s loop already polls fast enough for,
    since no part takes less than 60s per billet.
    """

    data = get_press_state()

    if not data:
        return

    state = _extract_state(data[0])

    if state["alloy"] is None:
        return

    last = collection.find_one(sort=[("recordedAt", -1)])

    if (
        last
        and last.get("alloy") == state["alloy"]
        and last.get("billetNumberPerOrder") == state["billetNumberPerOrder"]
    ):
        return  # no new billet since the last check

    collection.insert_one({
        **state,
        "alloyName": ALLOY_MAP.get(state["alloy"], state["alloy"]),
        "recordedAt": datetime.utcnow(),
    })
