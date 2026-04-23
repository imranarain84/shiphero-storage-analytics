import os
import json
import gzip
import time
import boto3
import requests
from datetime import date, datetime

SHIPHERO_TOKEN  = os.environ["SHIPHERO_TOKEN"]
SPACES_KEY      = os.environ["SPACES_KEY"]
SPACES_SECRET   = os.environ["SPACES_SECRET"]
SPACES_BUCKET   = os.environ["SPACES_BUCKET"]
SPACES_REGION   = os.environ.get("SPACES_REGION", "nyc3")
SPACES_ENDPOINT = f"https://{SPACES_REGION}.digitaloceanspaces.com"

BATCH_SIZE      = 12
API_URL         = "https://public-api.shiphero.com/graphql"
HEADERS         = {
    "Authorization": f"Bearer {SHIPHERO_TOKEN}",
    "Content-Type":  "application/json",
}

KNOWN_SKUS_KEY  = "config/known_skus.json"
CHECKPOINT_KEY  = "config/sku_scan_checkpoint.json"


# ── Spaces client ─────────────────────────────────────────────────────────────
def _s3():
    return boto3.client(
        "s3",
        region_name           = SPACES_REGION,
        endpoint_url          = SPACES_ENDPOINT,
        aws_access_key_id     = SPACES_KEY,
        aws_secret_access_key = SPACES_SECRET,
    )


def _s3_get(key: str) -> dict:
    try:
        obj = _s3().get_object(Bucket=SPACES_BUCKET, Key=key)
        return json.loads(obj["Body"].read())
    except Exception:
        return {}


def _s3_put(key: str, data: dict):
    _s3().put_object(
        Bucket      = SPACES_BUCKET,
        Key         = key,
        Body        = json.dumps(data, indent=2).encode("utf-8"),
        ContentType = "application/json",
    )


