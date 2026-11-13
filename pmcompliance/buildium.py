"""Buildium adapter with three tiers.

  (a) API client     - primary source. Offline it reads JSON fixtures shaped
                       like API responses (field names approximate the public
                       API; confirm against the client's account in week 1).
  (b) export import  - CSV exports from the Buildium UI. Fills fields the API
                       does not return, and is the fallback when the API is down.
  (c) browser step   - for changes with no API field and no bulk update. It
                       never drives a browser here: it proposes a UI change that
                       a person approves; after it is applied, the value is read
                       back through (a) or (b) and only then marked verified.

The audit reads from (a), falls back to (b), and only *proposes* (c).
Not affiliated with Buildium.
"""
from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from .parsing import parse_date, parse_yes

# Fields this design assumes the API does NOT provide (read or write). Each one
# says where the value comes from instead. Verify per account before a pilot.
API_GAPS: Dict[str, str] = {
    "vendor.trade_license_number": "not in the vendor API response; read from the vendor "
                                   "directory export (custom field)",
    "vendor.trade_license_state": "same as above",
    "vendor.trade_license_expiration": "same as above; updates are proposed as browser steps",
    "vendor.coi_per_occurrence_limit": "not stored in Buildium; read from the COI PDF",
    "vendor.coi_additional_insured": "not stored in Buildium; read from the COI PDF",
    "vendor.w9_on_file": "no flag; derived from the files attached to the vendor",
    "vendor.dispatch_hold": "no API field and no bulk update; proposed as a browser step",
    "property.has_hoa": "custom field, not in the property API response; read from the "
                        "property export",
}

# Fields assumed writable through the API (vendor update endpoint).
API_WRITABLE = {"vendor.insurance_expiration"}

CATEGORY_TO_TRADE = {
    "electrical": "electrical", "electrician": "electrical",
    "plumbing": "plumbing", "plumber": "plumbing",
    "hvac": "hvac", "heating & air": "hvac", "heating and air": "hvac",
    "landscaping": "landscaping", "lawn care": "landscaping",
    "cleaning": "cleaning", "janitorial": "cleaning", "turnover cleaning": "cleaning",
}


class ApiUnavailable(Exception):
    pass


@dataclass
class VendorRecord:
    entity_id: str
    name: str
    trade: str
    email: str
    active: bool
    insurance_expiration: Optional[date] = None
    license_number: str = ""
    license_state: str = ""
    license_expiration: Optional[date] = None
    dispatch_hold: bool = False
    sources: Dict[str, str] = field(default_factory=dict)


@dataclass
class PropertyRecord:
    property_id: str
    address: str
    has_hoa: bool = False
    hoa_name: str = ""


@dataclass
class OwnerRecord:
    entity_id: str
    name: str
    email: str
    properties: List[PropertyRecord] = field(default_factory=list)
    sources: Dict[str, str] = field(default_factory=dict)

    @property
    def has_hoa(self) -> bool:
        return any(p.has_hoa for p in self.properties)


# ------------------------------------------------------------------ tier (a)
class BuildiumApiClient:
    """Reads API-shaped fixtures. A live client would call the REST API with
    the account's client id/secret and page through results."""

    def __init__(self, fixtures_dir: str, available: bool = True) -> None:
        self.fixtures_dir = fixtures_dir
        self.available = available

    def _get(self, name: str) -> list:
        path = os.path.join(self.fixtures_dir, name + ".json")
        if not self.available or not os.path.exists(path):
            raise ApiUnavailable("Buildium API unavailable (%s)" % name)
        with open(path) as fh:
            return json.load(fh)

    def vendors(self) -> list:
        return self._get("vendors")

    def rental_owners(self) -> list:
        return self._get("rental_owners")

    def rental_properties(self) -> list:
        return self._get("rental_properties")


# ------------------------------------------------------------------ tier (b)
def _norm_header(h: str) -> str:
    return " ".join(h.replace("﻿", "").strip().lower().replace("#", "number").split())


def read_export(path: str, columns: Dict[str, str]) -> List[Dict[str, str]]:
    """Parse a Buildium-style CSV export.

    `columns` maps our field name -> the export's column header. Headers are
    matched case- and whitespace-insensitively; a BOM, CRLF line endings,
    quoted commas and blank rows are handled. Missing required columns raise.
    """
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader]
    if not rows:
        return []
    header = [_norm_header(h) for h in rows[0]]
    index = {}
    for ours, theirs in columns.items():
        key = _norm_header(theirs)
        if key not in header:
            raise ValueError("export %s has no column %r" % (os.path.basename(path), theirs))
        index[ours] = header.index(key)
    out = []
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue
        r = r + [""] * (len(header) - len(r))
        out.append({ours: r[i].strip() for ours, i in index.items()})
    return out


VENDOR_EXPORT_COLUMNS = {
    "vendor_id": "Vendor ID", "name": "Vendor Name", "category": "Category", "active": "Active",
    "email": "Email", "license_number": "License #", "license_state": "License State",
    "license_expiration": "License Expiration", "insurance_expiration": "Insurance Expiration",
    "dispatch_hold": "Do Not Dispatch",
}
OWNER_EXPORT_COLUMNS = {"owner_id": "Owner ID", "name": "Owner Name", "email": "Email",
                        "property_ids": "Property IDs"}
PROPERTY_EXPORT_COLUMNS = {"property_id": "Property ID", "address": "Address", "hoa": "HOA",
                           "hoa_name": "HOA Name"}


