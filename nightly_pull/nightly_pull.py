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

BATCH_SIZE = 12
API_URL    = "https://public-api.shiphero.com/graphql"
HEADERS    = {
    "Authorization": f"Bearer {SHIPHERO_TOKEN}",
    "Content-Type":  "application/json",
}


def _s3():
    return boto3.client(
        "s3",
        region_name           = SPACES_REGION,
        endpoint_url          = SPACES_ENDPOINT,
        aws_access_key_id     = SPACES_KEY,
        aws_secret_access_key = SPACES_SECRET,
    )


def load_tracked_tags() -> set:
    try:
        s3   = _s3()
        obj  = s3.get_object(Bucket=SPACES_BUCKET, Key="config/tracked_tags.json")
        data = json.loads(obj["Body"].read())
        tags = set(data.get("tags", []))
        print(f"Loaded {len(tags)} tracked tags from Spaces")
        return tags
    except Exception as e:
        print(f"WARNING: Could not load tracked_tags.json — {e}")
        return set()


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


def fetch_matching_skus(tracked_tags: set) -> list[dict]:
    matching = []
    cursor   = None
    page_num = 0

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
            resp   = _gql(query)
            if not resp:
                print(f"  Page {page_num}: empty response — retry")
                retries += 1
                time.sleep(10)
                continue

            errors = resp.get("errors", [])
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
                name      = node.get("name", "")
                prod_tags = node.get("tags") or []

                if tracked_tags.intersection(set(prod_tags)):
                    matching.append({
                        "sku":  sku,
                        "name": name,
                        "tags": prod_tags,
                    })

            page = data.get("pageInfo", {})
            if not page.get("hasNextPage"):
                print(f"  Pagination complete — {page_num} pages scanned, "
                      f"{len(matching)} matching SKUs")
                return matching

            cursor = page["endCursor"]
            break

        time.sleep(0.2)

    return matching


def fetch_inventory_batched(skus: list[dict]) -> list[dict]:
    sku_list = [s["sku"] for s in skus]
    sku_meta = {s["sku"]: s for s in skus}
    batches  = [sku_list[i:i+BATCH_SIZE] for i in range(0, len(sku_list), BATCH_SIZE)]
    rows     = []
    total    = len(batches)

    for batch_idx, batch in enumerate(batches):
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
            resp   = _gql(query)
            if not resp:
                print(f"    Empty response — retry")
                retries += 1
                time.sleep(10)
                continue

            errors = resp.get("errors", [])
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
                meta         = sku_meta[sku]

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
                    for wp in wp_list:
                        rows.append({
                            "sku":           sku,
                            "product_name":  meta["name"],
                            "tags":          meta["tags"],
                            "location_name": wp.get("location"),
                            "quantity":      wp.get("on_hand", 0),
                        })
            break

        time.sleep(0.1)

    return rows


def upload_snapshot(rows: list[dict], snapshot_date: str):
    payload  = json.dumps(rows, default=str).encode("utf-8")
    gz_bytes = gzip.compress(payload)
    key      = f"inventory/{snapshot_date}.json.gz"

    s3 = _s3()
    s3.put_object(
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

    tracked_tags = load_tracked_tags()
    if not tracked_tags:
        return {"statusCode": 500, "body": "No tracked tags found — aborting"}

    print("Step 1: Scanning all products for tracked tags...")
    matching_skus = fetch_matching_skus(tracked_tags)
    print(f"Found {len(matching_skus):,} products with tracked tags")

    if not matching_skus:
        return {"statusCode": 200, "body": "No matching products found"}

    print("Step 2: Fetching inventory locations...")
    rows = fetch_inventory_batched(matching_skus)
    print(f"Got {len(rows):,} inventory rows")

    print("Step 3: Uploading snapshot...")
    upload_snapshot(rows, today)

    summary = (
        f"Done — {len(matching_skus):,} products, "
        f"{len(rows):,} inventory rows for {today}"
    )
    print(f"=== {summary} ===")
    return {"statusCode": 200, "body": summary}


if __name__ == "__main__":
    main()