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

        loc_name = str(row.get("Bin/Location Name", "") or "").strip()
        stor_type = str(row.get("Storage Location Type", "") or "").strip()

        rows.append({
            "sku":           str(row.get("SKU", "")).strip(),
            "product_name":  str(row.get("Product Name", "")).strip(),
            "tags":          tags,
            "customer":      str(row.get("3PL Customer", "")).strip(),
            "location_name": None if loc_name in ("", "nan") else loc_name,
            "storage_type":  None if stor_type in ("", "nan") else stor_type,
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


def compute_daily_summary(rows: list[dict], snapshot_date: str):
    """
    Compute and store a lightweight daily summary in cost_history.json.
    This allows the app to load date range reports instantly.
    """
    from logic_local import get_rate, is_receiving

    # Group by customer + storage type + warehouse
    summary = {}
    loc_totals = {}

    # First pass — get total quantity per location for proportional split
    for row in rows:
        loc = row.get("location_name") or "No Active Bin"
        qty = row.get("quantity") or 0
        loc_totals[loc] = loc_totals.get(loc, 0) + qty

    # Second pass — calculate costs
    for row in rows:
        customer     = row.get("customer") or ""
        storage_type = row.get("storage_type") or "No Active Bin"
        location     = row.get("location_name") or "No Active Bin"
        warehouse    = row.get("warehouse") or ""
        qty          = row.get("quantity") or 0
        loc_total    = loc_totals.get(location, 0)

        if location == "No Active Bin" or is_receiving(location):
            cost = 0.0
        else:
            rate       = get_rate(storage_type)
            proportion = (qty / loc_total) if loc_total > 0 else 1.0
            cost       = rate * proportion

        key = f"{customer}||{storage_type}||{warehouse}"
        if key not in summary:
            summary[key] = {
                "customer":     customer,
                "storage_type": storage_type,
                "warehouse":    warehouse,
                "total_cost":   0.0,
                "location_count": 0,
                "sku_count":    0,
            }
        summary[key]["total_cost"]     += cost
        summary[key]["location_count"] += 1 if qty > 0 else 0
        summary[key]["sku_count"]      += 1

    # Load existing history
    s3 = _s3()
    try:
        obj     = s3.get_object(Bucket=SPACES_BUCKET, Key="config/cost_history.json")
        history = json.loads(obj["Body"].read())
    except Exception:
        history = {}

    # Add today's summary
    history[snapshot_date] = {
        "date":    snapshot_date,
        "entries": list(summary.values()),
    }

    # Save back
    s3.put_object(
        Bucket      = SPACES_BUCKET,
        Key         = "config/cost_history.json",
        Body        = json.dumps(history, indent=2).encode("utf-8"),
        ContentType = "application/json",
    )
    print(f"Updated cost_history.json with {len(summary)} entries for {snapshot_date}")


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
        update_cost_history(rows, today)
    except Exception as e:
        print(f"Warning: could not update cost history — {e}")

    try:
        send_summary_email(today, len(rows), size_kb, customers)
    except Exception as e:
        print(f"Warning: could not send summary email — {e}")

    summary = f"Done — {len(rows):,} rows for {today}"
    print(f"=== {summary} ===")
    return {"statusCode": 200, "body": summary}


if __name__ == "__main__":
    main()


def update_cost_history(rows: list[dict], snapshot_date: str):
    """Append today's pre-computed summary to cost_history.json."""
    RATES = {
        "pallet": 2.093, "standard bin": 0.0442, "bin": 0.0442,
        "half pallet": 1.0472, "tractor trailer load floor storage": 52.00,
        "blue bin large": 0.2925, "blue bin medium": 0.1462, "blue bin small": 0.0488,
        "gray bin small": 0.1846, "gray bin medium": 0.2275, "gray bin large": 0.325,
        "pallet tall": 2.7274, "pallet large": 2.652, "pallet medium large": 1.7914,
        "pallet medium small": 1.443, "pallet medium": 1.59, "pallet small large": 0.9581,
        "pallet small": 0.5902, "wall - back": 12.116, "wall - front": 4.4096,
        "pallite - 48": 0.0357, "pallite_16": 0.0537, "pallite_36": 0.0347,
        "pallite_48": 0.0357, "palite_48": 0.0357, "dt - pallet": 2.2074,
        "dt-pallet": 2.2074, "hd": 2.275, "jumbo receiving pallet": 3.90,
        "climate controlled storage room": 1.54, "secure storage room": 32.77,
    }

    def get_rate(st):
        return RATES.get((st or "").strip().lower(), 0.0)

    def is_recv(loc):
        return "receiv" in (loc or "").strip().lower()

    loc_totals = {}
    for row in rows:
        loc = row.get("location_name") or "No Active Bin"
        qty = row.get("quantity") or 0
        loc_totals[loc] = loc_totals.get(loc, 0) + qty

    summary = {}
    for row in rows:
        customer     = row.get("customer") or ""
        storage_type = row.get("storage_type") or "No Active Bin"
        location     = row.get("location_name") or "No Active Bin"
        warehouse    = row.get("warehouse") or ""
        qty          = row.get("quantity") or 0
        loc_total    = loc_totals.get(location, 0)

        if location == "No Active Bin" or is_recv(location):
            cost = 0.0
        else:
            rate       = get_rate(storage_type)
            proportion = (qty / loc_total) if loc_total > 0 else 1.0
            cost       = round(rate * proportion, 4)

        key = f"{customer}||{storage_type}||{warehouse}"
        if key not in summary:
            summary[key] = {
                "customer":       customer,
                "storage_type":   storage_type,
                "warehouse":      warehouse,
                "total_cost":     0.0,
                "location_count": 0,
                "sku_count":      0,
            }
        summary[key]["total_cost"]     = round(summary[key]["total_cost"] + cost, 4)
        summary[key]["location_count"] += 1 if qty > 0 and location != "No Active Bin" else 0
        summary[key]["sku_count"]      += 1

    s3 = _s3()
    try:
        obj     = s3.get_object(Bucket=SPACES_BUCKET, Key="config/cost_history.json")
        history = json.loads(obj["Body"].read())
    except Exception:
        history = {}

    history[snapshot_date] = {
        "date":       snapshot_date,
        "entries":    list(summary.values()),
        "total_rows": len(rows),
    }

    s3.put_object(
        Bucket      = SPACES_BUCKET,
        Key         = "config/cost_history.json",
        Body        = json.dumps(history).encode("utf-8"),
        ContentType = "application/json",
    )
    print(f"Updated cost_history.json for {snapshot_date}")
