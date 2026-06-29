import time
from datetime import datetime
import requests
from pymongo import MongoClient, UpdateOne
from pymongo.server_api import ServerApi

# ============================================================
# CONFIG
# ============================================================


def load_secrets(path="../secret/infos.txt"):
    secrets = {}

    with open(path, "r") as f:
        for line in f:
            line = line.strip()

            if not line or "=" not in line:
                continue

            key, value = line.split("=", 1)
            secrets[key.strip()] = value.strip()

    return secrets


CHECK_INTERVAL = 60
HISTORY_BATCH_SIZE = 10

secrets = load_secrets()

SQL_PASS = open('../secret/pass.txt', 'r').read().strip()

uri = f"mongodb+srv://padpress1:{SQL_PASS}@cluster0.ywwxl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(uri, server_api=ServerApi('1'))
db = client['log_files']
collection = db['log_files']

# ============================================================
# PLEX ENDPOINTS
# ============================================================

INVENTORY_URL = "https://cloud.plex.com/Inventory/InventoryByLocation/Search"

INVENTORY_PARAMS = {
    "__asid": secrets["ASID"],
    "limit": "true",
    "sourceActionKey": "10095"
}

INVENTORY_PAYLOAD = {
    "BuildingCode": "Paducah",
    "LocationInput": "PAD-Extrusion SHARED",
    "BuildingKey": "5208",
    "PCN": 0
}

HISTORY_URL = "https://cloud.plex.com/Inventory/ContainerHistory/SearchContainerHistory2"

HISTORY_PARAMS = {
    "__asid": secrets["ASID"],
    "limit": "true",
    "sourceActionKey": "13303"
}

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.cookies.update(
    {"plex-customercode": "Whitehall-KY",
     "plex-languageculturecode": "en-US",
     "apt.uid": secrets["UID"],
     "plex-auth-prod": secrets["AUTH_PROD"],
     "apt.sid": secrets["SID"],
     })

# ============================================================
# HELPERS
# ============================================================


def make_key(row):
    return f"{row.get('PartNo')}|{row.get('Location')}|{row.get('SerialNo')}"


def get_rows():
    resp = session.post(
        INVENTORY_URL,
        params=INVENTORY_PARAMS,
        json=INVENTORY_PAYLOAD,
        timeout=15
    )

    if resp.status_code in (401, 403):
        raise PermissionError("Session expired")

    resp.raise_for_status()

    return resp.json().get("Data", {}).get("Rows", [])


# ============================================================
# INVENTORY UPSERT
# ============================================================

def upsert_inventory(rows):

    if not rows:
        return None

    now = datetime.utcnow()

    ops = []

    for row in rows:

        key = make_key(row)

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


# ============================================================
# HISTORY FETCH + PARSE
# ============================================================

def get_container_history(serial_no):

    payload = {
        "PartNo": "",
        "PlexusCustomerNo": 0,
        "SerialNo": serial_no
    }

    resp = session.post(
        HISTORY_URL,
        params=HISTORY_PARAMS,
        json=payload,
        timeout=15
    )

    resp.raise_for_status()

    return resp.json().get("Data", {}).get("Rows", [])


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


# ============================================================
# HISTORY WORKER (NON-BLOCKING)
# ============================================================

def backfill_start_weight():

    docs = collection.find({
        "startWeight": {"$exists": False},
        "history": {"$exists": True}
    }).limit(HISTORY_BATCH_SIZE)

    for doc in docs:

        history = doc.get("history", [])

        if not history:
            continue

        # safer: find first valid StartWeight anywhere
        start_weight = None

        for h in reversed(history):
            if h.get("StartWeight") is not None:
                start_weight = h["StartWeight"]
                break

        if start_weight is None:
            continue

        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "startWeight": start_weight
                }
            }
        )

        print(f"[BACKFILL] {doc['_id']}")

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


# ============================================================
# INDEXES
# ============================================================

def ensure_indexes():
    collection.create_index("PartNo")
    collection.create_index("Location")
    collection.create_index("SerialNo")
    collection.create_index("timeMoved")
    collection.create_index("lastSeen")
    collection.create_index("historyLoaded")


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    ensure_indexes()

    print("Inventory + History monitor started.")

    while True:

        try:

            # 1. INVENTORY
            rows = get_rows()
            result = upsert_inventory(rows)

            # 2. HISTORY ENRICHMENT (NON-BLOCKING)
            process_history_queue()
            
            backfill_start_weight()  

            # LOG
            if result:
                print(
                    f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
                    f"Rows: {len(rows)} | "
                    f"New: {result.upserted_count} | "
                    f"Updated: {result.modified_count}"
                )

        except PermissionError:
            print("Session expired.")
            break

        except requests.RequestException as e:
            print(f"Network error: {e}")

        except Exception as e:
            print(f"Unexpected error: {e}")

        time.sleep(CHECK_INTERVAL)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
