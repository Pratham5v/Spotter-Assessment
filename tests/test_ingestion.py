import csv
from decimal import Decimal

import pytest

from stations.ingestion import HEADERS, AuditError, audit_csv, median_distinct


def source(tmp_path, rows, headers=HEADERS):
    path = tmp_path / "fuel.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def row(price="3", state="TX", address="I-20 EXIT 1"):
    return ["001", " Pilot #1 ", address, "Somewhere  ", state, "002", price]


def test_audit_preserves_duplicates_and_foreign_rows(tmp_path):
    data = audit_csv(source(tmp_path, [row(), row(), row("5"), row("7", "ON")]))
    assert data.summary["exact_duplicate_rows"] == 1
    assert data.summary["us_rows"] == 3 and data.summary["canadian_rows"] == 1
    station = data.stations["001"]
    assert station["price"] == Decimal(4) and station["fields"]["City"] == "Somewhere"
    assert len(station["observations"]) == 3
    assert data.rows[0].number == 2 and data.rows[0].raw["Truckstop Name"] == " Pilot #1 "


@pytest.mark.parametrize("price", ["", "NaN", "Infinity", "-1", "0", "abc"])
def test_bad_prices_are_row_specific(tmp_path, price):
    with pytest.raises(AuditError, match="row 2"):
        audit_csv(source(tmp_path, [row(price)]))


def test_conflicting_identity_is_rejected(tmp_path):
    with pytest.raises(AuditError, match="conflicting"):
        audit_csv(source(tmp_path, [row(), row(address="OTHER ROAD")]))


def test_headers_and_row_lengths(tmp_path):
    with pytest.raises(AuditError, match="headers"):
        audit_csv(source(tmp_path, [], HEADERS[::-1]))
    with pytest.raises(AuditError, match="row 2"):
        audit_csv(source(tmp_path, [row() + ["extra"]]))
    with pytest.raises(AuditError, match="row 2"):
        audit_csv(source(tmp_path, [row()[:-1]]))


def test_distinct_median_and_same_count_changes(tmp_path):
    assert median_distinct(map(Decimal, ["3", "3", "5", "7"])) == 5
    first = audit_csv(source(tmp_path, [row("3")]))
    second = audit_csv(source(tmp_path, [row("4")]))
    assert first.sha256 != second.sha256
    assert first.summary["raw_rows"] == second.summary["raw_rows"]
