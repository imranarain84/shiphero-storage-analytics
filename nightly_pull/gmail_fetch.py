import imaplib
import email
import re
import os
import boto3
import requests
from datetime import date
from io import BytesIO

GMAIL_USER      = os.environ["GMAIL_USER"]
GMAIL_APP_PASS  = os.environ["GMAIL_APP_PASS"]
SPACES_KEY      = os.environ["SPACES_KEY"]
SPACES_SECRET   = os.environ["SPACES_SECRET"]
SPACES_BUCKET   = os.environ["SPACES_BUCKET"]
SPACES_REGION   = os.environ.get("SPACES_REGION", "nyc3")
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"

SHIPHERO_SENDER  = "support@shiphero.com"
SHIPHERO_SUBJECT = "Your Inventory Snapshot Report is ready to download"


def _s3():
    return boto3.client(
        "s3",
        region_name           = SPACES_REGION,
        endpoint_url          = SPACES_ENDPOINT,
        aws_access_key_id     = SPACES_KEY,
        aws_secret_access_key = SPACES_SECRET,
    )


def find_download_link() -> str:
    """
    Connect to Gmail via IMAP, find the latest ShipHero report email,
    and extract the signed S3 download URL from the body.
    """
    print("Connecting to Gmail...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_APP_PASS)
    mail.select("inbox")

    # Search for emails from ShipHero with the exact subject
    status, data = mail.search(
        None,
        f'(FROM "{SHIPHERO_SENDER}" SUBJECT "{SHIPHERO_SUBJECT}")'
    )

    if status != "OK" or not data[0]:
        raise Exception("No ShipHero report emails found in inbox")

    # Get the most recent matching email
    email_ids = data[0].split()
    latest_id = email_ids[-1]

    status, msg_data = mail.fetch(latest_id, "(RFC822)")
    mail.logout()

    raw_email = msg_data[0][1]
    msg       = email.message_from_bytes(raw_email)

    # Extract body text
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type in ("text/plain", "text/html"):
                body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
    else:
        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

    # Find the signed S3 URL
    pattern = r'https://[\w\-]+\.s3\.amazonaws\.com/[^\s"<>]+'
    matches = re.findall(pattern, body)

    if not matches:
        raise Exception("Could not find download link in email body")

    # Return the first match (the report URL)
    url = matches[0].rstrip(".")
    print(f"Found download link: {url[:80]}...")
    return url


def download_csv(url: str) -> bytes:
    """Download the CSV from the signed S3 URL."""
    print("Downloading CSV...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    print(f"Downloaded {len(resp.content)/1024:.1f} KB")
    return resp.content


def upload_to_spaces(csv_bytes: bytes, snapshot_date: str):
    """Upload the CSV to Spaces under reports/inventory_YYYY-MM-DD.csv"""
    key = f"reports/inventory_{snapshot_date}.csv"
    _s3().put_object(
        Bucket      = SPACES_BUCKET,
        Key         = key,
        Body        = csv_bytes,
        ContentType = "text/csv",
    )
    print(f"Uploaded to Spaces: {key}")


def main(args: dict = {}) -> dict:
    today = str(date.today())
    print(f"=== Gmail Fetch Starting: {today} ===")

    url      = find_download_link()
    csv_data = download_csv(url)
    upload_to_spaces(csv_data, today)

    print(f"=== Done ===")
    return {"statusCode": 200, "body": f"CSV uploaded for {today}"}


if __name__ == "__main__":
    main()
