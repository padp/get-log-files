from flask import Flask, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.json_util import dumps
from bson import ObjectId
from collections import Counter
from datetime import datetime, timedelta
import os

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

client = MongoClient(
    f"mongodb+srv://padpress1:{SQL_PASS}@cluster0.ywwxl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")

db = client["log_files"]

lf_collection = db["log_files"]

alloy_change_collection = db["campaigns"]

# ============================================================
# Helper: shift start logic (same as your JS)
# ============================================================


def get_shift_start(now=None):

    now = now or datetime.utcnow()

    shift1 = now.replace(hour=7, minute=0, second=0, microsecond=0)
    shift2 = now.replace(hour=15, minute=0, second=0, microsecond=0)
    shift3 = now.replace(hour=23, minute=0, second=0, microsecond=0)

    if now >= shift3:
        return shift3

    if now >= shift2:
        return shift2

    if now >= shift1:
        return shift1

    return (shift3 - timedelta(days=1))


# ============================================================
# API: inventory list (optionally filtered)
# ============================================================

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

    docs = list(
        lf_collection.find(query).sort("timeMoved", -1)
    )

    return dumps(docs)


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

    now = datetime.utcnow()
    shift_start = get_shift_start(now)

    pipeline = [
        {
            "$facet": {
                "shiftCount": [
                    {
                        "$match": {
                            "timeMoved": {"$gte": shift_start}
                        }
                    },
                    {"$count": "count"}
                ],
                "recent": [
                    {"$sort": {"timeMoved": -1}},
                    {"$limit": 12}
                ]
            }
        }
    ]

    result = list(lf_collection.aggregate(pipeline))[0]

    shift_count = result["shiftCount"][0]["count"] if result["shiftCount"] else 0

    return dumps({
        "shiftCount": shift_count,
        "recent": result["recent"]
    })


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
        .sort("started", -1)
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
