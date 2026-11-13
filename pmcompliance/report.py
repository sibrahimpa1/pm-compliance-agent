"""Render the audit as one self-contained HTML file (no external assets)."""
from __future__ import annotations

import html
import json
from typing import List, Optional

from .checks import EntityResult, Finding
from .pipeline import AuditRun
from .store import Store

PILL_TEXT = {"compliant": "Compliant", "expiring_soon": "Expiring soon", "expired": "Expired",
             "missing": "Missing", "needs_review": "Needs review", "pending": "Pending approval",
             "approved": "Approved", "rejected": "Rejected", "sent": "Sent (stub)",
             "na": "Not required"}

KIND_TEXT = {"renewal_reminder": "Renewal reminder", "document_request": "Document request",
             "owner_followup": "Owner follow-up", "review_task": "Review task",
             "buildium_change": "Buildium change"}

CSS = """
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--bg:#f8fafc;--card:#fff;
--green:#15803d;--green-bg:#dcfce7;--amber:#b45309;--amber-bg:#fef3c7;--red:#b91c1c;
--red-bg:#fee2e2;--rose:#be123c;--rose-bg:#ffe4e6;--violet:#6d28d9;--violet-bg:#ede9fe;
--slate-bg:#f1f5f9;--blue:#1d4ed8;--blue-bg:#dbeafe}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1320px;margin:0 auto;padding:28px 32px 48px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;
border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:22px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:16px;margin:30px 0 4px}
.sub{color:var(--muted);margin:0}
.meta{color:var(--muted);text-align:right;font-size:13px}
.meta b{color:var(--ink);font-weight:600}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .n{font-size:26px;font-weight:650;letter-spacing:-.02em}
.card .l{color:var(--muted);font-size:13px}
.hint{color:var(--muted);font-size:13px;margin:0 0 10px}
table{width:100%;border-collapse:separate;border-spacing:0;background:var(--card);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{background:var(--slate-bg);color:#334155;text-align:left;font-size:12px;font-weight:600;
text-transform:uppercase;letter-spacing:.04em;padding:9px 12px;border-bottom:1px solid var(--line)}
td{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.name{font-weight:600}
.small{font-size:12px;color:var(--muted)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:#475569}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;
white-space:nowrap}
.compliant,.sent{background:var(--green-bg);color:var(--green)}
.expiring_soon,.pending{background:var(--amber-bg);color:var(--amber)}
.expired{background:var(--red-bg);color:var(--red)}
.missing{background:var(--rose-bg);color:var(--rose)}
.needs_review{background:var(--violet-bg);color:var(--violet)}
.approved{background:var(--blue-bg);color:var(--blue)}
.rejected,.na{background:var(--slate-bg);color:var(--muted)}
.why{font-size:12px;color:#475569;margin-top:4px;max-width:260px}
.paused{display:inline-block;background:var(--red);color:#fff;border-radius:6px;padding:2px 8px;
font-size:12px;font-weight:600}
.active{color:var(--green);font-size:12px;font-weight:600}
.quote{border-left:3px solid var(--line);padding:2px 0 2px 10px;margin:4px 0;font-size:12.5px}
.quote .src{color:var(--muted);font-size:11.5px}
.ok{color:var(--green)} .warn{color:var(--amber)}
details{margin-top:10px} summary{cursor:pointer;color:var(--blue);font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
footer{margin-top:34px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);
padding-top:14px}
"""


def e(s: object) -> str:
    return html.escape("" if s is None else str(s))


def pill(status: str) -> str:
    return '<span class="pill %s">%s</span>' % (e(status), e(PILL_TEXT.get(status, status)))


def doc_cell(f: Optional[Finding]) -> str:
    if f is None:
        return pill("na")
    out = [pill(f.status)]
    if f.expiry:
        out.append('<div class="small">exp. %s</div>' % e(f.expiry.isoformat()))
    if f.extraction and f.extraction.route == "vision":
        out.append('<div class="small">read from scan</div>')
    if f.status != "compliant" and f.reasons:
        out.append('<div class="why">%s</div>' % e("; ".join(f.reasons)))
    return "".join(out)


