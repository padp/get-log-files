from datetime import datetime
from database import billets, schedule_status
from press import get_press_state
from schedule import predict_billets_until_alloy_change


def _estimate_cadence_seconds(lookback=10):
    """Average seconds-per-billet from the most recent billet_log entries."""

    recent = list(billets.find({}).sort("recordedAt", -1).limit(lookback))

    if len(recent) < 2:
        return None

    recent.sort(key=lambda d: d["recordedAt"])
    span = (recent[-1]["recordedAt"] - recent[0]["recordedAt"]).total_seconds()
    intervals = len(recent) - 1

    if span <= 0:
        return None

    return span / intervals


def update_schedule_status():
    """
    Reads the live press snapshot, predicts how many billets remain before
    the next alloy change (via the operator schedule on the network share),
    and upserts a single "current" status document -- this runs on the
    press-adjacent PC where the schedule share is actually mounted, so the
    result gets persisted to Mongo for the API (which has no access to that
    share) to read.
    """

    data = get_press_state()

    if not data:
        return

    snapshot = data[0]
    job_number = snapshot.get("Job Number (#)")
    billet_number = snapshot.get("Billet Number (per Order)")

    if not job_number or billet_number is None:
        return

    try:
        job_number = int(job_number)
    except (TypeError, ValueError):
        return

    try:
        prediction = predict_billets_until_alloy_change(job_number, billet_number)
    except Exception as e:
        print(f"[SCHEDULE] Failed to read press schedule: {e}")
        return

    if prediction is None:
        return

    cadence = _estimate_cadence_seconds()
    eta_seconds = prediction["billetsRemaining"] * cadence if cadence else None

    schedule_status.replace_one(
        {"_id": "current"},
        {
            "_id": "current",
            "jobNumber": job_number,
            "billetsRemaining": prediction["billetsRemaining"],
            "jobsRemaining": prediction["jobsRemaining"],
            "alloy": prediction["alloy"],
            "etaSeconds": eta_seconds,
            "updatedAt": datetime.utcnow(),
        },
        upsert=True,
    )
