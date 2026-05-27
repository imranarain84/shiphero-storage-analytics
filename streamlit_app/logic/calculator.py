import pandas as pd
from logic.rates import get_rate


def is_receiving_location(location_name: str) -> bool:
    """Receiving locations are not billed for storage."""
    if not location_name:
        return False
    return "receiv" in location_name.strip().lower()


def calculate_costs(rows: list[dict], num_days: int) -> pd.DataFrame:
    """
    Calculate storage costs from snapshot rows.
    Rates are charged per occupied location.
    When multiple SKUs share the same location, the cost is split
    proportionally by quantity across all SKUs in that location.
    """
    if not rows:
        return pd.DataFrame()

    # Build a DataFrame for easier grouping
    df = pd.DataFrame(rows)

    # Normalize location and storage type
    df["location_name"] = df["location_name"].fillna("No Active Bin")
    df["storage_type"]  = df["storage_type"].fillna("No Active Bin")
    df["location_name"] = df["location_name"].apply(
        lambda x: "No Active Bin" if str(x).strip().lower() in ("nan", "none", "") else str(x).strip()
    )
    df["storage_type"] = df["storage_type"].apply(
        lambda x: "No Active Bin" if str(x).strip().lower() in ("nan", "none", "") else str(x).strip()
    )

    # Calculate total quantity per location for proportional splitting
    loc_totals = df.groupby("location_name")["quantity"].sum().rename("loc_total_qty")
    df = df.join(loc_totals, on="location_name")

    records = []
    for _, row in df.iterrows():
        location_name = row["location_name"]
        storage_type  = row["storage_type"]
        qty           = row["quantity"] or 0
        loc_total_qty = row["loc_total_qty"] or 0

        if is_receiving_location(location_name) or location_name == "No Active Bin":
            rate = 0.0
            cost = 0.0
        else:
            rate = get_rate(storage_type)
            # Split cost proportionally if multiple SKUs share this location
            if loc_total_qty > 0 and qty > 0:
                proportion = qty / loc_total_qty
            else:
                proportion = 1.0
            cost = rate * proportion * num_days

        records.append({
            "SKU":          row.get("sku", ""),
            "Product Name": row.get("product_name", ""),
            "Customer":     row.get("customer", ""),
            "Tags":         ", ".join(row.get("tags") or []),
            "Location":     location_name,
            "Storage Type": storage_type,
            "Warehouse":    row.get("warehouse", ""),
            "Quantity":     qty,
            "Daily Rate":   rate,
            "Days":         num_days,
            "Total Cost":   round(cost, 2),
        })

    return pd.DataFrame(records)