def _evidence_rows(results: List[EntityResult]) -> str:
    rows = []
    for res in results:
        for f in res.findings:
            if f.status == "compliant" or not f.extraction:
                continue
            ex = f.extraction
            keys = [k for k in ("insured_name", "legal_name", "licensee_name", "owner_name",
                                "expiry_date", "per_occurrence_limit", "additional_insured",
                                "signature") if k in ex.fields]
            quotes = []
            for k in keys:
                fld = ex.fields[k]
                check = ('<span class="ok">&#10003; found in text</span>' if fld.verified
                         else '<span class="warn">not checkable (scan)</span>'
                         if fld.verified is None else '<span class="warn">not found</span>')
                quotes.append('<div class="quote">&ldquo;%s&rdquo;<div class="src">%s &middot; '
                              'page %d &middot; confidence %.2f &middot; %s</div></div>'
                              % (e(fld.line), e(k), fld.page, fld.confidence, check))
            rows.append("<tr><td><div class='name'>%s</div><div class='small'>%s</div></td>"
                        "<td>%s<div class='small'>%s</div></td><td>%s</td><td>%s</td></tr>"
                        % (e(res.name), e(res.entity_id), e(f.label),
                           e(ex.path.split("/data/")[-1]), pill(f.status), "".join(quotes)))
    return "".join(rows)


def _all_fields(results: List[EntityResult]) -> str:
    rows = []
    for res in results:
        for f in res.findings:
            if not f.extraction:
                continue
            for k, fld in sorted(f.extraction.fields.items()):
                rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='mono'>"
                            "p.%d &middot; %.2f &middot; %s</td></tr>"
                            % (e(res.entity_id), e(f.label), e(k), e(fld.value), fld.page,
                               fld.confidence, e(f.extraction.extractor)))
    return "".join(rows)


def render(run: AuditRun, store: Store) -> str:
    vendors = [r for _rec, r in run.vendors]
    owners = [r for _rec, r in run.owners]
    queue = store.items()
    pending = sum(1 for q in queue if q["status"] == "pending")

    v_rows = []
    for rec, res in run.vendors:
        dispatch = ('<span class="paused">Dispatch paused</span>' if res.dispatch_paused
                    else '<span class="active">Active</span>')
        v_rows.append(
            "<tr><td><div class='name'>%s</div><div class='small'>%s &middot; %s</div></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (e(res.name), e(res.entity_id), e(res.detail.upper() if res.detail == "hvac"
                                                else res.detail.title()),
               pill(res.status), doc_cell(res.finding("coi")), doc_cell(res.finding("w9")),
               doc_cell(res.finding("trade_license")), dispatch))

    o_rows = []
    for rec, res in run.owners:
        needed = [f.label for f in res.findings if f.status in ("missing", "expired",
                                                                "expiring_soon")]
        needed_html = ("<br>".join(e(n) for n in needed) if needed
                       else '<span class="small">Nothing</span>')
        o_rows.append(
            "<tr><td><div class='name'>%s</div><div class='small'>%s &middot; %s</div></td>"
            "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (e(res.name), e(res.entity_id), e(res.detail), pill(res.status),
               doc_cell(res.finding("w9")), doc_cell(res.finding("landlord_insurance")),
               doc_cell(res.finding("management_agreement")),
               doc_cell(res.finding("direct_deposit")), doc_cell(res.finding("hoa_rules")),
               needed_html))

    q_rows = []
    for q in queue:
        payload = json.loads(q["payload"] or "{}")
        to = q["recipient"] or ""
        if q["kind"] == "buildium_change":
            to = "Buildium via %s" % ("API" if payload.get("tier") == "api" else "browser step")
        q_rows.append("<tr><td class='mono'>#%d</td><td>%s</td><td><div class='name'>%s</div>"
                      "<div class='small'>%s</div></td><td>%s<div class='small'>to %s</div></td>"
                      "<td>%s%s</td><td class='mono'>%s</td></tr>"
                      % (q["id"], e(KIND_TEXT.get(q["kind"], q["kind"])), e(q["entity_name"]),
                         e(q["entity_id"]), e(q["subject"]), e(to), pill(q["status"]),
                         ("<div class='small'>by %s</div>" % e(q["decided_by"])
                          if q["decided_by"] else ""), e(q["idem_key"])))

    a_rows = "".join("<tr><td class='mono'>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                     "<td>%s</td></tr>" % (e(a["ts"]), e(a["actor"]), e(a["event"]),
                                          e(a["entity_id"] or ""), e(a["detail"]))
                     for a in store.audit(14))

    n_ok_v = sum(1 for r in vendors if r.status == "compliant")
    n_ok_o = sum(1 for r in owners if r.status == "compliant")
    n_paused = sum(1 for r in vendors if r.dispatch_paused)
    notes = "".join("<p class='hint'>%s</p>" % e(n) for n in run.notes + [
        "Skipped: %s" % s for s in run.skipped])

    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compliance audit %(as_of)s</title><style>%(css)s</style></head>
