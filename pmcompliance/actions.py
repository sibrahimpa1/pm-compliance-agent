"""Turn audit results into queued drafts. Nothing here sends anything.

Idempotency keys: entity | document type | window
  * vendor reminder / request: the window is the status plus the expiry date
    (a renewed certificate with a new date gets a new reminder; a re-run does not)
  * owner follow-up: the window is the follow-up period (default 7 days), so
    an owner gets at most one nudge per period while items stay open
  * review task: the window is the document's SHA-256 (one review per file)
  * Buildium change: field plus proposed value
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from .buildium import BuildiumAdapter, OwnerRecord, VendorRecord
from .checks import EntityResult, Finding
from .store import Store


def _window(f: Finding) -> str:
    return "%s:%s" % (f.status, f.expiry.isoformat() if f.expiry else "none")


def _vendor_email(rec: VendorRecord, f: Finding) -> Optional[Dict[str, str]]:
    label = f.label
    if f.status == "expiring_soon":
        return {
            "kind": "renewal_reminder",
            "subject": "%s renewal due %s" % (label, f.expiry.isoformat()),
            "body": ("Hello %s team,\n\nThe %s we have on file expires on %s (%d days). "
                     "Please send the renewed document before that date so work orders can keep "
                     "coming to you without interruption.\n\nThank you,\nVendor compliance"
                     % (rec.name, label, f.expiry.strftime("%B %d, %Y"), f.days_left)),
        }
    if f.status == "expired":
        return {
            "kind": "document_request",
            "subject": "%s expired %s - dispatch on hold" % (label, f.expiry.isoformat())
            if f.blocks_dispatch else "%s expired %s" % (label, f.expiry.isoformat()),
            "body": ("Hello %s team,\n\nThe %s we have on file expired on %s. %s"
                     "Please send a current copy.\n\nThank you,\nVendor compliance"
                     % (rec.name, label, f.expiry.strftime("%B %d, %Y"),
                        "New work orders are on hold until we receive it. "
                        if f.blocks_dispatch else "")),
        }
    if f.status == "missing":
        return {
            "kind": "document_request",
            "subject": "%s needed" % label,
            "body": ("Hello %s team,\n\nWe do not have a %s on file for you. %s"
                     "Please reply with a copy.\n\nThank you,\nVendor compliance"
                     % (rec.name, label, "New work orders are on hold until we receive it. "
                        if f.blocks_dispatch else "")),
        }
    return None


def queue_vendor_actions(store: Store, result: EntityResult, rec: VendorRecord) -> List[int]:
    new: List[int] = []
    for f in result.findings:
        store.record_status(rec.entity_id, f.doc_type, f.status)
        if f.status == "compliant":
            continue
        if f.status == "needs_review":
            sha = f.extraction.sha256[:12] if f.extraction else "none"
            i = store.enqueue(
                "%s|%s|needs_review|%s" % (rec.entity_id, f.doc_type, sha), "review_task",
                "internal", rec.entity_id, rec.name, f.doc_type, "compliance team",
                "Review %s for %s" % (f.label, rec.name),
                "Check the %s against the original file and decide: accept, request a corrected "
                "copy, or pause dispatch.\nWhy flagged: %s" % (f.label, "; ".join(f.reasons)))
        else:
            mail = _vendor_email(rec, f)
            i = store.enqueue("%s|%s|%s" % (rec.entity_id, f.doc_type, _window(f)), mail["kind"],
                              "email", rec.entity_id, rec.name, f.doc_type, rec.email,
                              mail["subject"], mail["body"])
        if i:
            new.append(i)

    # Dispatch: paused automatically in our own state (fail closed). Mirroring
    # the hold into Buildium is a proposed change that a person approves.
    if result.dispatch_paused:
        reason = "; ".join("%s %s" % (f.label, f.status) for f in result.findings
                           if f.blocks_dispatch and f.status in ("expired", "missing"))
        store.set_dispatch(rec.entity_id, True, reason)
        if not rec.dispatch_hold:
            change = BuildiumAdapter.propose_change(rec.entity_id, rec.name, "vendor.dispatch_hold",
                                                    "no", "yes", reason)
            i = _queue_change(store, rec, change)
            if i:
                new.append(i)
    else:
        store.set_dispatch(rec.entity_id, False, "required documents valid again")

    # Keep Buildium's dates in step with the documents.
    coi = result.finding("coi")
    if coi and coi.expiry and coi.status in ("compliant", "expiring_soon") and \
            rec.insurance_expiration != coi.expiry:
        change = BuildiumAdapter.propose_change(
            rec.entity_id, rec.name, "vendor.insurance_expiration",
            rec.insurance_expiration.isoformat() if rec.insurance_expiration else None,
            coi.expiry.isoformat(), "Buildium date differs from the certificate on file")
        i = _queue_change(store, rec, change)
        if i:
            new.append(i)
    lic = result.finding("trade_license")
    if lic and lic.expiry and lic.status in ("compliant", "expiring_soon") and \
            rec.license_expiration != lic.expiry:
        change = BuildiumAdapter.propose_change(
            rec.entity_id, rec.name, "vendor.trade_license_expiration",
            rec.license_expiration.isoformat() if rec.license_expiration else None,
            lic.expiry.isoformat(), "Buildium date differs from the licence on file")
        i = _queue_change(store, rec, change)
        if i:
            new.append(i)
    return new


def _queue_change(store: Store, rec: VendorRecord, change: dict) -> Optional[int]:
    how = ("through the API" if change["tier"] == "api"
           else "as a browser step (no API field); operator applies it, then the value is "
                "read back")
    return store.enqueue(
        "%s|%s|%s" % (rec.entity_id, change["field"], change["new"]), "buildium_change",
        "buildium_api" if change["tier"] == "api" else "browser_step", rec.entity_id, rec.name,
        None, "Buildium",
        "Set %s to %s" % (change["field"].split(".", 1)[1], change["new"]),
        "Proposed change %s.\nCurrent: %s\nNew: %s\nWhy: %s\nVerify: %s"
        % (how, change["current"], change["new"], change["reason"], change["verify"]),
        payload=change)


def queue_owner_actions(store: Store, result: EntityResult, rec: OwnerRecord, as_of: date,
                        every_days: int = 7) -> List[int]:
    new: List[int] = []
    outstanding = []
    for f in result.findings:
        store.record_status(rec.entity_id, f.doc_type, f.status)
        if f.status == "missing":
            outstanding.append("%s (not on file)" % f.label)
        elif f.status == "expired":
            outstanding.append("%s (expired %s; please send the current policy)"
                               % (f.label, f.expiry.strftime("%m/%d/%Y")))
        elif f.status == "expiring_soon":
            outstanding.append("%s (renews %s; please send the renewal when issued)"
                               % (f.label, f.expiry.strftime("%m/%d/%Y")))
        elif f.status == "needs_review":
            sha = f.extraction.sha256[:12] if f.extraction else "none"
            i = store.enqueue(
                "%s|%s|needs_review|%s" % (rec.entity_id, f.doc_type, sha), "review_task",
                "internal", rec.entity_id, rec.name, f.doc_type, "onboarding team",
                "Review %s for %s" % (f.label, rec.name),
                "Legal/financial document: a person decides.\nWhy flagged: %s"
                % "; ".join(f.reasons))
            if i:
                new.append(i)
    if outstanding:
        period = date.fromordinal(as_of.toordinal() - as_of.toordinal() % every_days)
        items = "\n".join("  - %s" % o for o in outstanding)
        signature = ",".join(sorted(f.doc_type + ":" + f.status for f in result.findings
                                    if f.status in ("missing", "expired", "expiring_soon")))
        i = store.enqueue(
            "%s|owner_followup|%s|from-%s" % (rec.entity_id, signature, period.isoformat()), "owner_followup",
            "email", rec.entity_id, rec.name, None, rec.email,
            "Documents still needed for your onboarding (%d)" % len(outstanding),
            "Hello %s,\n\nTo finish setting up management of %s we still need:\n%s\n\n"
            "You can reply to this email with the files attached.\n\nThank you,\nOwner onboarding"
            % (rec.name, ", ".join(p.address for p in rec.properties) or "your property", items))
        if i:
            new.append(i)
    return new
