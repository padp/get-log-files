from flask import Flask, request, Response
from flask_cors import CORS
from pymongo import MongoClient
from bson.json_util import dumps
from bson import ObjectId
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os

from reconciliation import get_gap_status

# The plant (Paducah, KY) runs on Central time -- shift boundaries below are
# plant-local, not UTC. This API runs on Render, whose server clock is not
# guaranteed to be plant-local (unlike the collector, which runs on-site and
# can just use datetime.now()), so the conversion has to be explicit here.
PLANT_TZ = ZoneInfo("America/Chicago")

app = Flask(__name__)

CORS(
    app,
    origins=[
        "https://padp.github.io",
        "http://localhost:8080"
    ]
)

# ============================================================
# Mongo Connection (Render ENV VAR)
# ============================================================

SQL_PASS = os.environ.get("SQL_PASS")

# Bounds worst-case latency on every Mongo call this app makes (default is
# 30s) -- matters more now that create_index below runs at import time and
# would otherwise hang a cold start for the full default timeout if Mongo
# happens to be slow to respond right then.
client = MongoClient(
    f"mongodb+srv://padpress1:{SQL_PASS}@cluster0.ywwxl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0",
    serverSelectionTimeoutMS=5000)

db = client["log_files"]

lf_collection = db["log_files"]

alloy_change_collection = db["campaigns"]

billet_collection = db["billet_log"]

schedule_status_collection = db["schedule_status"]

table_state_collection = db["table_state"]

table_events_collection = db["table_events"]

table_state_image_collection = db["table_state_image"]

# No index existed on timeMoved before this -- every sort/filter on it
# (the inventory list, the dashboard shift query, scanner-health's
# most-recent lookup) was a full collection scan, and the collection only
# ever grows (removed items are marked, never deleted). create_index is a
# no-op if it already exists, so safe to call on every app startup rather
# than needing a one-time manual step -- guarded so a transient Mongo
# hiccup at cold start delays startup by at most the timeout above instead
# of crashing the whole app.
try:
    lf_collection.create_index([("timeMoved", -1)])
except Exception as e:
    print(f"[STARTUP] Could not ensure timeMoved index (will retry next deploy/restart): {e}")

# Shared supervisory-override credential, not a real per-user login --
# matches this app's existing security posture (nothing else here is
# authenticated either), just enough to keep the write path from being
# wide open to anyone who finds the URL. Set on Render, never hardcoded.
OVERRIDE_USERNAME = os.environ.get("OVERRIDE_USERNAME")
OVERRIDE_PASSWORD = os.environ.get("OVERRIDE_PASSWORD")

# ============================================================
# Helper: shift start logic (same as your JS)
# ============================================================


def get_shift_start(now=None):
    """
    Returns the current shift's start as a naive UTC datetime, matching how
    timeMoved is stored (datetime.utcnow(), no tzinfo) so it can be compared
    directly in a Mongo query. The 7/15/23 boundaries are evaluated in plant
    local time -- doing this in UTC directly (the bug this replaced) puts
    the boundaries at 1am/9am/5pm Central, hours away from the real shift
    changes.
    """

    now_utc = (now or datetime.utcnow()).replace(tzinfo=timezone.utc)
    local_now = now_utc.astimezone(PLANT_TZ)

    shift1 = local_now.replace(hour=7, minute=0, second=0, microsecond=0)
    shift2 = local_now.replace(hour=15, minute=0, second=0, microsecond=0)
    shift3 = local_now.replace(hour=23, minute=0, second=0, microsecond=0)

    if local_now >= shift3:
        shift_start_local = shift3
    elif local_now >= shift2:
        shift_start_local = shift2
    elif local_now >= shift1:
        shift_start_local = shift1
    else:
        shift_start_local = shift3 - timedelta(days=1)

    return shift_start_local.astimezone(timezone.utc).replace(tzinfo=None)


# ============================================================
# API: inventory list (optionally filtered)
# ============================================================

_INVENTORY_DEFAULT_LIMIT = 100
_INVENTORY_MAX_LIMIT = 500


