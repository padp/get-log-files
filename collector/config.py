from pathlib import Path

CHECK_INTERVAL = 60

HISTORY_BATCH_SIZE = 10

SECRET_FOLDER = Path("../../secret")

INFO_FILE = SECRET_FOLDER / "infos.txt"

PASS_FILE = SECRET_FOLDER / "pass.txt"

DATABASE_NAME = "log_files"

INVENTORY_COLLECTION = "log_files"

CAMPAIGN_COLLECTION = "alloy_campaigns"

PRESS_API = "https://mongo-express-api.vercel.app/data"

SQL_PASS = open('../secret/pass.txt', 'r').read().strip()

import os

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


secrets = load_secrets()