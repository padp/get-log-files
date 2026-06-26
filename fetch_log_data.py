import time
from datetime import datetime

import requests
from pymongo import MongoClient, UpdateOne
from pymongo.server_api import ServerApi


# ============================================================
# Configuration
# ============================================================

CHECK_INTERVAL = 60

MAX_FILE_CONTENT_LEN = 1
FILE_CONTENTS = []
SQL_PASS = open('../secret/pass.txt', 'r').read()
uri = f"mongodb+srv://padpress1:{SQL_PASS}@cluster0.ywwxl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(uri, server_api=ServerApi('1'))
db = client['log_files']
collection = db['log_files']

URL = "https://cloud.plex.com/Inventory/InventoryByLocation/Search"

PARAMS = {
    "__asid": "e7cb2ddc332341099923bc057e2aabff",
    "limit": "true",
    "sourceActionKey": "10095"
}

PAYLOAD = {
    "BuildingCode": "Paducah",
    "LocationInput": "PAD-Extrusion SHARED",
    "BuildingKey": "5208",
    "PCN": 0
}

session = requests.Session()

session.cookies.update({
    "plex-customercode": "Whitehall-KY",
    "plex-languageculturecode": "en-US",
    "apt.uid": "AP-K8HQXAK7WUV8-2-1746719246469-58932842.0.2.80b5fbc8-a2fc-469d-90cc-711043ee972e",
    "plex-auth-prod": "ab333702bf9b4ec0951ad96ed9ec366a",
    "apt.sid": "AP-K8HQXAK7WUV8-2-1782398410625-66449194",
})


def make_key(row):
    """
    Creates a unique key for each inventory item.
    """
    return f"{row.get('PartNo')}|{row.get('Location')}|{row.get('SerialNo')}"


def get_rows():

    response = session.post(
        URL,
        params=PARAMS,
        json=PAYLOAD,
        timeout=15
    )

    if response.status_code in (401, 403):
        raise PermissionError("Session expired")

    response.raise_for_status()

    data = response.json()

    return data.get("Data", {}).get("Rows", [])


def upsert_rows(rows):

    if not rows:
        return None

    now = datetime.utcnow()

    operations = []

    for row in rows:

        key = make_key(row)

        operations.append(

            UpdateOne(

                {"_id": key},

                {
                    "$set": {
                        **row,
                        "lastSeen": now
                    },

                    "$setOnInsert": {
                        "timeMoved": now
                    }

                },

                upsert=True

            )

        )

    return collection.bulk_write(
        operations,
        ordered=False
    )


def ensure_indexes():

    collection.create_index("PartNo")
    collection.create_index("Location")
    collection.create_index("SerialNo")
    collection.create_index("timeMoved")
    collection.create_index("lastSeen")


# ============================================================
# Main
# ============================================================

def main():

    ensure_indexes()

    print("Inventory monitor started.")

    while True:

        try:

            rows = get_rows()

            result = upsert_rows(rows)

            if result:

                print(
                    f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
                    f"Rows: {len(rows)} | "
                    f"New: {result.upserted_count} | "
                    f"Updated: {result.modified_count}"
                )

            else:

                print(
                    f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
                    "No rows returned."
                )

        except PermissionError:

            print("Authentication expired.")
            break

        except requests.RequestException as e:

            print(f"Network error: {e}")

        except Exception as e:

            print(f"Unexpected error: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()