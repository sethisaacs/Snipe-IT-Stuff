# This python script uses Meraki Systems Manager 'Latest Connectivity Timestamp' to see when the device was last seen online in MDM.
# It then post that day and time to your custom Snipe-IT field
# Run on CRON job

import sys
import time
import requests
from datetime import datetime

# ================= Configuration =================
MERAKI_API_KEY = "APIKEY" Meraki API Key with view only for organization
MERAKI_NETWORK_ID = "NET-ID" # Replace with network ID, not Organization ID

SNIPEIT_BASE_URL = "URL"  # Replace with localhost:port or with Snipe URL
SNIPEIT_API_KEY = "APIKEY" # Snipe API key with asset edit access
SNIPEIT_CUSTOM_FIELD_KEY = "_snipeit_CUSTOM_FIELD_00"  # Snipe DB column name, repalce CUSTOM_FILED_00

DRY_RUN = False  # Set to True to preview without posting to Snipe
# =================================================

MERAKI_HEADERS = {
    "X-Cisco-Meraki-API-Key": MERAKI_API_KEY,
    "Accept": "application/json",
}

SNIPEIT_HEADERS = {
    "Authorization": f"Bearer {SNIPEIT_API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def parse_timestamp(iso_str):
    """Convert Meraki ISO timestamp (e.g. 2026-03-16T08:15:29.400000Z) to Snipe-IT format."""
    if not iso_str:
        return None
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def fetch_all_sm_devices():
    """Retrieve all devices from Meraki Systems Manager network."""
    url = f"https://api.meraki.com/api/v1/networks/{MERAKI_NETWORK_ID}/sm/devices"
    params = {"perPage": 1000}
    devices = []

    while url:
        resp = requests.get(url, headers=MERAKI_HEADERS, params=params if "?" not in url else None)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        devices.extend(batch)

        next_url = None
        if "Link" in resp.headers:
            links = requests.utils.parse_header_links(resp.headers["Link"])
            for link in links:
                if link.get("rel") == "next":
                    next_url = link.get("url")
                    break
        url = next_url

    return devices


def get_latest_connectivity_timestamp(device_id):
    """Paginates to the end of the connectivity history to get the latest lastSeenAt."""
    url = f"https://api.meraki.com/api/v1/networks/{MERAKI_NETWORK_ID}/sm/devices/{device_id}/connectivity"
    latest_ts = None

    while url:
        try:
            resp = requests.get(url, headers=MERAKI_HEADERS, params={"perPage": 1000} if "?" not in url else None)
            resp.raise_for_status()
            batch = resp.json()
            if batch:
                latest_ts = batch[-1].get("lastSeenAt") or batch[-1].get("firstSeenAt")

            next_url = None
            if "Link" in resp.headers:
                links = requests.utils.parse_header_links(resp.headers["Link"])
                for link in links:
                    if link.get("rel") == "next":
                        next_url = link.get("url")
                        break
            url = next_url
        except requests.exceptions.RequestException as e:
            print(f"Warning: Failed fetching connectivity for {device_id}: {e}")
            break

    return latest_ts


def get_snipeit_asset_by_serial(serial):
    """Lookup asset ID and existing custom field value in Snipe-IT by hardware serial."""
    url = f"{SNIPEIT_BASE_URL}/api/v1/hardware/byserial/{serial}"
    try:
        resp = requests.get(url, headers=SNIPEIT_HEADERS)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("total", 0) > 0 and len(data.get("rows", [])) > 0:
                return data["rows"][0]
    except requests.exceptions.RequestException as e:
        print(f"Warning: Failed querying Snipe-IT for serial {serial}: {e}")
    return None


def update_snipeit_custom_field(asset_id, timestamp_str):
    """Update custom field on target asset."""
    url = f"{SNIPEIT_BASE_URL}/api/v1/hardware/{asset_id}"
    payload = {
        SNIPEIT_CUSTOM_FIELD_KEY: timestamp_str
    }
    resp = requests.patch(url, headers=SNIPEIT_HEADERS, json=payload)
    resp.raise_for_status()
    return resp.json()


def main():
    print("Fetching devices from Meraki Systems Manager...")
    try:
        devices = fetch_all_sm_devices()
    except Exception as e:
        print(f"Error fetching Meraki devices: {e}")
        sys.exit(1)

    print(f"Retrieved {len(devices)} devices from Meraki SM.\n")

    updated_count = 0
    unchanged_count = 0
    not_in_snipeit_count = 0
    no_timestamp_count = 0
    no_serial_count = 0

    not_found_serials = []

    for dev in devices:
        serial = dev.get("serialNumber") or dev.get("serial")
        dev_id = dev.get("id")

        if not serial:
            no_serial_count += 1
            continue

        if not dev_id:
            continue

        # 1. Check Snipe-IT
        asset = get_snipeit_asset_by_serial(serial)
        if not asset:
            not_in_snipeit_count += 1
            not_found_serials.append(serial)
            continue

        asset_id = asset["id"]
        current_val = (
            asset.get("custom_fields", {})
            .get(SNIPEIT_CUSTOM_FIELD_KEY, {})
            .get("value")
        )

        # 2. Query Meraki for the latest connectivity check-in
        raw_ts = get_latest_connectivity_timestamp(dev_id)
        formatted_time = parse_timestamp(raw_ts)

        if not formatted_time:
            no_timestamp_count += 1
            continue

        # 3. Check if already up-to-date
        if current_val == formatted_time:
            unchanged_count += 1
            continue

        # 4. Apply update
        print(f"[{serial}] Updating Asset #{asset_id} -> {formatted_time}")
        if not DRY_RUN:
            update_snipeit_custom_field(asset_id, formatted_time)
        updated_count += 1

        # Rate-limiting pause
        time.sleep(0.15)

# Sync breakdown. Uncomment to see results. Helpful for initial setup or troubleshooting
#   print("\n================ Sync Breakdown ================")
#   print(f"Total Meraki Devices Scanned : {len(devices)}")
#   print(f"Successfully Updated         : {updated_count}")
#   print(f"Already Up-To-Date           : {unchanged_count}")
#   print(f"Not Found in Snipe-IT        : {not_in_snipeit_count}")
#   print(f"No Meraki Connectivity Time  : {no_timestamp_count}")
#   print(f"Missing Serial in Meraki     : {no_serial_count}")
#   print("================================================")

    if not_found_serials:
        print(f"\nSample serials in Meraki but missing from Snipe-IT (first 10):")
        print(", ".join(not_found_serials[:10]))


if __name__ == "__main__":
    main()
