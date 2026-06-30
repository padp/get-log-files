from plex import get_container_history
from config import HISTORY_BATCH_SIZE
from database import inventory as collection
from datetime import datetime

def simplify_history(rows):

    out = []

    for r in rows:
        out.append({
            "UpdateDate": r.get("UpdateDate"),
            "ChangeDate": r.get("ChangeDate"),
            "Containers": r.get("Containers"),
            "FirstName": r.get("FirstName"),
            "LastName": r.get("LastName"),
            "LastAction": r.get("LastAction"),
            "Location": r.get("Location"),
        })

    return out

def extract_rows(raw):

    if isinstance(raw, list):
        return raw

    if isinstance(raw, dict):
        if "Data" in raw:
            return raw.get("Data", {}).get("Rows", []) or []
        if "Rows" in raw:
            return raw.get("Rows", []) or []

    return []

def backfill_start_weight():

    docs = collection.find({
        "startWeight": {"$exists": False},
        "SerialNo": {"$exists": True}
    }).limit(HISTORY_BATCH_SIZE)

    for doc in docs:

        serial = doc["SerialNo"]

        try:
            # 1. ALWAYS use fresh Plex data
            raw = get_container_history(serial)
            rows = extract_rows(raw)

            if not rows:
                continue

            # 2. simplify search for StartWeight
            start_weight = None

            for r in rows:
                if r.get("Quantity") is not None:
                    start_weight = r["Quantity"]
                    break

            if start_weight is None:
                print(f"[SKIP] No StartWeight found for {serial}")
                continue

            # 3. update Mongo
            collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "startWeight": start_weight
                    }
                }
            )

            print(f"[BACKFILL] {serial} → {start_weight}")

        except Exception as e:
            print(f"[ERROR] {serial}: {e}")
            

def process_history_queue():

    docs = collection.find({
        "$or": [
            {"historyLoaded": {"$exists": False}},
            {"historyLoaded": False}
        ]
    }).limit(HISTORY_BATCH_SIZE)

    for doc in docs:

        serial = doc["SerialNo"]

        try:

            raw = get_container_history(serial)
            history = simplify_history(raw)

            now = datetime.utcnow()

            update = {
                "history": history,
                "historyLoaded": True,
                "historyLoadedAt": now,
                "historyAttempts": doc.get("historyAttempts", 0) + 1,
                "historyLastAttempt": now
            }

            # derive latest move
            if history:
                latest = max(history, key=lambda x: x["ChangeDate"] or "")

                update["lastMove"] = {
                    "FirstName": latest.get("FirstName"),
                    "LastName": latest.get("LastName"),
                    "Action": latest.get("LastAction"),
                    "Location": latest.get("Location"),
                    "ChangeDate": latest.get("ChangeDate"),
                }

            collection.update_one(
                {"_id": doc["_id"]},
                {"$set": update}
            )

            print(f"[HISTORY] Loaded {serial}")

        except Exception as e:

            collection.update_one(
                {"_id": doc["_id"]},
                {
                    "$inc": {"historyAttempts": 1},
                    "$set": {"historyLastAttempt": datetime.utcnow()}
                }
            )

            print(f"[HISTORY ERROR] {serial}: {e}")

