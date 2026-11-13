import os

from conftest import ROOT
from pmcompliance.buildium import (BuildiumAdapter, BuildiumApiClient, VENDOR_EXPORT_COLUMNS,
                                   read_export)

EXPORTS = os.path.join(ROOT, "data", "buildium", "exports")
API = os.path.join(ROOT, "data", "buildium", "api")


def test_csv_import_handles_bom_quotes_and_blank_rows():
    rows = read_export(os.path.join(EXPORTS, "vendor_directory.csv"), VENDOR_EXPORT_COLUMNS)
    assert len(rows) == 10  # trailing blank row skipped
    northgate = next(r for r in rows if r["vendor_id"] == "V-103")
    assert northgate["name"] == "Northgate HVAC Services, Inc."  # quoted comma kept
    assert rows[0]["vendor_id"] == "V-101"  # BOM stripped from the first header


def test_csv_import_rejects_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Vendor ID,Name\nV-1,Acme\n")
    try:
        read_export(str(p), VENDOR_EXPORT_COLUMNS)
    except ValueError as exc:
        assert "Vendor Name" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_api_first_with_gaps_filled_from_export():
    adapter = BuildiumAdapter(BuildiumApiClient(API), EXPORTS)
    v = {r.entity_id: r for r in adapter.vendors()}["V-101"]
    assert v.sources["name"] == "api" and v.sources["license_expiration"] == "export"
    assert v.license_number == "EC-000101"
    assert adapter.notes == []


def test_falls_back_to_export_when_api_is_down():
    adapter = BuildiumAdapter(BuildiumApiClient(API, available=False), EXPORTS)
    vendors = adapter.vendors()
    owners = adapter.owners()
    assert len(vendors) == 10 and all(v.sources["name"] == "export" for v in vendors)
    assert {o.entity_id for o in owners} == {"O-201", "O-202", "O-203", "O-204", "O-205"}
    assert any("unavailable" in n for n in adapter.notes)


def test_change_tiers_and_readback():
    api_change = BuildiumAdapter.propose_change("V-107", "Bluepipe", "vendor.insurance_expiration",
                                                "2026-06-30", "2027-06-30", "stale")
    ui_change = BuildiumAdapter.propose_change("V-103", "Northgate", "vendor.dispatch_hold",
                                               "no", "yes", "COI expired")
    assert api_change["tier"] == "api" and api_change["playwright_step"] is None
    assert ui_change["tier"] == "browser"
    assert ui_change["playwright_step"] == "set_vendor_do_not_dispatch"
    adapter = BuildiumAdapter(BuildiumApiClient(API), EXPORTS)
    rec = {r.entity_id: r for r in adapter.vendors()}["V-103"]
    assert BuildiumAdapter.verify_readback(ui_change, rec) is False  # not applied yet
    rec.dispatch_hold = True
    assert BuildiumAdapter.verify_readback(ui_change, rec) is True
