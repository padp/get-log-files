from datetime import datetime

from database import campaigns
from press import get_running_alloy

def get_current_campaign():
    """
    Returns the currently active campaign document.
    """
    return campaigns.find_one({"active": True})

def create_campaign(alloy_code, plex_part):
    """
    Inserts a new active campaign.
    """
    now = datetime.utcnow()

    doc = {
        "alloyCode": alloy_code,
        "plexPart": plex_part,
        "startedAt": now,
        "endedAt": None,
        "active": True
    }

    result = campaigns.insert_one(doc)

    return result.inserted_id

def close_campaign(campaign_id):
    """
    Marks existing campaign as closed.
    """
    campaigns.update_one(
        {"_id": campaign_id},
        {
            "$set": {
                "endedAt": datetime.utcnow(),
                "active": False
            }
        }
    )
    
def process_campaign():
    """
    Checks press alloy and updates campaign state if needed.
    Returns current campaign document.
    """

    code, plex_part = get_running_alloy()

    if not code:
        return None

    current = get_current_campaign()

    # --------------------------------------------------------
    # No campaign exists yet
    # --------------------------------------------------------
    if current is None:
        create_campaign(code, plex_part)
        return get_current_campaign()

    # --------------------------------------------------------
    # No change
    # --------------------------------------------------------
    if current["alloyCode"] == code:
        return current

    # --------------------------------------------------------
    # Alloy changed → close old + open new
    # --------------------------------------------------------
    close_campaign(current["_id"])
    create_campaign(code, plex_part)

    return get_current_campaign()