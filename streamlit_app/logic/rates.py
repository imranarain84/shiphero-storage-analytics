# Daily storage rates per location per day.
# Keys are LOWERCASED and STRIPPED — normalization happens in get_rate().
# This means Pallet TALL, Pallet Tall, pallet tall all resolve correctly.

STORAGE_RATES = {
    "pallet":                              2.093,
    "standard bin":                        0.0442,
    "bin":                                 0.0442,
    "half pallet":                         1.0472,
    "tractor trailer load floor storage":  52.00,
    "blue bin large":                      0.2925,
    "blue bin medium":                     0.1462,
    "blue bin small":                      0.0488,
    "gray bin small":                      0.1846,
    "gray bin medium":                     0.2275,
    "gray bin large":                      0.325,
    "pallet tall":                         2.7274,
    "pallet large":                        2.652,
    "pallet medium large":                 1.7914,
    "pallet medium small":                 1.443,
    "pallet medium":                       1.59,
    "pallet small large":                  0.9581,
    "pallet small":                        0.5902,
    "wall - back":                         12.116,
    "wall - front":                        4.4096,
    "pallite - 48":                        0.0357,  # corrected from rate card
    "pallite_16":                          0.0537,
    "pallite_36":                          0.0347,
    "pallite_48":                          0.0357,  # corrected from rate card
    "palite_48":                           0.0357,  # typo variant
    "dt - pallet":                         2.2074,
    "dt-pallet":                           2.2074,
    "hd":                                  2.275,
    "jumbo receiving pallet":              3.90,
    "climate controlled storage room":     1.54,
    "secure storage room":                 32.77,  # $983/month ÷ 30 days
    "no active bin":                       0.0,
}


def get_rate(storage_type: str) -> float:
    """
    Look up the daily rate for a storage type.
    Normalizes by lowercasing and stripping whitespace so minor
    capitalization differences and typos in ShipHero resolve correctly.
    """
    if not storage_type:
        return 0.0
    return STORAGE_RATES.get(storage_type.strip().lower(), 0.0)
