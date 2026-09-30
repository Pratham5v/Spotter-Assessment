"""Deterministic employer identities; extracted hints are not accepted locations."""

import re
from collections import Counter

VERSION = "station_inventory_v1"
BRANDS = (
    (r"\bFLYING\s*J\b", "Flying J"),
    (r"\bPILOT\b", "Pilot"),
    (r"\bLOVE['’]?S\b", "Love's"),
    (r"\bKWIK\s+TRIP\b", "Kwik Trip"),
    (r"\bKWIK\s+STAR\b", "Kwik Star"),
    (r"\bSHEETZ\b", "Sheetz"),
    (r"\bCASEY['’]?S\b", "Casey's"),
    (r"\bQUIKTRIP\b", "QuikTrip"),
    (r"\bROAD\s+RANGER\b", "Road Ranger"),
    (r"\bSPEEDWAY\b", "Speedway"),
    (r"\bCIRCLE\s+K\b", "Circle K"),
    (r"\bMAVERIK\b", "Maverik"),
)


def brand_hint(name):
    found = {brand for pattern, brand in BRANDS if re.search(pattern, name, re.I)}
    return sorted(found)


def inventory(audit):
    records = []
    for opis_id, station in sorted(audit.stations.items()):
        fields = station["fields"]
        references = sorted(
            {number for name in station["aliases"] for number in re.findall(r"#\s*(\d+)", name)}
        )
        brands = sorted({b for name in station["aliases"] for b in brand_hint(name)})
        address = fields["Address"]
        records.append(
            {
                "opis_id": opis_id,
                "fingerprint": station["fingerprint"],
                "name": fields["Truckstop Name"],
                "aliases": station["aliases"],
                "brand_hints": brands,
                "possible_branch_references": references,
                "address": address,
                "city": fields["City"],
                "state": fields["State"],
                "address_context": {
                    "has_exit_token": bool(re.search(r"\bexit\b", address, re.I)),
                    "numbered_street_candidate": bool(
                        re.match(r"^\d+\s+", address) and not re.search(r"\bexit\b", address, re.I)
                    ),
                    "note": "Search hints only; no highway, branch or location asserted.",
                },
                "source_row_numbers": [row.number for row in station["observations"]],
                "observation_count": len(station["observations"]),
                "distinct_price_count": station["distinct_prices"],
                "status": "unresolved",
                "reasons": ["location_evidence_not_evaluated"],
            }
        )
    return {
        "source_sha256": audit.sha256,
        "version": VERSION,
        "summary": {
            **audit.summary,
            "identities_with_branch_hint": sum(
                bool(r["possible_branch_references"]) for r in records
            ),
            "conflicting_branch_hints": sum(
                len(r["possible_branch_references"]) > 1 for r in records
            ),
            "brand_counts": dict(
                sorted(Counter(b for r in records for b in r["brand_hints"]).items())
            ),
        },
        "records": records,
    }
