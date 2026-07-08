import time
from datetime import datetime
import requests
from config import CHECK_INTERVAL
from campaigns import process_campaign
from inventory import upsert_inventory
from plex import get_inventory_rows
from history import process_history_queue, backfill_start_weight
from billet_log import record_billet_state


def main():

    print("[STATUS] Collector starting")

    while True:

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            print(f"[STATUS] {now} cycle starting")

            campaign = process_campaign()
            print(f"[STATUS] Campaign: {campaign['plexPart'] if campaign else 'none'}")

            record_billet_state()

            rows = get_inventory_rows()
            print(f"[STATUS] Fetched {len(rows)} inventory rows")

            upsert_inventory(rows, campaign)

            process_history_queue()

            backfill_start_weight()

            print("[STATUS] Cycle complete")

        except PermissionError as e:
            print(f"[AUTH] {e}")

        except requests.RequestException as e:
            print(f"[NETWORK] {e}")

        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()