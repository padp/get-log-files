import time
import requests
from config import CHECK_INTERVAL
from campaigns import process_campaign
from inventory import upsert_inventory
from plex import get_inventory_rows
from history import process_history_queue, backfill_start_weight


def main():

    while True:

        try:
            campaign = process_campaign()

            rows = get_inventory_rows()

            upsert_inventory(rows, campaign)

            process_history_queue()

            backfill_start_weight()

        except PermissionError as e:
            print(f"[AUTH] {e}")

        except requests.RequestException as e:
            print(f"[NETWORK] {e}")

        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()