<body><div class="wrap">
<header><div><h1>Vendor credentialing &amp; owner onboarding audit</h1>
<p class="sub">Sample Residential Management &middot; synthetic data &middot; every outbound item
waits for a person to approve it</p></div>
<div class="meta">As of <b>%(as_of)s</b><br>Extraction: <b>%(mode)s</b><br>
Source: Buildium API fixtures + CSV exports</div></header>

<div class="cards">
<div class="card"><div class="n">%(ok_v)d / %(n_v)d</div><div class="l">active vendors fully compliant</div></div>
<div class="card"><div class="n">%(paused)d</div><div class="l">vendors with dispatch paused</div></div>
<div class="card"><div class="n">%(ok_o)d / %(n_o)d</div><div class="l">owner files complete</div></div>
<div class="card"><div class="n">%(pending)d</div><div class="l">items waiting for approval</div></div>
</div>

<h2>Vendor credentialing</h2>
<p class="hint">Required: Certificate of Insurance (GL &ge; $1,000,000 per occurrence,
management company as additional insured), W-9, and a trade licence for electrical, plumbing
and HVAC. Reminders go out 30 days before expiry. An expired or missing COI pauses dispatch.</p>
%(notes)s
<table><thead><tr><th>Vendor</th><th>Overall</th><th>Certificate of insurance</th><th>W-9</th>
<th>Trade licence</th><th>Dispatch</th></tr></thead><tbody>%(v_rows)s</tbody></table>

<h2>Owner onboarding</h2>
<p class="hint">Required: W-9, proof of landlord insurance, signed management agreement,
direct deposit form, and HOA rules when a property has an HOA.</p>
<table><thead><tr><th>Owner</th><th>Overall</th><th>W-9</th><th>Landlord insurance</th>
<th>Mgmt agreement</th><th>Direct deposit</th><th>HOA rules</th><th>Still needed</th></tr></thead>
<tbody>%(o_rows)s</tbody></table>

<h2>Approval queue</h2>
<p class="hint">Drafts and proposed Buildium changes. The idempotency key (entity | document |
window) means a re-run never adds a duplicate. <code>send</code> refuses anything not approved;
the sender is a stub that writes to <code>out/outbox.jsonl</code>.</p>
<table><thead><tr><th>#</th><th>Type</th><th>For</th><th>Subject</th><th>Status</th>
<th>Idempotency key</th></tr></thead><tbody>%(q_rows)s</tbody></table>

<h2>Evidence for every finding</h2>
<p class="hint">Each value is quoted from the source line it came from. Text-layer quotes are
checked against the PDF text in code; quotes from a scan cannot be, so low confidence there goes
to a person. Tax IDs and account numbers are masked to the last 4 digits everywhere.</p>
<table><thead><tr><th>Entity</th><th>Document</th><th>Status</th><th>Quoted evidence</th></tr>
</thead><tbody>%(evidence)s</tbody></table>
<details><summary>All extracted fields (%(n_fields)d)</summary>
<table style="margin-top:8px"><thead><tr><th>Entity</th><th>Document</th><th>Field</th>
<th>Value</th><th>Source</th></tr></thead><tbody>%(all_fields)s</tbody></table></details>

<h2>Audit log (latest)</h2>
<table><thead><tr><th>Time (UTC)</th><th>Actor</th><th>Event</th><th>Entity</th><th>Detail</th>
</tr></thead><tbody>%(a_rows)s</tbody></table>

<footer>Synthetic data. Not affiliated with Buildium, LeadSimple, QuickBooks or DocuSign.
Generated by pm-compliance-agent.</footer>
</div></body></html>
""" % {
        "css": CSS, "as_of": e(run.as_of.isoformat()),
        "mode": "offline replay (recorded fixtures)" if run.mode == "offline" else "live model",
        "ok_v": n_ok_v, "n_v": len(vendors), "paused": n_paused, "ok_o": n_ok_o,
        "n_o": len(owners), "pending": pending, "notes": notes, "v_rows": "".join(v_rows),
        "o_rows": "".join(o_rows), "q_rows": "".join(q_rows),
        "evidence": _evidence_rows(vendors + owners),
        "n_fields": sum(len(f.extraction.fields) for r in vendors + owners for f in r.findings
                        if f.extraction),
        "all_fields": _all_fields(vendors + owners), "a_rows": a_rows,
    }
