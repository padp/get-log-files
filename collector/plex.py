import requests
from config import secrets
from login import renew_credentials, load_credentials

INFO_FILE = "../secret/infos.txt"
LOGIN_SECRETS_PATH = "../secret/login_infos.txt"

_login_secrets = load_credentials(LOGIN_SECRETS_PATH)

session = requests.Session()


def _apply_cookies(creds):
    session.cookies.update({
        "plex-customercode": "Whitehall-KY",
        "plex-languageculturecode": "en-US",
        "plex-auth-prod": creds["AUTH_PROD"],
    })


_apply_cookies(secrets)


def _reauth():
    """Log in fresh, overwrite infos.txt, and pick up the new ASID/AUTH_PROD."""
    global secrets
    secrets = renew_credentials(
        secrets_path=INFO_FILE,
        username=_login_secrets["username"],
        password=_login_secrets["password"],
        company_code=_login_secrets["company_code"],
    )
    _apply_cookies(secrets)


def _post(url, params, json, timeout=15):
    """POST with a single retry: re-login once if the session has expired (401/403/419)."""
    resp = session.post(url, params=params, json=json, timeout=timeout)

    if resp.status_code in (401, 403, 419):
        _reauth()
        resp = session.post(url, params={**params, "__asid": secrets["ASID"]}, json=json, timeout=timeout)

    if resp.status_code in (401, 403, 419):
        raise PermissionError("Session expired and re-login failed")

    resp.raise_for_status()
    return resp


def get_inventory_rows():
    resp = _post(
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
    )
    return resp.json().get("Data", {}).get("Rows", [])


def get_container_history(serial_no):
    resp = _post(
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
    )
    return resp.json().get("Data", {}).get("Rows", [])
