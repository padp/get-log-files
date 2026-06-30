from database import client
from datetime import datetime

# ------------------------------------------------------------
# Alloy mapping
# ------------------------------------------------------------

ALLOY_MAP = {
    "006005": "8-6005A",
    "066099": "8-6063 B",
    "006063": "8-6063 GP",
    "006008": "8-6008",
    "006082": "8-6082"
}

press_collection = client["press_db"]["press_data"]

# ------------------------------------------------------------
# Core: get latest press state from Mongo
# ------------------------------------------------------------

def get_press_state():
    """
    Returns latest press document from MongoDB using Date/Time field.
    """

    try:
        doc = press_collection.find_one(
            {},
            sort=[("Date/Time", -1)]
        )

        if not doc:
            return None

        return [doc]  # preserve your existing API shape

    except Exception:
        return None


# ------------------------------------------------------------
# Alloy code
# ------------------------------------------------------------

def get_running_alloy_code():

    try:
        data = get_press_state()

        if not data or not isinstance(data, list):
            return None

        first = data[0]

        return first.get("Alloy")

    except Exception:
        return None


def get_running_alloy():

    code = get_running_alloy_code()

    if not code:
        return None, None

    return code, ALLOY_MAP.get(code, code)