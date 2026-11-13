"""The audit pipeline: directory -> documents -> extraction -> checks -> queue."""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

from . import actions
from .buildium import BuildiumAdapter, BuildiumApiClient, OwnerRecord, VendorRecord
from .checks import EntityResult, evaluate, load_requirements, required_docs
from .extract import Extraction, extract
from .store import Store

def _root() -> str:
    """Repo root: $PMC_ROOT, else the folder holding the package (editable
    install or checkout), else the current directory."""
    env = os.environ.get("PMC_ROOT")
    if env:
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return here if os.path.isdir(os.path.join(here, "data")) else os.getcwd()


REPO_ROOT = _root()


@dataclass
class Paths:
    data: str = os.path.join(REPO_ROOT, "data")
    config: str = os.path.join(REPO_ROOT, "config", "requirements.json")
    out: str = os.path.join(REPO_ROOT, "out")

    @property
    def docs(self) -> str:
        return os.path.join(self.data, "docs")

    @property
    def fixtures(self) -> str:
        return os.path.join(self.data, "fixtures")

    @property
    def api(self) -> str:
        return os.path.join(self.data, "buildium", "api")

    @property
    def exports(self) -> str:
        return os.path.join(self.data, "buildium", "exports")

    @property
    def db(self) -> str:
        return os.path.join(self.out, "state.db")

    @property
    def outbox(self) -> str:
        return os.path.join(self.out, "outbox.jsonl")


@dataclass
class AuditRun:
    as_of: date
    mode: str
    vendors: List[Tuple[VendorRecord, EntityResult]] = field(default_factory=list)
    owners: List[Tuple[OwnerRecord, EntityResult]] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    new_items: List[int] = field(default_factory=list)


def documents_for(paths: Paths, entity_id: str) -> List[str]:
    """Files attached to the entity (in Buildium: the vendor/owner Files tab)."""
    return sorted(glob.glob(os.path.join(paths.docs, entity_id, "*.pdf")))


def run_audit(paths: Paths, store: Store, as_of: Optional[date] = None, mode: str = "offline",
              api_available: bool = True, record: bool = False) -> AuditRun:
    as_of = as_of or date.today()
    req = load_requirements(paths.config)
    adapter = BuildiumAdapter(BuildiumApiClient(paths.api, available=api_available),
                              paths.exports)
    run = AuditRun(as_of=as_of, mode=mode)
    store.log("audit", "run_started", None, "as_of=%s mode=%s" % (as_of.isoformat(), mode))

    def extract_all(entity_id: str) -> List[Extraction]:
        return [extract(p, paths.fixtures, mode=mode, record=record)
                for p in documents_for(paths, entity_id)]

    for rec in adapter.vendors():
        if not rec.active:
            run.skipped.append("%s %s (inactive in Buildium)" % (rec.entity_id, rec.name))
            continue
        try:
            needed = required_docs(req, "vendor", trade=rec.trade)
        except KeyError:
            run.skipped.append("%s %s (no requirements for trade %r)"
                               % (rec.entity_id, rec.name, rec.trade))
            continue
        result = evaluate("vendor", rec.entity_id, rec.name, rec.email, rec.trade, needed,
                          extract_all(rec.entity_id), req, as_of)
        run.new_items += actions.queue_vendor_actions(store, result, rec)
        run.vendors.append((rec, result))

    for owner in adapter.owners():
        needed = required_docs(req, "owner", has_hoa=owner.has_hoa)
        detail = "; ".join(p.address.split(",")[0] + (" (HOA)" if p.has_hoa else "")
                           for p in owner.properties)
        result = evaluate("owner", owner.entity_id, owner.name, owner.email, detail, needed,
                          extract_all(owner.entity_id), req, as_of)
        run.new_items += actions.queue_owner_actions(
            store, result, owner, as_of, req.get("owner_followup_every_days", 7))
        run.owners.append((owner, result))

    run.notes = adapter.notes
    store.log("audit", "run_finished", None, "%d vendors, %d owners, %d new queue items"
              % (len(run.vendors), len(run.owners), len(run.new_items)))
    return run
