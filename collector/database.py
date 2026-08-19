from pymongo import MongoClient
from pymongo.server_api import ServerApi
from config import SQL_PASS


# ============================================================
# CONNECTION
# ============================================================

uri = f"mongodb+srv://padpress1:{SQL_PASS}@cluster0.ywwxl.mongodb.net/?retryWrites=true&w=majority"

client = MongoClient(uri, server_api=ServerApi("1"))

db = client["log_files"]


# ============================================================
# COLLECTIONS
# ============================================================

inventory = db["log_files"]
campaigns = db["campaigns"]
history = db["history_logs"]  # optional but recommended
billets = db["billet_log"]
schedule_status = db["schedule_status"]
table_state = db["table_state"]
table_events = db["table_events"]
table_state_image = db["table_state_image"]
log_bay_inventory = db["log_bay_inventory"]