# ------------------------------------------------------------------ adapter
class BuildiumAdapter:
    def __init__(self, api: BuildiumApiClient, exports_dir: str) -> None:
        self.api = api
        self.exports_dir = exports_dir
        self.notes: List[str] = []

    def _export(self, name: str, columns: Dict[str, str]) -> List[Dict[str, str]]:
        return read_export(os.path.join(self.exports_dir, name), columns)

    def vendors(self) -> List[VendorRecord]:
        export = {r["vendor_id"]: r for r in self._export("vendor_directory.csv",
                                                          VENDOR_EXPORT_COLUMNS)}
        try:
            api_rows = self.api.vendors()
        except ApiUnavailable as exc:
            self.notes.append("%s; vendors read from the CSV export" % exc)
            return [self._vendor_from_export(r) for r in export.values()]
        out = []
        for v in api_rows:
            vid = "V-%d" % v["Id"]
            name = v.get("CompanyName") or ("%s %s" % (v.get("FirstName", ""),
                                                       v.get("LastName", ""))).strip()
            ins = (v.get("VendorInsurance") or {}).get("ExpirationDate")
            rec = VendorRecord(
                entity_id=vid, name=name,
                trade=CATEGORY_TO_TRADE.get(((v.get("Category") or {}).get("Name") or "").lower(),
                                            "unknown"),
                email=v.get("PrimaryEmail") or "", active=bool(v.get("IsActive")),
                insurance_expiration=parse_date(ins),
                sources={"name": "api", "trade": "api", "email": "api", "active": "api",
                         "insurance_expiration": "api"})
            ex = export.get(vid)
            if ex:  # fill API gaps from the export
                rec.license_number = ex["license_number"]
                rec.license_state = ex["license_state"]
                rec.license_expiration = parse_date(ex["license_expiration"])
                rec.dispatch_hold = bool(parse_yes(ex["dispatch_hold"]))
                for k in ("license_number", "license_state", "license_expiration", "dispatch_hold"):
                    rec.sources[k] = "export"
            out.append(rec)
        return out

    @staticmethod
    def _vendor_from_export(r: Dict[str, str]) -> VendorRecord:
        return VendorRecord(
            entity_id=r["vendor_id"], name=r["name"],
            trade=CATEGORY_TO_TRADE.get(r["category"].lower(), "unknown"), email=r["email"],
            active=bool(parse_yes(r["active"])),
            insurance_expiration=parse_date(r["insurance_expiration"]),
            license_number=r["license_number"], license_state=r["license_state"],
            license_expiration=parse_date(r["license_expiration"]),
            dispatch_hold=bool(parse_yes(r["dispatch_hold"])),
            sources={k: "export" for k in ("name", "trade", "email", "active", "license_number",
                                           "license_expiration", "insurance_expiration")})

    def owners(self) -> List[OwnerRecord]:
        props = {r["property_id"]: PropertyRecord(r["property_id"], r["address"],
                                                  bool(parse_yes(r["hoa"])), r["hoa_name"])
                 for r in self._export("property_list.csv", PROPERTY_EXPORT_COLUMNS)}
        try:
            api_owners = self.api.rental_owners()
            api_props = {"P-%d" % p["Id"]: p for p in self.api.rental_properties()}
        except ApiUnavailable as exc:
            self.notes.append("%s; owners read from the CSV export" % exc)
            out = []
            for r in self._export("owner_directory.csv", OWNER_EXPORT_COLUMNS):
                ids = [p.strip() for p in r["property_ids"].split(";") if p.strip()]
                out.append(OwnerRecord(r["owner_id"], r["name"], r["email"],
                                       [props[i] for i in ids if i in props],
                                       {"name": "export", "properties": "export"}))
            return out
        out = []
        for o in api_owners:
            name = o.get("CompanyName") if o.get("IsCompany") else \
                ("%s %s" % (o.get("FirstName", ""), o.get("LastName", ""))).strip()
            plist = []
            for pid in o.get("PropertyIds", []):
                key = "P-%d" % pid
                base = props.get(key) or PropertyRecord(key, "")
                api_p = api_props.get(key, {})
                addr = (api_p.get("Address") or {}).get("AddressLine1") or base.address
                plist.append(PropertyRecord(key, addr, base.has_hoa, base.hoa_name))
            out.append(OwnerRecord("O-%d" % o["Id"], name, o.get("Email") or "", plist,
                                   {"name": "api", "properties": "api", "has_hoa": "export"}))
        return out

    # -------------------------------------------------------------- changes
    @staticmethod
    def propose_change(entity_id: str, entity_name: str, field_name: str,
                       current: Optional[str], new: str, reason: str) -> dict:
        """Describe a change to Buildium. API-writable fields go through the API;
        everything else becomes a browser step that a person approves."""
        tier = "api" if field_name in API_WRITABLE else "browser"
        step = {
            "vendor.dispatch_hold": "set_vendor_do_not_dispatch",
            "vendor.trade_license_expiration": "set_vendor_license_expiration",
        }.get(field_name, "update_field")
        return {"tier": tier, "field": field_name, "current": current, "new": new,
                "reason": reason, "entity_id": entity_id, "entity_name": entity_name,
                "playwright_step": step if tier == "browser" else None,
                "verify": "read back %s after the change; mark done only if it equals %r"
                          % (field_name, new)}

    @staticmethod
    def verify_readback(change: dict, record: VendorRecord) -> bool:
        """True when a fresh read of the record shows the proposed value."""
        attr = change["field"].split(".", 1)[1]
        attr = {"trade_license_expiration": "license_expiration"}.get(attr, attr)
        value = getattr(record, attr, None)
        if isinstance(value, date):
            value = value.isoformat()
        if isinstance(value, bool):
            value = "yes" if value else "no"
        return str(value) == str(change["new"])
