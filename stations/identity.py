"""Conservative operator name and branch-reference parsing."""

import re

BRANDS = [
    ("FLYING J", "Flying J"),
    ("PILOT", "Pilot"),
    ("LOVES", "Love's"),
    ("CASEYS", "Casey's"),
    ("ROAD RANGER", "Road Ranger"),
    ("7ELEVEN", "7-Eleven"),
    ("CIRCLE K", "Circle K"),
    ("ALLSUPS", "Allsup's"),
]


def words(text):
    return re.sub(r"[^a-z0-9 ]", "", text.casefold())


def station_name(name):
    clean = words(name).upper()
    brand = next(
        (replacement for token, replacement in BRANDS if token in clean),
        re.sub(r"\s*#.*$", "", name).strip(),
    )
    number = re.search(r"#\s*(\d+)", name)
    return brand, number.group(1) if number else None
