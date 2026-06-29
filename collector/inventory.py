from datetime import datetime
from pymongo import UpdateOne
from database import inventory as collection

def make_key(row):
    return f"{row.get('PartNo')}|{row.get('Location')}|{row.get('SerialNo')}"

def upsert_inventory(rows, campaign=None):

    if not rows:
        return None

    now = datetime.utcnow()

    ops = []

    for row in rows:

        key = make_key(row)

        if campaign:
            row["campaign"] = campaign

        ops.append(
            UpdateOne(
                {"_id": key},
                {
                    "$set": {
                        **row,
                        "lastSeen": now
                    },
                    "$setOnInsert": {
                        "timeMoved": now,
                        "historyLoaded": False,
                        "historyLoadedAt": None,
                        "historyAttempts": 0,
                        "historyLastAttempt": None
                    }
                },
                upsert=True
            )
        )

    return collection.bulk_write(ops, ordered=False)