import os
import json
import gzip
import boto3
import pandas as pd
from datetime import date
from io import BytesIO

SPACES_KEY      = os.environ["SPACES_KEY"]
SPACES_SECRET   = os.environ["SPACES_SECRET"]
SPACES_BUCKET   = os.environ["SPACES_BUCKET"]
SPACES_REGION   = os.environ.get("SPACES_REGION", "nyc3")
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"


def _s3():
    return boto3.client(
        "s3",
        region_name           = SPACES_REGION,
        endpoint_url          = SPACES_ENDPOINT,
        aws_access_key_id     = SPACES_KEY,
        aws_secret_access_key = SPACES_SECRET,
    )


def load_latest_csv() -> pd.DataFrame:
    """
    Find and load the most recent ShipHero CSV from Spaces.
    Files are stored under reports/ with names like inventory_YYYY-MM-DD.csv
    """
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
    return pd.read_csv(BytesIO(data))


def csv_to_snapshot_rows(df: pd.DataFrame) -> list[dict]:
    """
    Convert the ShipHero CSV into the snapshot row format
    the Streamlit app expects.
    """
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


def upload_snapshot(rows: list[dict], snapshot_date: str):
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
    print(f"Uploaded {key} ({len(gz_bytes)/1024:.1f} KB, {len(rows):,} rows)")


def main(args: dict = {}) -> dict:
    today = str(date.today())
    print(f"=== Nightly Pull Starting: {today} ===")

    df = load_latest_csv()
    print(f"Loaded {len(df):,} rows from CSV")

    # Only keep rows with actual stock
    df = df[df["Quantity"] > 0]
    print(f"{len(df):,} rows with quantity > 0")

    rows = csv_to_snapshot_rows(df)
    upload_snapshot(rows, today)

    summary = f"Done — {len(rows):,} rows for {today}"
    print(f"=== {summary} ===")
    return {"statusCode": 200, "body": summary}


if __name__ == "__main__":
    main()