@app.route("/api/inventory", methods=["GET"])
def inventory():

    q = request.args.get("q", "").strip()

    query = {}

    if q:
        query = {
            "$or": [
                {"_id": {"$regex": q, "$options": "i"}},
                {"PartNo": {"$regex": q, "$options": "i"}},
                {"SerialNo": {"$regex": q, "$options": "i"}},
                {"Location": {"$regex": q, "$options": "i"}},
            ]
        }

    # The collection only ever grows (removed items are marked, never
    # deleted) -- paginate rather than shipping the whole thing every load.
    # Search (q) runs server-side against the same page window, so the
    # frontend never needs the full collection just to filter it client-side.
    limit = min(int(request.args.get("limit", _INVENTORY_DEFAULT_LIMIT) or _INVENTORY_DEFAULT_LIMIT), _INVENTORY_MAX_LIMIT)
    skip = max(int(request.args.get("skip", 0) or 0), 0)

    total = lf_collection.count_documents(query)

    # history is a per-item, ever-growing array of every Plex move that
    # item has ever made -- the list/search view doesn't use it (the
    # "moved without being run" flag only needs the separate, small
    # lastMove/historyLoaded fields, both still included below), and it's
    # by far the largest thing on some records. Full history is still
    # available via /api/inventory/<item_id> when a record is opened.
    docs = list(
        lf_collection.find(query, {"history": 0}).sort("timeMoved", -1).skip(skip).limit(limit)
    )

    return dumps({"total": total, "limit": limit, "skip": skip, "rows": docs})


# ============================================================
# API: single record
# ============================================================

@app.route("/api/inventory/<path:item_id>", methods=["GET"])
def inventory_item(item_id):

    doc = lf_collection.find_one({"_id": item_id})

    return dumps(doc)


# ============================================================
# API: dashboard summary
# ============================================================

@app.route("/api/dashboard", methods=["GET"])
def dashboard():
    """
    Everything the dashboard's shift-count and Log Details panels need,
    scoped to just the current shift -- a small, bounded set (a shift's
    worth of deliveries, not the whole ever-growing collection), so unlike
    /api/inventory this intentionally does NOT strip history: Log Details'
    per-log "View History" dropdown needs it, and the set is small enough
    that it's cheap to include here.
    """

    now = datetime.utcnow()
    shift_start = get_shift_start(now)

    shift_entries = list(
        lf_collection.find({"timeMoved": {"$gte": shift_start}}).sort("timeMoved", -1)
    )

    return dumps({
        "shiftCount": len(shift_entries),
        "shiftEntries": shift_entries,
    })


# ============================================================
# API: scanner health
# ============================================================

# How long inventory can go with no new arrivals -- WHILE the press keeps
# running billets -- before we flag a likely barcode-scanner dropout.
# Tune this once there's a feel for what a normal gap looks like; it's the
# one knob that trades false alarms against missed outages.
SCANNER_GAP_THRESHOLD = timedelta(hours=1)


@app.route("/api/scanner-health", methods=["GET"])
def scanner_health():
    """
    log_files.timeMoved marks when a log was actually scanned into
    PAD-Extrusion SHARED; billet_log marks when the press actually consumed
    one. If the press keeps consuming billets while no new log has been
    scanned in for a while, that's the signature of the scanner losing
    connection -- production keeps going, but nothing new is being logged
    as arrived, which is exactly what causes the inventory discrepancies
    this project exists to catch.
    """

    last_log = lf_collection.find_one({}, sort=[("timeMoved", -1)])
    last_billet = billet_collection.find_one({}, sort=[("recordedAt", -1)])

    now = datetime.utcnow()
    last_log_time = last_log["timeMoved"] if last_log else None
    last_billet_time = last_billet["recordedAt"] if last_billet else None

    gap = (now - last_log_time) if last_log_time else None

    billets_since_last_log = 0
    if last_log_time:
        billets_since_last_log = billet_collection.count_documents({
            "recordedAt": {"$gt": last_log_time}
        })

    press_running_during_gap = billets_since_last_log > 0

    likely_issue = bool(
        gap and gap > SCANNER_GAP_THRESHOLD and press_running_during_gap
    )

    return dumps({
        "lastLogArrival": last_log_time,
        "lastBilletActivity": last_billet_time,
        "gapMinutes": round(gap.total_seconds() / 60, 1) if gap else None,
        "billetsSinceLastLog": billets_since_last_log,
        "likelyScannerIssue": likely_issue,
    })


