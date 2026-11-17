# This script reports users with disabled logins who still have assets assigned in the CATEGORY, CATEGORY, and CATEGORY categories.
# It will send a CSV report with the user details( username, full name, and disabled date) and asset information (asset tag, model, category, company, and current/default locations)
# User accounts are disabled via CRON job LDAP sync.
# Run on a CRON job as needed

import requests
import csv
import os
import sys
import time
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Snipe Config (Loaded from scriptconfig.env)
SNIPEIT_URL = os.getenv("SNIPE_URL", "").rstrip("/")
API_TOKEN = os.getenv("SNIPE_API_KEY", "")

# Script-Specific Variables
CATEGORY_IDS = [1, 2, 3] # IDs for CATEGORY (1), CATEGORY (2), and CATEGORY (3)
OUTPUT_FILE = "Assigned_Assets_Disabled_Users_Report.csv" # Report Name
REQUEST_TIMEOUT = 30 # API timeout in seconds

# Email Config (Loaded from scriptconfig.env)
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Script
# Keep HTTP session open for faster local API calls
session = requests.Session()
session.headers.update({
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "application/json"
})

def print_progress_bar(current, total, label="Progress"):
    if total <= 0:
        return
    percent = min(100.0, (current / float(total)) * 100)
    bar_length = 25
    filled = int(bar_length * current // total)
    bar = "#" * filled + "-" * (bar_length - filled)
    sys.stdout.write(f"\r{label}: [{bar}] {percent:5.1f}% ({current}/{total})")
    sys.stdout.flush()

def fetch_category_assets():
    all_assets = []
    limit = 250

    # Pull all hardware in the target categories
    for category_id in CATEGORY_IDS:
        offset = 0
        total_assets = None

        print(f"Fetching assets in Category ID {category_id}...", flush=True)

        while True:
            url = f"{SNIPEIT_URL}/api/v1/hardware?category_id={category_id}&limit={limit}&offset={offset}"
            try:
                response = session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.exceptions.RequestException as e:
                print(f"\n[ERROR] Failed fetching hardware for category {category_id} at offset {offset}: {e}", flush=True)
                break

            if response.status_code != 200:
                print(f"\n[ERROR] HTTP {response.status_code} fetching hardware for category {category_id}: {response.text}", flush=True)
                break

            data = response.json()
            if total_assets is None:
                total_assets = data.get('total', 0)
                print(f"Found {total_assets} total assets in Category ID {category_id}.", flush=True)

            rows = data.get('rows', [])
            if not rows:
                break

            all_assets.extend(rows)
            offset += len(rows)
            print_progress_bar(offset, total_assets, label=f"Downloading Cat {category_id}")

            if offset >= total_assets:
                break

        print("", flush=True)

    return all_assets

def get_user_details(user_id, user_cache):
    if user_id in user_cache:
        return user_cache[user_id]

    url = f"{SNIPEIT_URL}/api/v1/users/{user_id}"
    for attempt in range(2):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                # Pause 15 seconds if we hit the Snipe-IT API rate limit
                print(f"\n[INFO] API rate limit hit, pausing for 15 seconds...", flush=True)
                time.sleep(15)
                continue
            if resp.status_code == 200:
                user_data = resp.json()
                user_cache[user_id] = user_data
                return user_data
            else:
                print(f"\n[WARNING] HTTP {resp.status_code} looking up user ID {user_id}", flush=True)
                break
        except requests.exceptions.RequestException as e:
            print(f"\n[WARNING] Error looking up user ID {user_id}: {e}", flush=True)
            break

    user_cache[user_id] = None
    return None

def get_disabled_users_with_assets():
    flagged_records = []
    user_cache = {}

    assets = fetch_category_assets()

    # Filter to assets assigned to a user
    user_assigned_assets = [
        a for a in assets
        if isinstance(a.get('assigned_to'), dict) and a['assigned_to'].get('type') == 'user'
    ]

    total_assigned = len(user_assigned_assets)
    print(f"Checking {total_assigned} user-assigned assets for disabled/inactive accounts...\n", flush=True)

    for idx, item in enumerate(user_assigned_assets, start=1):
        assigned_to = item.get('assigned_to') or {}
        user_id = assigned_to.get('id')

        if user_id:
            user_info = get_user_details(user_id, user_cache)
            if user_info:
                is_activated = user_info.get('activated')
                # Check if login is disabled (0 or False)
                if is_activated not in [True, 1, "1", "true", "True"]:
                    username = user_info.get('username', 'N/A')
                    full_name = user_info.get('name', 'N/A')

                    # Get user department from LDAP sync
                    dept_info = user_info.get('department') or {}
                    department = dept_info.get('name', 'N/A')

                    # Get inactive date from updated_at (YYYY-MM-DD only)
                    updated_dict = user_info.get('updated_at', {})
                    raw_updated = updated_dict.get('datetime', '') if isinstance(updated_dict, dict) else str(updated_dict)
                    inactive_date = raw_updated[:10] if raw_updated else "Unknown"

                    # Pull asset details
                    asset_tag = item.get('asset_tag', 'N/A')
                    model_info = item.get('model') or {}
                    model_name = model_info.get('name', 'N/A')

                    cat_info = item.get('category') or {}
                    category_name = cat_info.get('name', 'N/A')

                    company_info = item.get('company') or {}
                    company_name = company_info.get('name', 'N/A')

                    loc_info = item.get('location') or {}
                    current_location = loc_info.get('name', 'N/A')

                    rtd_loc_info = item.get('rtd_location') or {}
                    default_location = rtd_loc_info.get('name', 'N/A')

                    print(
                        f"\n  [MATCH] User: {username} ({full_name} | Dept: {department}) | "
                        f"Inactive: {inactive_date} | Asset: {asset_tag} ({model_name} | Cat: {category_name} | "
                        f"Co: {company_name} | Current Loc: {current_location} | Default Loc: {default_location})",
                        flush=True
                    )

                    flagged_records.append({
                        "Username": username,
                        "Full Name": full_name,
                        "Department": department,
                        "Date Inactive": inactive_date,
                        "Asset Tag": asset_tag,
                        "Model Name": model_name,
                        "Category": category_name,
                        "Company": company_name,
                        "Current Location": current_location,
                        "Default Location": default_location
                    })

        print_progress_bar(idx, total_assigned, label="Checking users")

    print("\n\nScan complete.", flush=True)
    return flagged_records

def generate_csv(records):
    if not records:
        return False

    fieldnames = [
        "Username",
        "Full Name",
        "Department",
        "Date Inactive",
        "Asset Tag",
        "Model Name",
        "Category",
        "Company",
        "Current Location",
        "Default Location"
    ]
    with open(OUTPUT_FILE, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"Report generated successfully: {OUTPUT_FILE}", flush=True)
    return True

# Email Subject & Body Config
def send_email(file_path, body_text):
    print("Preparing to send email...", flush=True)
    todays_date = datetime.now().strftime("%d-%b-%y")

    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Reply-To'] = EMAIL_TO
    msg['Subject'] = f"Snipe-IT Report: Inactive Users with Assigned Assets {todays_date}"

    msg.attach(MIMEText(body_text, 'plain'))

    # Only attach CSV if a file was generated
    if file_path:
        try:
            with open(file_path, "rb") as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())

            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {os.path.basename(file_path)}'
            )
            msg.attach(part)
        except Exception as e:
            print(f"Failed to attach file: {e}", flush=True)
            return

    # Connect to SMTP server and send
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        text = msg.as_string()
        # Split EMAIL_TO so single and comma-separated lists both work
        server.sendmail(EMAIL_FROM, EMAIL_TO.split(","), text)
        server.quit()
        print(f"Email sent successfully to {EMAIL_TO}", flush=True)
    except Exception as e:
        print(f"Failed to send email. Error: {e}", flush=True)

if __name__ == "__main__":
    records = get_disabled_users_with_assets()
    categories_str = ", ".join(str(cid) for cid in CATEGORY_IDS)
    todays_date = datetime.now().strftime("%d-%b-%y")

    if records:
        # Assets found: generate CSV and send report
        print(f"Total matching records found: {len(records)}", flush=True)
        generate_csv(records)
        email_body = f"Please find attached the report listing disabled users who currently hold assets in categories {categories_str}."
        send_email(OUTPUT_FILE, email_body)
    else:
        # Nothing found: skip CSV and send all clear email
        print("No inactive users found with assigned assets in these categories.", flush=True)
        email_body = f"All Clear! There are currently no disabled users with assigned assets in the {categories_str} categories as of {todays_date}."
        send_email(None, email_body)
