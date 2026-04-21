STORAGE_RATES = {
    "Pallet":                              2.093,
    "Standard Bin":                        0.0442,
    "Bin":                                 0.0442,
    "Half Pallet":                         1.0472,
    "Tractor Trailer Load Floor Storage":  52.00,
    "Blue Bin Large":                      0.2925,
    "Blue Bin Medium":                     0.1462,
    "Blue Bin Small":                      0.0488,
    "Gray Bin Small":                      0.1846,
    "Gray Bin Medium":                     0.2275,
    "Gray Bin Large":                      0.325,
    "Pallet Tall":                         2.7274,
    "Pallet Large":                        2.652,
    "Pallet Medium Large":                 1.7914,
    "Pallet Medium Small":                 1.443,
    "Pallet Small Large":                  0.9581,
    "Pallet Small":                        0.5902,
    "Wall - Back":                         12.116,
    "Wall - Front":                        4.4096,
    "Pallite - 48":                        0.0572,
    "Pallite_16":                          0.0537,
    "Pallite_48":                          0.0357,
    "DT - Pallet":                         2.2074,
    "DT-Pallet":                           2.2074,
    "HD":                                  2.275,
    "Jumbo Receiving Pallet":              3.90,
    "No Active Bin":                       0.0,
}


def get_rate(storage_type: str) -> float:
    return STORAGE_RATES.get(storage_type, 0.0)