# ============================================================
# API: schedule status
# ============================================================

@app.route("/api/schedule-status", methods=["GET"])
def schedule_status():
    """
    schedule_status.py computes this on the collector's PC (the only place
    with the schedule share mounted) and upserts a single "current" doc --
    this just reads it back for the frontend.
    """

    doc = schedule_status_collection.find_one({"_id": "current"})

    if doc is None:
        return {"error": "No schedule status available yet"}, 404

    return dumps(doc)


# ============================================================
# API: table state (log table count)
# ============================================================

@app.route("/api/table-state", methods=["GET"])
def table_state():
    """
    table_state.py reconciles the camera count and the furnace PLC signal
    into a single confirmed count on the collector's PC and upserts a single
    "current" doc -- this just reads it back for the frontend, same pattern
    as /api/schedule-status.
    """

    doc = table_state_collection.find_one({"_id": "current"})

    if doc is None:
        return {"error": "No table state available yet"}, 404

    # recentCameraReadings/lastFurnaceSlots etc. are internal reconciliation
    # bookkeeping (including local file paths on the collector PC) -- only
    # the confirmed count and its freshness are meaningful to the frontend
    return dumps({
        "confirmedCount": doc.get("confirmedCount"),
        "updatedAt": doc.get("updatedAt"),
    })


@app.route("/api/table-state/events", methods=["GET"])
def table_state_events():
    """
    Every confirmedCount change (camera consensus, furnace decrement, manual
    override) is already logged to table_events -- this surfaces just the
    increases, i.e. actual log deliveries to the table, timestamped.

    This used to also cross-check each event against a tight time window
    around log_files.timeMoved and flag ones with nothing nearby -- dropped
    (2026-08-17) because it was the wrong tool: a delivery's recordedAt is
    when 3 consecutive camera readings finally agreed, not when the log
    arrived, and that can trail the real delivery by a lot more than any
    reasonable window (every furnace decrement wipes the reading window and
    forces consensus to rebuild from scratch; before the confidence-formula
    fix, deliveries at counts <=6 couldn't reach consensus at all until
    something else nudged the count higher). Comparing individual event
    *timing* was fundamentally unreliable -- see /api/table-state/reconciliation
    for the aggregate-count comparison that replaced it.

    oldCount=None (the very first consensus ever reached) counts as an
    increase too via $ifNull, since there's no prior count to compare
    against but logs still showed up. Internal bookkeeping (e.g. camera
    consensus's raw reading detail, which includes collector-PC file paths)
    is dropped -- only what's meaningful here is returned.
    """

    limit = min(int(request.args.get("limit", 50)), 200)

    docs = list(table_events_collection.find(
        {"$expr": {"$gt": ["$newCount", {"$ifNull": ["$oldCount", -1]}]}}
    ).sort("recordedAt", -1).limit(limit))

    events = [
        {
            "recordedAt": d.get("recordedAt"),
            "oldCount": d.get("oldCount"),
            "newCount": d.get("newCount"),
            "delta": d.get("newCount", 0) - (d.get("oldCount") or 0),
            "reason": d.get("reason"),
        }
        for d in docs
    ]

    return dumps(events)


