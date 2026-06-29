import requests
from config import secrets

session = requests.Session()

session.cookies.update({
    "plex-customercode": "Whitehall-KY",
    "plex-languageculturecode": "en-US",
    "apt.uid": secrets["UID"],
    "plex-auth-prod": secrets["AUTH_PROD"],
    "apt.sid": secrets["SID"],
})

def get_inventory_rows():
    resp = session.post(
        "https://cloud.plex.com/Inventory/InventoryByLocation/Search",
        params={
            "__asid": secrets["ASID"],
            "limit": "true",
            "sourceActionKey": "10095"
        },
        json={
            "BuildingCode": "Paducah",
            "LocationInput": "PAD-Extrusion SHARED",
            "BuildingKey": "5208",
            "PCN": 0
        },
        timeout=15
    )

    if resp.status_code in (401, 403):
        raise PermissionError("Session expired")

    resp.raise_for_status()
    return resp.json().get("Data", {}).get("Rows", [])

def get_container_history(serial_no):
    resp = session.post(
        "https://cloud.plex.com/Inventory/ContainerHistory/SearchContainerHistory2",
        params={
            "__asid": secrets["ASID"],
            "limit": "true",
            "sourceActionKey": "13303"
        },
        json={
            "PartNo": "",
            "PlexusCustomerNo": 0,
            "SerialNo": serial_no
        },
        timeout=15
    )

    if resp.status_code in (401, 403):
        raise PermissionError("Session expired")

    resp.raise_for_status()
    return resp.json().get("Data", {}).get("Rows", [])