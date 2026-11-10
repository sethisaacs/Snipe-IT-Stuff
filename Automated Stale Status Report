# This script reports assets in the asset category 'CATEGORY' that have remained in status 'STATUS' for longer than a defined threshold. 
# It will send a CSV report with the device asset ID, how long it has been 'STATUS', and the location it was sent from.
# Set on a CRON job for for reporting.

import requests
import csv
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Snipe Config (Loaded from environment file)
SNIPEIT_URL = os.getenv("SNIPE_URL", "").rstrip("/")
API_TOKEN = os.getenv("SNIPE_API_KEY", "")

# Script-Specific Variables
STATUS_IDS = [0] # ID for STATUS
CATEGORY_ID = 0 # ID for CATEGORY
DAYS_THRESHOLD = 0 # Days in status
OUTPUT_FILE = "Report.csv" # Report Name

# Email Config (Loaded from environment file)
SMTP_SERVER = os.getenv("SMTP_SERVER", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", 0))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Script
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Accept": "application/json"
}

def get_exact_status_date(asset_id, target_status_name):
    url = f"{SNIPEIT_URL}/api/v1/reports/activity?item_type=asset&item_id={asset_id}&sort=created_at&order=desc"
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        return None
        
    logs = response.json().get('rows', [])
    if not logs:
        return None

    for log in logs:
        log_meta = str(log.get('log_meta', '')).lower()
        note = str(log.get('note', '')).lower()
        
        if target_status_name.lower() in log_meta or target_status_name.lower() in note:
            created_str = log.get('created_at', {}).get('datetime')
            if created_str:
                return datetime.strptime(created_str[:10], "%Y-%m-%d")
    
    oldest_log = logs[-1]
    created_str = oldest_log.get('created_at', {}).get('datetime')
    if created_str:
        return datetime.strptime(created_str[:10], "%Y-%m-%d")

    return None

def get_stale_assets():
    stale_assets = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    for status_id in STATUS_IDS:
        # Added limit=1000 to bypass the default 50 item API limit
        url = f"{SNIPEIT_URL}/api/v1/hardware?status_id={status_id}&category_id={CATEGORY_ID}&limit=1000"
        response = requests.get(url, headers=headers)
        
        if response.status_code != 200:
            print(f"Failed to fetch data for status {status_id}: {response.text}")
            continue
            
        assets = response.json().get('rows', [])
        
        for asset in assets:
            asset_id = asset.get('id')
            status_name = asset.get('status_label', {}).get('name')
            
            exact_date = get_exact_status_date(asset_id, status_name)
            
            if not exact_date:
                updated_str = asset.get('updated_at', {}).get('datetime')
                if not updated_str: continue
                exact_date = datetime.strptime(updated_str[:10], "%Y-%m-%d")

            days_in_status = (today - exact_date).days
            
            if days_in_status >= DAYS_THRESHOLD:
                assigned_to = asset.get('assigned_to') or {}
                
                stale_assets.append({
                    "Asset Tag": asset.get('asset_tag'),
                    "Name": asset.get('name', 'N/A'),
                    "Checkout Type": assigned_to.get('type', 'Unassigned').title(),
                    "Checked Out To": assigned_to.get('name', 'Unassigned'),
                    "Status": status_name,
                    "Days in Status": days_in_status,
                    "Date Entered Status": exact_date.strftime("%Y-%m-%d")
                })
                
    return stale_assets

def generate_csv(assets):
    if not assets:
        print("No assets exceeded the time threshold. Skipping CSV generation.")
        return False
        
    with open(OUTPUT_FILE, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=["Asset Tag", "Name", "Checkout Type", "Checked Out To", "Status", "Days in Status", "Date Entered Status"])
        writer.writeheader()
        writer.writerows(assets)
    print(f"Report generated successfully: {OUTPUT_FILE}")
    return True

# Email Subject & Body Config
def send_email(file_path, body_text):
    print("Preparing to send email...")
    todays_date = datetime.now().strftime("%d-%b-%y")
    msg = MIMEMultipart()
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg['Subject'] = f"Snipe-IT Report: Stale STATUS | CATEGORY - {todays_date}" 
    
    # Attach the dynamic body text
    msg.attach(MIMEText(body_text, 'plain'))
    
    # Only try to attach a CSV if a file_path was provided
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
            print(f"Failed to attach file: {e}")
            return

    # Connect to SMTP server and send
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls() # Secure the connection
        server.login(SMTP_USER, SMTP_PASS)
        text = msg.as_string()
        
        # Split EMAIL_TO to handle both single and comma-separated multiple recipients
        server.sendmail(EMAIL_FROM, EMAIL_TO.split(","), text)
        
        server.quit()
        print(f"Email sent successfully to {EMAIL_TO}")
    except Exception as e:
        print(f"Failed to send email. Error: {e}")

if __name__ == "__main__":
    print(f"Gathering data for category ID {CATEGORY_ID} and analyzing asset history...")
    stale = get_stale_assets()
    
    if stale:
        # Assets found: Generate CSV and send standard email with attachment
        generate_csv(stale)
        email_body = f"Please see the attached CSV report for CATEGORY Devices that have remained in STATUS longer than the {DAYS_THRESHOLD} day threshold."
        send_email(OUTPUT_FILE, email_body)
    else:
        # No assets found: Skip CSV, send "all clear" email with no attachment
        print("No assets exceeded the time threshold. Sending email without CSV.")
        email_body = f"There are currently no CATEGORY Devices that have exceeded the {DAYS_THRESHOLD} day threshold."
        send_email(None, email_body)
