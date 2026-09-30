"""Strict source audit and deterministic price policy; no database or provider I/O."""

import csv
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

HEADERS = [
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
]
US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
CA_PROVINCES = frozenset("AB BC MB NB NL NS NT NU ON PE QC SK YT".split())
PRICE_POLICY = "median_distinct_v1"
NORMALIZATION = "whitespace_case_v1"


class AuditError(ValueError):
    pass


def normalize(text):
    return re.sub(r"\s+", " ", text.strip())


def median_distinct(values):
    values = sorted(set(values))
    if not values or any(not p.is_finite() or p <= 0 for p in values):
        raise AuditError("Prices must be finite and positive")
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


@dataclass(frozen=True)
class SourceRow:
    number: int
    raw: dict
    fields: dict
    price: Decimal
    classification: str


@dataclass(frozen=True)
class AuditedSource:
    sha256: str
    rows: list[SourceRow]
    stations: dict
    summary: dict


def identity_fingerprint(fields):
    import json

    identity = [
        fields["OPIS Truckstop ID"],
        *(fields[k].casefold() for k in ("Address", "City", "State")),
    ]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def audit_csv(path):
    path = Path(path)
    rows, groups = [], defaultdict(list)
    raw_duplicates = Counter()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != HEADERS:
            raise AuditError(f"Required headers in order: {HEADERS}")
        for raw in reader:
            number = reader.line_num
            if None in raw or any(v is None or not normalize(v) for v in raw.values()):
                raise AuditError(f"CSV row {number}: missing fields or incorrect row length")
            fields = {k: normalize(v) for k, v in raw.items()}
            fields["State"] = fields["State"].upper()
            try:
                price = Decimal(fields["Retail Price"])
            except InvalidOperation as exc:
                raise AuditError(f"CSV row {number}: invalid price") from exc
            if not price.is_finite() or price <= 0:
                raise AuditError(f"CSV row {number}: price must be finite and positive")
            if price.as_tuple().exponent < -9 or price >= Decimal("100000000"):
                raise AuditError(f"CSV row {number}: price exceeds supported precision")
            state = fields["State"]
            classification = (
                "US" if state in US_STATES else "CA" if state in CA_PROVINCES else "unsupported"
            )
            if classification == "unsupported":
                raise AuditError(f"CSV row {number}: unrecognized state/province {state}")
            row = SourceRow(number, raw, fields, price, classification)
            rows.append(row)
            raw_duplicates[tuple(raw[k] for k in HEADERS)] += 1
            if classification == "US":
                groups[fields["OPIS Truckstop ID"]].append(row)
    stations = {}
    for opis_id, observations in groups.items():
        addresses = {
            tuple(r.fields[k].casefold() for k in ("Address", "City", "State"))
            for r in observations
        }
        if len(addresses) != 1:
            raise AuditError(
                f"OPIS {opis_id}: conflicting address/city/state; manual resolution required"
            )
        canonical = min(
            observations, key=lambda r: (r.fields["Truckstop Name"].casefold(), r.number)
        )
        prices = sorted({r.price for r in observations})
        stations[opis_id] = {
            "fields": canonical.fields,
            "aliases": sorted({r.fields["Truckstop Name"] for r in observations}),
            "price": median_distinct(prices),
            "min_price": prices[0],
            "max_price": prices[-1],
            "observations": observations,
            "distinct_prices": len(prices),
            "fingerprint": identity_fingerprint(canonical.fields),
        }
    summary = {
        "raw_rows": len(rows),
        "us_rows": sum(r.classification == "US" for r in rows),
        "canadian_rows": sum(r.classification == "CA" for r in rows),
        "unique_ids": len({r.fields["OPIS Truckstop ID"] for r in rows}),
        "us_ids": len(stations),
        "exact_duplicate_rows": sum(n - 1 for n in raw_duplicates.values()),
        "us_ids_multiple_prices": sum(s["distinct_prices"] > 1 for s in stations.values()),
        "us_city_state_pairs": len(
            {
                (r.fields["City"].casefold(), r.fields["State"])
                for r in rows
                if r.classification == "US"
            }
        ),
        "price_policy": PRICE_POLICY,
    }
    return AuditedSource(hashlib.sha256(path.read_bytes()).hexdigest(), rows, stations, summary)
