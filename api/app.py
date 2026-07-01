from flask import Flask, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.json_util import dumps
from bson import ObjectId
from datetime import datetime, timedelta
import os

app = Flask(__name__)

CORS(
    app,
    origins=[
        "https://padp.github.io"
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


def calculate_length(weight):

    if not weight:
        return 0

    length = weight / 4.9375

    return 240 if abs(length-240) < abs(length-216) else 216


@app.route("/api/campaigns/<campaign_id>", methods=["GET"])
def campaign_details(campaign_id):

    campaign = alloy_change_collection.find_one(
        {"_id": ObjectId(campaign_id)}
    )

    if campaign is None:
        return {"error": "Campaign not found"}, 404

    query = {
        "timeMoved": {
            "$gte": campaign["startedAt"]
        }
    }

    if campaign.get("endedAt"):
        query["timeMoved"]["$lt"] = campaign["endedAt"]

    logs = list(
        lf_collection.find(query).sort("timeMoved", 1)
    )

    total_weight = 0
    total_length = 0

    for log in logs:

        weight = log.get("startWeight", 0)

        total_weight += weight
        total_length += calculate_length(weight)

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
