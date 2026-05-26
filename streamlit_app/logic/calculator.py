import pandas as pd
from logic.rates import get_rate


def is_receiving_location(location_name: str) -> bool:
    """Receiving locations are not billed for storage."""
    if not location_name:
        return False
    return "receiv" in location_name.strip().lower()


def calculate_costs(rows: list[dict], num_days: int) -> pd.DataFrame:
    records = []
    for row in rows:
        storage_type  = row.get("storage_type") or "No Active Bin"
        location_name = row.get("location_name") or "No Active Bin"
        qty           = row.get("quantity") or 0

        if is_receiving_location(location_name):
            rate = 0.0
        else:
            rate = get_rate(storage_type)

        cost = rate * qty * num_days

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
            "Total Cost":   cost,
        })

    return pd.DataFrame(records)