@app.route("/api/table-state/reconciliation", methods=["GET"])
def table_state_reconciliation():
    """
    The actual question this whole feature exists to answer: over the same
    period, has the same number of logs been delivered to the table (per
    the camera/table_state, summed across every confirmedCount increase --
    camera consensus and manual override alike, since a supervisor override
    upward is itself evidence of a real delivery the camera couldn't
    confirm on its own) as have been moved in Plex at PAD-Extrusion SHARED
    (log_files.timeMoved, i.e. scanned in by the material handler)? This
    deliberately does NOT try to pair up individual events by timing -- see
    the docstring on /api/table-state/events for why that's unreliable. A
    nonzero netDifference (delivered > moved) means logs are physically
    arriving without a matching Plex move catching up, over the period as a
    whole -- the actual traceability gap, tracked as a running total instead
    of a fragile per-event match.

    Defaults to the current shift (same boundary get_shift_start uses for
    /api/dashboard's "Logs loaded this shift", so the two numbers are
    directly comparable) -- pass ?hours=N for a rolling window instead, e.g.
    to look at a longer trend.
    """

    hours_param = request.args.get("hours")
    if hours_param is not None:
        hours = min(float(hours_param), 24 * 30)
        since = datetime.utcnow() - timedelta(hours=hours)
    else:
        since = get_shift_start(datetime.utcnow())
        hours = None

    delivered_docs = table_events_collection.find(
        {"$expr": {"$gt": ["$newCount", {"$ifNull": ["$oldCount", -1]}]}, "recordedAt": {"$gte": since}}
    )
    delivered = sum(
        d.get("newCount", 0) - (d.get("oldCount") or 0) for d in delivered_docs
    )

    moved = lf_collection.count_documents({"timeMoved": {"$gte": since}})

    gap_status = get_gap_status(lf_collection, table_events_collection)

    return dumps({
        "sinceHours": hours,
        "since": since,
        "delivered": delivered,
        "moved": moved,
        "netDifference": delivered - moved,
        "gapOpenSince": gap_status["gapOpenSince"],
        "gapOpenMinutes": gap_status["gapOpenMinutes"],
        "gapAlert": gap_status["gapAlert"],
    })


