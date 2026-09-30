from stations.inventory import brand_hint, inventory


def test_branch_hints_preserve_leading_zeros_and_distinct_aliases():
    from types import SimpleNamespace

    fields = {
        "Truckstop Name": "PILOT #007",
        "Address": "I-20 EXIT 3",
        "City": "Town",
        "State": "TX",
    }
    audit = SimpleNamespace(
        sha256="source",
        summary={},
        stations={
            "a": {
                "fields": fields,
                "aliases": ["PILOT #007", "PILOT #7"],
                "fingerprint": "identity",
                "observations": [SimpleNamespace(number=2)],
                "distinct_prices": 1,
            }
        },
    )
    result = inventory(audit)
    record = result["records"][0]
    assert record["possible_branch_references"] == ["007", "7"]
    assert record["aliases"] == audit.stations["a"]["aliases"]
    assert record["fingerprint"] == "identity"
    assert record["status"] == "unresolved"
    assert result["summary"]["conflicting_branch_hints"] == 1


def test_operator_token_boundaries_do_not_match_unrelated_names():
    assert brand_hint("PILOT #388") == ["Pilot"]
    assert brand_hint("PILOT POINT FUEL") == ["Pilot"]  # A hint, never acceptance.
    assert brand_hint("AUTOPILOT MART") == []
    assert brand_hint("LOVE’S TRAVEL STOP #003") == ["Love's"]
