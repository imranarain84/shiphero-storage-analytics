import os
import json
import gzip
import boto3
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
from io import BytesIO

SPACES_KEY      = os.environ["SPACES_KEY"]
SPACES_SECRET   = os.environ["SPACES_SECRET"]
SPACES_BUCKET   = os.environ["SPACES_BUCKET"]
SPACES_REGION   = os.environ.get("SPACES_REGION", "nyc3")
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"

GMAIL_USER     = os.environ["GMAIL_USER"]
GMAIL_APP_PASS = os.environ["GMAIL_APP_PASS"]

NOTIFY_EMAILS  = ["imran@verticalpassage.com", "ryan@verticalpassage.com"]


def _s3():
    return boto3.client(
        "s3",
        region_name           = SPACES_REGION,
        endpoint_url          = SPACES_ENDPOINT,
        aws_access_key_id     = SPACES_KEY,
        aws_secret_access_key = SPACES_SECRET,
    )


def load_latest_csv() -> pd.DataFrame:
    s3   = _s3()
    resp = s3.list_objects_v2(Bucket=SPACES_BUCKET, Prefix="reports/")

    files = [
        obj["Key"] for obj in resp.get("Contents", [])
        if obj["Key"].endswith(".csv")
    ]

    if not files:
        raise FileNotFoundError("No CSV files found in reports/ folder in Spaces")

    latest = sorted(files)[-1]
    print(f"Loading CSV: {latest}")

    obj  = s3.get_object(Bucket=SPACES_BUCKET, Key=latest)
    data = obj["Body"].read()
    return pd.read_csv(BytesIO(data), on_bad_lines='skip')


def csv_to_snapshot_rows(df: pd.DataFrame) -> list[dict]:
    rows = []
    for _, row in df.iterrows():
        tags_raw = row.get("Product Tags", "")
        if pd.isna(tags_raw):
            tags = []
        else:
            tags = [t.strip() for t in str(tags_raw).split("|") if t.strip()]

        rows.append({
            "sku":           str(row.get("SKU", "")).strip(),
            "product_name":  str(row.get("Product Name", "")).strip(),
            "tags":          tags,
            "customer":      str(row.get("3PL Customer", "")).strip(),
            "location_name": str(row.get("Bin/Location Name", "")).strip() or None,
            "storage_type":  str(row.get("Storage Location Type", "")).strip() or None,
            "quantity":      int(row.get("Quantity", 0) or 0),
            "warehouse":     str(row.get("Warehouse Name", "")).strip(),
        })
    return rows


def upload_snapshot(rows: list[dict], snapshot_date: str) -> float:
    payload  = json.dumps(rows, default=str).encode("utf-8")
    gz_bytes = gzip.compress(payload)
    key      = f"inventory/{snapshot_date}.json.gz"

    _s3().put_object(
        Bucket          = SPACES_BUCKET,
        Key             = key,
        Body            = gz_bytes,
        ContentType     = "application/json",
        ContentEncoding = "gzip",
    )
    size_kb = len(gz_bytes) / 1024
    print(f"Uploaded {key} ({size_kb:.1f} KB, {len(rows):,} rows)")
    return size_kb


def send_summary_email(snapshot_date: str, row_count: int, size_kb: float, customers: list[str]):
    print("Sending summary email...")

    subject = f"✅ Warehouse Storage Snapshot Ready — {snapshot_date}"

    body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #333;">
        <h2 style="color: #2c3e50;">Daily Inventory Snapshot — {snapshot_date}</h2>
        <p>The daily ShipHero inventory report has been successfully downloaded and processed.</p>
        <table style="border-collapse: collapse; width: 400px;">
            <tr style="background-color: #f2f2f2;">
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Date</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{snapshot_date}</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Rows Processed</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{row_count:,}</td>
            </tr>
            <tr style="background-color: #f2f2f2;">
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Snapshot Size</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{size_kb:.1f} KB</td>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #ddd;"><strong>Customers</strong></td>
                <td style="padding: 8px; border: 1px solid #ddd;">{len(customers)}</td>
            </tr>
        </table>
        <br>
        <p style="color: #888; font-size: 12px;">
            This is an automated message from the Vertical Passage Warehouse Storage Report system.
        </p>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = ", ".join(NOTIFY_EMAILS)
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASS)
        server.sendmail(GMAIL_USER, NOTIFY_EMAILS, msg.as_string())

    print(f"Summary email sent to {', '.join(NOTIFY_EMAILS)}")


def main(args: dict = {}) -> dict:
    today = str(date.today())
    print(f"=== Nightly Pull Starting: {today} ===")

    df = load_latest_csv()
    print(f"Loaded {len(df):,} rows from CSV")

    df = df[df["Quantity"] > 0]
    print(f"{len(df):,} rows with quantity > 0")

    rows      = csv_to_snapshot_rows(df)
    size_kb   = upload_snapshot(rows, today)
    customers = sorted(set(r["customer"] for r in rows if r.get("customer")))

    try:
        send_summary_email(today, len(rows), size_kb, customers)
    except Exception as e:
        print(f"Warning: could not send summary email — {e}")

    summary = f"Done — {len(rows):,} rows for {today}"
    print(f"=== {summary} ===")
    return {"statusCode": 200, "body": summary}


if __name__ == "__main__":
    main()
