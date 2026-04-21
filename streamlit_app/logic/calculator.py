import pandas as pd
from logic.rates import get_rate


def calculate_costs(
    rows: list[dict],
    num_days: int,
    loc_type_map: dict[str, str],
) -> pd.DataFrame:
    records = []
    for row in rows:
        loc          = row.get("location_name") or "No Active Bin"
        storage_type = loc_type_map.get(loc, "No Active Bin")
        rate         = get_rate(storage_type)
        qty          = row.get("quantity") or 0
        cost         = rate * qty * num_days

        records.append({
            "SKU":          row.get("sku", ""),
            "Product Name": row.get("product_name", ""),
            "Tags":         ", ".join(row.get("tags") or []),
            "Location":     loc,
            "Storage Type": storage_type,
            "Quantity":     qty,
            "Daily Rate":   rate,
            "Days":         num_days,
            "Total Cost":   cost,
        })

    return pd.DataFrame(records)