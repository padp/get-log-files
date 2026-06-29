import requests
from config import PRESS_API

# ------------------------------------------------------------
# Alloy mapping (Plex → your internal naming)
# ------------------------------------------------------------

ALLOY_MAP = {
    "006005": "8-6005A",
    "066099": "8-6063 B",
    "006063": "8-6063 GP",
    "006008": "8-6008",
    "006082": "8-6082"
}


# ------------------------------------------------------------
# Core function: get raw press state
# ------------------------------------------------------------

def get_press_state():
    """
    Returns raw press JSON from external API.
    """
    resp = requests.get(PRESS_API, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------
# Normalized alloy functions
# ------------------------------------------------------------

def get_running_alloy_code():
    """
    Returns raw alloy code from press API (e.g. '006005').
    Safe: never throws, never returns invalid overwrite values.
    """

    try:
        data = get_press_state()

        if not data or not isinstance(data, list):
            return None

        first = data[0] if len(data) > 0 else None

        if not isinstance(first, dict):
            return None

        alloy = first.get("Alloy")

        if not alloy:
            return None

        return alloy

    except Exception:
        return None


def get_running_alloy():
    """
    Returns mapped Plex alloy name (e.g. '8-6005A').
    Falls back to raw code if unknown.
    """
    code = get_running_alloy_code()

    if not code:
        return None, None

    return code, ALLOY_MAP.get(code, code)