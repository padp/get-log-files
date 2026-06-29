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
            "Location": r.get("Location")
        })

    return out

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
                    "StartWeight": latest.get("Quantity")
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

