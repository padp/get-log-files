"""
from pymongo import MongoClient
from config import secrets

SQL_PASS = open('../secret/pass.txt', 'r').read().strip()

uri = f"mongodb+srv://padpress1:{SQL_PASS}@cluster0.ywwxl.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(uri)
db = client["log_files"]
collection = db["log_files"]

print("Docs:", collection.count_documents({}))
print("Sample:", collection.find_one())


from plex import get_inventory_rows
from inventory import upsert_inventory

rows = get_inventory_rows()

result = upsert_inventory(rows)

print("Upserted:", result.upserted_count if result else 0)
print("Modified:", result.modified_count if result else 0)



from history import process_history_queue

process_history_queue()

"""

from collector import main

main()