@app.route("/api/table-state/nearby-moves", methods=["GET"])
def table_state_nearby_moves():
    """
    Manual per-event drill-down: given one delivery event's recordedAt (and,
    optionally, its delta -- how many logs that event added), what Plex
    moves (log_files.timeMoved) happened around it?

    Plex moves land in clean batches at an identical timeMoved (one
    material-handler scan = one batch, confirmed on real data -- see
    api/reconciliation.py's module docstring). So rather than dumping every
    move in a wide window, this groups them into those batches and, when
    delta is given, scores each batch by (a) how closely its size matches
    delta and (b) how close in time it is to the delivery -- size match
    first, time as the tiebreaker, since "how many logs were moved" is the
    direct question being asked ("find the amount that were loaded at that
    time"). The best-scoring batch is returned as bestFit.

    Still deliberately NOT an automated assertion -- /api/table-state/events'
    docstring already covers why per-event timing is unreliable (a
    delivery's recordedAt is when consensus finally agreed, not when the
    log arrived, and that lag is unpredictable). bestFit is a best-effort
    suggestion for a human to sanity-check, not a claim of certainty --
    the full batch list is still returned alongside it for that reason.
    Window defaults wide and skewed backward (beforeMinutes > afterMinutes)
    since the real Plex move is more likely to have happened before a
    laggy consensus timestamp than after it.
    """

    time_param = request.args.get("time")
    if not time_param:
        return {"error": "time is required (ISO 8601)"}, 400

    try:
        center = datetime.fromisoformat(time_param.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return {"error": "time must be a valid ISO 8601 timestamp"}, 400

    delta_param = request.args.get("delta")
    delta = None
    if delta_param is not None:
        try:
            delta = int(delta_param)
        except ValueError:
            return {"error": "delta must be an integer"}, 400

    before_minutes = min(float(request.args.get("beforeMinutes", 60)), 24 * 60)
    after_minutes = min(float(request.args.get("afterMinutes", 15)), 24 * 60)

    window_start = center - timedelta(minutes=before_minutes)
    window_end = center + timedelta(minutes=after_minutes)

    docs = list(
        lf_collection.find(
            {"timeMoved": {"$gte": window_start, "$lte": window_end}},
            {"SerialNo": 1, "PartNo": 1, "timeMoved": 1},
        ).sort("timeMoved", 1)
    )

    batches_by_time = {}
    for d in docs:
        ts = d["timeMoved"]
        batches_by_time.setdefault(ts, []).append(
            {"serialNo": d.get("SerialNo"), "partNo": d.get("PartNo")}
        )

    batches = [
        {"timeMoved": ts, "count": len(serials), "serials": serials}
        for ts, serials in sorted(batches_by_time.items())
    ]

    best_fit = None
    if batches:
        if delta is not None:
            def score(b):
                size_diff = abs(b["count"] - delta)
                time_diff = abs((b["timeMoved"] - center).total_seconds())
                return (size_diff, time_diff)
            best_fit = min(batches, key=score)
        else:
            # no delta given -- fall back to simple closest-in-time
            best_fit = min(batches, key=lambda b: abs((b["timeMoved"] - center).total_seconds()))

    return dumps({
        "windowStart": window_start,
        "windowEnd": window_end,
        "bestFit": best_fit,
        "batches": batches,
    })


@app.route("/api/table-state/image", methods=["GET"])
def table_state_image():
    """
    table_state.py mirrors the most recent annotated camera snapshot into
    Mongo every reconciliation cycle specifically so this can serve it --
    the collector PC itself isn't reachable from outside the plant network,
    so this is the only way the dashboard's supervisory panel can show a
    supervisor what the camera actually saw.
    """

    doc = table_state_image_collection.find_one({"_id": "current"})

    if doc is None or not doc.get("image"):
        return {"error": "No table snapshot available yet"}, 404

    return Response(bytes(doc["image"]), mimetype="image/jpeg")


@app.route("/api/table-state/override", methods=["POST"])
def table_state_override():
    """
    Manual supervisory correction of confirmedCount -- exists because the
    camera/furnace reconciliation can get wedged (e.g. a delivery the camera
    saw clearly but couldn't reach consensus confidence on, while nothing
    ever gave the furnace side a reason to move) with no automatic way back
    to the true count. Gated by a shared passcode (not real per-user auth,
    same security posture as the rest of this app) and always logged to
    table_events with who/why, same as every other confirmedCount change.
    """

    if not OVERRIDE_USERNAME or not OVERRIDE_PASSWORD:
        return {"error": "Manual override is not configured on the server"}, 503

    body = request.get_json(silent=True) or {}

    username = body.get("username", "")
    password = body.get("password", "")

    if username != OVERRIDE_USERNAME or password != OVERRIDE_PASSWORD:
        return {"error": "Invalid username or password"}, 401

    count = body.get("count")

    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return {"error": "count must be a non-negative integer"}, 400

    reason = (body.get("reason") or "").strip()

    doc = table_state_collection.find_one({"_id": "current"})
    old_count = doc.get("confirmedCount") if doc else None

    now = datetime.utcnow()

    # Clear recentCameraReadings so stale pre-override readings can't
    # immediately look like a "greater than current" consensus and fight
    # the correction -- same reasoning as the furnace-decrement reset in
    # table_state.py, only fresh readings taken after this point should
    # count toward the next one.
    table_state_collection.update_one(
        {"_id": "current"},
        {
            "$set": {
                "confirmedCount": count,
                "updatedAt": now,
                "recentCameraReadings": [],
            }
        },
        upsert=True,
    )

    table_events_collection.insert_one({
        "reason": "manual_override",
        "oldCount": old_count,
        "newCount": count,
        "detail": {"username": username, "reason": reason},
        "recordedAt": now,
    })

    print(f"[TABLE OVERRIDE] {username}: {old_count} -> {count} ({reason or 'no reason given'})")

    return {"confirmedCount": count}


# ============================================================
# Health check (Render uses this a lot)
# ============================================================

@app.route("/")
def health():
    return {"status": "ok"}


# ============================================================
# Run locally
# ============================================================

# ============================================================
# API: campaign history
# ============================================================

@app.route("/api/campaigns", methods=["GET"])
def campaigns():

    limit = int(request.args.get("limit", 10))

    docs = list(
        alloy_change_collection
        .find({})
        .sort("startedAt", -1)
        .limit(limit)
    )

    return dumps(docs)

# ============================================================
# API: single campaign
# ============================================================


WEIGHT_PER_INCH = 4.9375  # startWeight ~= length_in * WEIGHT_PER_INCH
NONSENSE_TOLERANCE = 0.12  # how far (relatively) a weight may sit from both 216" and 240" before it's untrustworthy


def nearest_length(weight):
    length = weight / WEIGHT_PER_INCH
    return 240 if abs(length - 240) < abs(length - 216) else 216


def is_trustworthy(weight):
    """A weight is trustworthy if it clearly implies one of the two real log lengths."""

    if not weight:
        return False

    length = weight / WEIGHT_PER_INCH

    off_216 = abs(length - 216) / 216
    off_240 = abs(length - 240) / 240

    return min(off_216, off_240) <= NONSENSE_TOLERANCE


def resolve_campaign_lengths(logs):
    """
    Nearest-of-216/240 for logs with a trustworthy startWeight. For logs whose
    weight is missing or doesn't clearly look like either length, borrow the
    majority length from the rest of the campaign -- every log in a campaign
    shares the same PartNo, so they should physically be the same length.
    """

    weights = [log.get("startWeight", 0) for log in logs]
    trustworthy_lengths = [nearest_length(w) for w in weights if is_trustworthy(w)]

    majority_length = None
    if trustworthy_lengths:
        majority_length = Counter(trustworthy_lengths).most_common(1)[0][0]

    lengths = []
    for weight in weights:
        if is_trustworthy(weight):
            lengths.append(nearest_length(weight))
        elif majority_length is not None:
            lengths.append(majority_length)
        elif weight:
            lengths.append(nearest_length(weight))  # no cohort data at all -- best guess
        else:
            lengths.append(0)

    return lengths


WALK_WINDOW_BEFORE = timedelta(days=30)  # logs get staged well ahead of when they're actually run
WALK_WINDOW_AFTER = timedelta(days=14)


def parse_dt(value):
    """Normalizes a BSON datetime or an ISO string (Plex's raw '...Z' timestamps
    are stored as plain strings, not BSON dates) into a naive UTC datetime,
    matching the rest of the app's datetime.utcnow() convention."""

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    return None


def get_sort_time(doc):
    """The moment a log was actually run at the press, if known -- falls back
    to its arrival time (timeMoved) when history hasn't been backfilled yet."""

    last_move = doc.get("lastMove") or {}
    return parse_dt(last_move.get("ChangeDate")) or parse_dt(doc.get("timeMoved"))


def find_alloy_change_logs(target_part_no, die_change_time):
    """
    Walks outward from die_change_time in both directions, ordered by each
    log's actual press-depletion time, until hitting a log for a different
    PartNo. Logs get staged at the press well before they're actually run, so
    raw arrival time (timeMoved) alone can't bound a campaign -- the press
    only consumes one log at a time though, so ordering by depletion time
    gives a genuinely sequential production order to walk the boundary on.
    """

    candidates = list(lf_collection.find({
        "timeMoved": {
            "$gte": die_change_time - WALK_WINDOW_BEFORE,
            "$lte": die_change_time + WALK_WINDOW_AFTER,
        }
    }))

    candidates.sort(key=lambda doc: get_sort_time(doc) or die_change_time)

    anchor = next(
        (i for i, doc in enumerate(candidates) if (get_sort_time(doc) or die_change_time) >= die_change_time),
        len(candidates)
    )

    start = anchor
    while start > 0 and candidates[start - 1].get("PartNo") == target_part_no:
        start -= 1

    end = anchor
    while end < len(candidates) and candidates[end].get("PartNo") == target_part_no:
        end += 1

    return candidates[start:end]


@app.route("/api/campaigns/<campaign_id>", methods=["GET"])
def campaign_details(campaign_id):

    campaign = alloy_change_collection.find_one(
        {"_id": ObjectId(campaign_id)}
    )

    if campaign is None:
        return {"error": "Campaign not found"}, 404

    logs = find_alloy_change_logs(campaign["plexPart"], campaign["startedAt"])

    total_weight = sum(log.get("startWeight", 0) for log in logs)
    total_length = sum(resolve_campaign_lengths(logs))

    return dumps({

        "campaign": campaign,

        "stats": {
            "logCount": len(logs),
            "totalWeight": total_weight,
            "totalLength": total_length
        },

        "logs": logs

    })
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