# ── GraphQL helper ────────────────────────────────────────────────────────────
def _gql(query: str, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            resp = requests.post(
                API_URL,
                json    = {"query": query},
                headers = HEADERS,
                timeout = 120,
            )
            return resp.json()
        except requests.exceptions.ReadTimeout:
            print(f"    Request timed out — retry {attempt+1}/{retries}")
            time.sleep(10)
        except Exception as e:
            print(f"    Request error: {e} — retry {attempt+1}/{retries}")
            time.sleep(10)
    return {}


# ── Load config ───────────────────────────────────────────────────────────────
def load_tracked_tags() -> set:
    data = _s3_get("config/tracked_tags.json")
    tags = set(data.get("tags", []))
    print(f"Loaded {len(tags)} tracked tags")
    return tags


def load_known_skus() -> dict:
    """Returns {sku: {name, tags}} for all previously discovered SKUs."""
    data = _s3_get(KNOWN_SKUS_KEY)
    skus = data.get("skus", {})
    print(f"Loaded {len(skus):,} known SKUs from Spaces")
    return skus


def save_known_skus(skus: dict):
    _s3_put(KNOWN_SKUS_KEY, {
        "skus":         skus,
        "last_updated": datetime.utcnow().isoformat(),
        "count":        len(skus),
    })
    print(f"Saved {len(skus):,} known SKUs to Spaces")


def load_checkpoint() -> dict:
    return _s3_get(CHECKPOINT_KEY)


def save_checkpoint(cursor: str, found: dict):
    _s3_put(CHECKPOINT_KEY, {
        "cursor":     cursor,
        "found":      found,
        "saved_at":   datetime.utcnow().isoformat(),
    })


def clear_checkpoint():
    try:
        _s3().delete_object(Bucket=SPACES_BUCKET, Key=CHECKPOINT_KEY)
    except Exception:
        pass


# ── Phase 1: Weekly SKU Discovery (with checkpoint/resume) ───────────────────
def weekly_sku_scan(tracked_tags: set) -> dict:
    """
    Scans ALL products to find ones with tracked tags.
    Saves progress every 50 pages so it can resume if interrupted.
    Returns {sku: {name, tags}} dict.
    """
    # Check for existing checkpoint
    checkpoint  = load_checkpoint()
    cursor      = checkpoint.get("cursor")
    found       = checkpoint.get("found", {})
    page_num    = 0

    if cursor:
        print(f"  Resuming from checkpoint — {len(found):,} SKUs found so far")
    else:
        print("  Starting fresh scan...")

    while True:
        page_num += 1
        after = f', after: "{cursor}"' if cursor else ""

        query = f"""
        query {{
          products {{
            data(first: 100{after}) {{
              edges {{
                node {{
                  sku
                  name
                  tags
                }}
              }}
              pageInfo {{
                hasNextPage
                endCursor
              }}
            }}
          }}
        }}
        """

        retries = 0
        while retries < 5:
            resp = _gql(query)
            if not resp:
                print(f"  Page {page_num}: empty response — retry")
                retries += 1
                time.sleep(10)
                continue

            errors    = resp.get("errors", [])
            throttled = any(
                "credit" in str(e).lower() or "complexity" in str(e).lower()
                for e in errors
            )
            if throttled:
                print(f"  Page {page_num}: throttled — waiting 15s")
                time.sleep(15)
                retries += 1
                continue

            data = (
                resp.get("data", {})
                    .get("products", {})
                    .get("data", {})
            )

            for edge in data.get("edges", []):
                node      = edge["node"]
                sku       = node.get("sku", "")
                prod_tags = node.get("tags") or []
                if tracked_tags.intersection(set(prod_tags)):
                    found[sku] = {
                        "name": node.get("name", ""),
                        "tags": prod_tags,
                    }

            page_info = data.get("pageInfo", {})

            # Save checkpoint every 50 pages
            if page_num % 50 == 0:
                print(f"  Page {page_num}: checkpoint saved — {len(found):,} matches so far")
                save_checkpoint(page_info.get("endCursor", ""), found)

            if not page_info.get("hasNextPage"):
                print(f"  Scan complete — {page_num} pages, {len(found):,} matching SKUs")
                clear_checkpoint()
                return found

            cursor = page_info["endCursor"]
            break

        time.sleep(0.2)

    return found


# ── Phase 2: Nightly Inventory Pull ──────────────────────────────────────────
def fetch_inventory_batched(skus: dict) -> list[dict]:
    """
    Fetch inventory for known SKUs only.
    Only includes rows where quantity > 0.
    """
    sku_list = list(skus.keys())
    batches  = [sku_list[i:i+BATCH_SIZE] for i in range(0, len(sku_list), BATCH_SIZE)]
    rows     = []
    total    = len(batches)

    for batch_idx, batch in enumerate(batches):
        if batch_idx % 50 == 0:
            print(f"  Inventory batch {batch_idx+1}/{total}")

        aliases = "\n".join([
            f"""
            s{i}: product(sku: "{sku}") {{
              sku
              inventory {{
                warehouse_products {{
                  location
                  on_hand
                }}
              }}
            }}
            """
            for i, sku in enumerate(batch)
        ])
        query = f"query BatchInv {{\n{aliases}\n}}"

        retries = 0
        while retries < 5:
            resp = _gql(query)
            if not resp:
                retries += 1
                time.sleep(10)
                continue

            errors    = resp.get("errors", [])
            throttled = any(
                "credit" in str(e).lower() or "complexity" in str(e).lower()
                for e in errors
            )
            if throttled:
                print(f"    Throttled — waiting 15s")
                time.sleep(15)
                retries += 1
                continue

            for key, product in (resp.get("data") or {}).items():
                idx_in_batch = int(key[1:])
                sku          = batch[idx_in_batch]
                meta         = skus[sku]

                if not product:
                    rows.append({
                        "sku":           sku,
                        "product_name":  meta["name"],
                        "tags":          meta["tags"],
                        "location_name": None,
                        "quantity":      0,
                    })
                    continue

                wp_list = (
                    product.get("inventory", {})
                           .get("warehouse_products") or []
                )

                if not wp_list:
                    rows.append({
                        "sku":           sku,
                        "product_name":  meta["name"],
                        "tags":          meta["tags"],
                        "location_name": None,
                        "quantity":      0,
                    })
                else:
                    has_stock = False
                    for wp in wp_list:
                        qty = wp.get("on_hand", 0) or 0
                        if qty > 0:
                            has_stock = True
                            rows.append({
                                "sku":           sku,
                                "product_name":  meta["name"],
                                "tags":          meta["tags"],
                                "location_name": wp.get("location"),
                                "quantity":      qty,
                            })
                    if not has_stock:
                        rows.append({
                            "sku":           sku,
                            "product_name":  meta["name"],
                            "tags":          meta["tags"],
                            "location_name": None,
                            "quantity":      0,
                        })
            break

        time.sleep(0.1)

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


# ── Entry points ──────────────────────────────────────────────────────────────
def run_weekly_scan(args: dict = {}) -> dict:
    """
    Weekly job: discover all SKUs with tracked tags.
    Saves to known_skus.json. Supports checkpoint/resume.
    """
    print(f"=== Weekly SKU Scan Starting: {date.today()} ===")
    tracked_tags = load_tracked_tags()
    if not tracked_tags:
        return {"statusCode": 500, "body": "No tracked tags"}

    known_skus = weekly_sku_scan(tracked_tags)
    save_known_skus(known_skus)

    # Also run inventory pull for today after scan completes
    print("Running inventory pull for today...")
    rows = fetch_inventory_batched(known_skus)
    upload_snapshot(rows, str(date.today()))

    summary = f"Weekly scan done — {len(known_skus):,} SKUs, {len(rows):,} inventory rows"
    print(f"=== {summary} ===")
    return {"statusCode": 200, "body": summary}


def run_nightly_pull(args: dict = {}) -> dict:
    """
    Nightly job: fetch inventory for known SKUs only.
    Fast — skips the full product scan.
    """
    print(f"=== Nightly Pull Starting: {date.today()} ===")

    known_skus = load_known_skus()
    if not known_skus:
        print("No known SKUs found — running full scan instead")
        return run_weekly_scan()

    print(f"Fetching inventory for {len(known_skus):,} known SKUs...")
    rows = fetch_inventory_batched(known_skus)
    print(f"Got {len(rows):,} inventory rows")

    upload_snapshot(rows, str(date.today()))

    summary = f"Done — {len(known_skus):,} SKUs, {len(rows):,} rows for {date.today()}"
    print(f"=== {summary} ===")
    return {"statusCode": 200, "body": summary}


def main(args: dict = {}) -> dict:
    mode = os.environ.get("PULL_MODE", "nightly")
    if mode == "weekly":
        return run_weekly_scan(args)
    else:
        return run_nightly_pull(args)


if __name__ == "__main__":
    main()