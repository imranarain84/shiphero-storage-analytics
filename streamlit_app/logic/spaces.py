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


def _s3_get(key: str) -> dict:
    try:
        obj = _client().get_object(Bucket=SPACES_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        return {}


def _s3_put(key: str, data: dict):
    _client().put_object(
        Bucket      = SPACES_BUCKET,
        Key         = key,
        Body        = json.dumps(data, indent=2).encode("utf-8"),
        ContentType = "application/json",
    )


# ── Snapshot helpers ──────────────────────────────────────────────────────────
def list_available_dates() -> list[str]:
    try:
        resp  = _client().list_objects_v2(Bucket=SPACES_BUCKET, Prefix="inventory/")
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
    try:
        obj      = _client().get_object(
            Bucket=SPACES_BUCKET,
            Key=f"inventory/{snapshot_date}.json.gz"
        )
        gz_bytes = obj["Body"].read()
        payload  = gzip.decompress(gz_bytes)
        return json.loads(payload)
    except Exception:
        return []


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


# ── User management ───────────────────────────────────────────────────────────
USERS_KEY = "config/users.json"


def load_users() -> dict:
    data = _s3_get(USERS_KEY)
    return data.get("users", {})


def save_users(users: dict):
    _s3_put(USERS_KEY, {
        "users":        users,
        "last_updated": datetime.utcnow().isoformat(),
    })


def authenticate(username: str, password: str) -> dict | None:
    """
    Returns the user dict if credentials are valid, None otherwise.
    """
    users = load_users()
    user  = users.get(username.strip().lower())
    if not user:
        return None
    if user.get("password") != password:
        return None
    return user


def get_all_customers(snapshot_date: str) -> list[str]:
    """Return sorted list of all 3PL customers in the latest snapshot."""
    rows = load_snapshot(snapshot_date)
    return sorted(set(r.get("customer", "") for r in rows if r.get("customer")))
