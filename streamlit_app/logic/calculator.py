import pandas as pd
from logic.rates import get_rate


def calculate_costs(rows: list[dict], num_days: int) -> pd.DataFrame:
    """
    Calculate storage costs from snapshot rows.
    storage_type comes directly from the ShipHero CSV so no location
    lookup is needed.
    """
    records = []
    for row in rows:
        storage_type = row.get("storage_type") or "No Active Bin"
        rate         = get_rate(storage_type)
        qty          = row.get("quantity") or 0
        cost         = rate * qty * num_days

        records.append({
            "SKU":          row.get("sku", ""),
            "Product Name": row.get("product_name", ""),
            "Customer":     row.get("customer", ""),
            "Tags":         ", ".join(row.get("tags") or []),
            "Location":     row.get("location_name") or "No Active Bin",
            "Storage Type": storage_type,
            "Warehouse":    row.get("warehouse", ""),
            "Quantity":     qty,
            "Daily Rate":   rate,
            "Days":         num_days,
            "Total Cost":   cost,
        })

    return pd.DataFrame(records)
