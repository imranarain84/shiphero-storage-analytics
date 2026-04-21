import os
import json
import gzip
import boto3
from datetime import date, timedelta, datetime

SPACES_KEY      = os.environ["SPACES_KEY"]
SPACES_SECRET   = os.environ["SPACES_SECRET"]
SPACES_BUCKET   = os.environ["SPACES_BUCKET"]
SPACES_REGION   = os.environ.get("SPACES_REGION", "nyc3")
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"


def _client():
    return boto3.client(
        "s3",
        region_name           = SPACES_REGION,
        endpoint_url          = SPACES_ENDPOINT,
        aws_access_key_id     = SPACES_KEY,
        aws_secret_access_key = SPACES_SECRET,
    )


def list_available_dates() -> list[str]:
    try:
        s3   = _client()
        resp = s3.list_objects_v2(Bucket=SPACES_BUCKET, Prefix="inventory/")
        dates = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            d   = key.split("/")[-1].replace(".json.gz", "")
            if len(d) == 10:
                dates.append(d)
        return sorted(dates)
    except Exception:
        return []


def load_snapshot(snapshot_date: str) -> list[dict]:
    s3  = _client()
    key = f"inventory/{snapshot_date}.json.gz"
    try:
        obj      = s3.get_object(Bucket=SPACES_BUCKET, Key=key)
        gz_bytes = obj["Body"].read()
        payload  = gzip.decompress(gz_bytes)
        return json.loads(payload)
    except Exception:
        return []


def load_most_recent_snapshot() -> tuple[str, list[dict]]:
    dates = list_available_dates()
    if not dates:
        return ("", [])
    latest = dates[-1]
    return (latest, load_snapshot(latest))


def load_date_range(start: str, end: str) -> dict[str, list[dict]]:
    available = set(list_available_dates())
    start_d   = date.fromisoformat(start)
    end_d     = date.fromisoformat(end)
    result    = {}
    current   = start_d
    while current <= end_d:
        ds = str(current)
        if ds in available:
            result[ds] = load_snapshot(ds)
        current += timedelta(days=1)
    return result


TAGS_KEY = "config/tracked_tags.json"


def load_tracked_tags() -> dict:
    try:
        s3   = _client()
        obj  = s3.get_object(Bucket=SPACES_BUCKET, Key=TAGS_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return {"tags": [], "last_modified": None, "last_modified_by": None}


def save_tracked_tags(tags: list[str], modified_by: str = "admin") -> bool:
    try:
        s3      = _client()
        payload = json.dumps({
            "tags":             sorted(tags),
            "last_modified":    datetime.utcnow().isoformat(),
            "last_modified_by": modified_by,
        }, indent=2).encode("utf-8")
        s3.put_object(
            Bucket      = SPACES_BUCKET,
            Key         = TAGS_KEY,
            Body        = payload,
            ContentType = "application/json",
        )
        return True
    except Exception as e:
        print(f"Error saving tracked tags: {e}")
        return False