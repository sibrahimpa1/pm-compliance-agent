"""Build the static web app in site/ (index.html + data.json).

The page is one self-contained file: inline CSS and JS, data embedded as JSON,
no CDNs or web fonts, so it works from file:// and from GitHub Pages. The same
data is written to site/data.json for anyone who wants it raw. Every string
passes through the PII mask before it is written.

    python -m pmcompliance.site      # runs the offline demo pipeline, then writes site/
"""
from __future__ import annotations

import json
import os
from typing import Any, List

from . import pii
from .buildium import OwnerRecord, VendorRecord
from .checks import EntityResult, Finding
from .pipeline import AuditRun
from .store import Store


def _doc(f: Finding) -> dict:
    ex = f.extraction
    return {
        "doc_type": f.doc_type, "label": f.label, "status": f.status, "reasons": f.reasons,
        "expiry": f.expiry.isoformat() if f.expiry else None, "days_left": f.days_left,
        "blocks_dispatch": f.blocks_dispatch,
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in f.checks],
        "file": ex.path.split("/data/")[-1] if ex else None,
        "route": ex.route if ex else None, "extractor": ex.extractor if ex else None,
        "fields": [{"name": k, "value": v.value, "page": v.page, "line": v.line,
                    "confidence": v.confidence, "verified": v.verified}
                   for k, v in sorted(ex.fields.items())] if ex else [],
    }


def _iso(d: Any) -> Any:
    return d.isoformat() if d else None


def site_data(run: AuditRun, store: Store) -> dict:
    vendors = []
    for rec, res in run.vendors:  # type: VendorRecord, EntityResult
        vendors.append({
            "id": res.entity_id, "name": res.name, "trade": rec.trade, "email": rec.email,
            "status": res.status, "dispatch_paused": res.dispatch_paused,
            "record": {"insurance_expiration": _iso(rec.insurance_expiration),
                       "license_number": rec.license_number, "license_state": rec.license_state,
                       "license_expiration": _iso(rec.license_expiration),
                       "dispatch_hold_in_buildium": rec.dispatch_hold},
            "sources": rec.sources, "docs": [_doc(f) for f in res.findings],
        })
    owners = []
    for rec, res in run.owners:  # type: OwnerRecord, EntityResult
        owners.append({
            "id": res.entity_id, "name": res.name, "email": rec.email, "status": res.status,
            "properties": [{"id": p.property_id, "address": p.address, "has_hoa": p.has_hoa,
                            "hoa_name": p.hoa_name} for p in rec.properties],
            "sources": rec.sources, "docs": [_doc(f) for f in res.findings],
        })
    queue = [{k: q[k] for k in ("id", "kind", "channel", "entity_id", "entity_name", "doc_type",
                                "recipient", "subject", "body", "status", "idem_key",
                                "decided_by", "created_at")} for q in store.items()]
    for item, q in zip(queue, store.items()):
        item["payload"] = json.loads(q["payload"] or "{}")
    audit = [{k: a[k] for k in ("ts", "actor", "event", "entity_id", "detail")}
             for a in reversed(store.audit(500))]
    data = {"as_of": run.as_of.isoformat(), "mode": run.mode, "vendors": vendors,
            "owners": owners, "queue": queue, "audit": audit, "skipped": run.skipped,
            "notes": run.notes}
    return _mask_all(data)


def _mask_all(obj: Any) -> Any:
    if isinstance(obj, str):
        return pii.mask(obj)
    if isinstance(obj, list):
        return [_mask_all(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _mask_all(v) for k, v in obj.items()}
    return obj


def write_site(run: AuditRun, store: Store, site_dir: str) -> str:
    os.makedirs(site_dir, exist_ok=True)
    data = site_data(run, store)
    with open(os.path.join(site_dir, "data.json"), "w") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    embedded = json.dumps(data, sort_keys=True).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", embedded).replace("__AS_OF__", data["as_of"])
    path = os.path.join(site_dir, "index.html")
    with open(path, "w") as fh:
        fh.write(page)
    # GitHub Pages: serve files as-is.
    open(os.path.join(site_dir, ".nojekyll"), "w").close()
    return path


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Compliance Desk</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#ffffff; --ink:#111827; --ink2:#374151; --muted:#6b7280;
  --line:#e5e7eb; --soft:#f3f4f6; --accent:#2563eb; --accent-soft:#eff4ff;
  --ok:#15803d; --ok-bg:#e7f6ec; --warn:#a16207; --warn-bg:#fdf6dc; --bad:#b42318;
  --bad-bg:#fdecea; --miss:#be123c; --miss-bg:#fdeef2; --rev:#5b21b6; --rev-bg:#f1ecfd;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}
button{font:inherit}
.banner{background:#111827;color:#e5e7eb;font-size:12.5px;padding:7px 16px;text-align:center}
.app{display:grid;grid-template-columns:232px minmax(0,1fr);min-height:calc(100vh - 33px)}
.app>*{min-width:0}
.side{background:var(--panel);border-right:1px solid var(--line);padding:18px 14px;
  position:sticky;top:0;height:calc(100vh - 33px);display:flex;flex-direction:column}
.brand{display:flex;align-items:center;gap:10px;padding:0 6px 18px}
.logo{width:30px;height:30px;border-radius:8px;background:var(--accent);color:#fff;
  display:grid;place-items:center;font-weight:700}
.brand b{display:block;font-size:15px}
.brand small{color:var(--muted);font-size:12px}
nav{display:flex;flex-direction:column;gap:2px}
nav a{display:flex;justify-content:space-between;align-items:center;color:var(--ink2);
  padding:8px 10px;border-radius:8px;font-weight:500}
nav a:hover{background:var(--soft)}
nav a.on{background:var(--accent-soft);color:var(--accent)}
.badge{background:var(--accent);color:#fff;border-radius:999px;font-size:11px;padding:0 7px;
  line-height:18px;min-width:18px;text-align:center}
.side-foot{margin-top:auto;color:var(--muted);font-size:12px;padding:0 6px}
main{padding:26px 30px 60px;min-width:0}
.head{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;
  flex-wrap:wrap;margin-bottom:18px}
h1{font-size:21px;margin:0;letter-spacing:-.01em}
h2{font-size:15px;margin:0 0 10px}
.sub{color:var(--muted);margin:2px 0 0}
.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;
  cursor:pointer;text-align:left;color:inherit}
.kpi:hover{border-color:#cbd5e1}
.kpi .n{font-size:28px;font-weight:650;letter-spacing:-.02em;line-height:1.1}
.kpi .l{display:flex;align-items:center;gap:6px;color:var(--ink2);font-weight:500;margin-top:4px}
.kpi .s{color:var(--muted);font-size:12px}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.grid2{display:grid;grid-template-columns:1.4fr 1fr;gap:16px}
.box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;
  min-width:0}
.box+.box{margin-top:0}
.stack>*+*{margin-top:16px}
.list{list-style:none;margin:0;padding:0}
.list li{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
  padding:9px 0;border-top:1px solid var(--line)}
.list li:first-child{border-top:0}
.muted{color:var(--muted)} .small{font-size:12px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11.5px}
.pill{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:600;
  white-space:nowrap}
.s-compliant,.s-sent{background:var(--ok-bg);color:var(--ok)}
.s-expiring_soon,.s-pending{background:var(--warn-bg);color:var(--warn)}
.s-expired{background:var(--bad-bg);color:var(--bad)}
.s-missing{background:var(--miss-bg);color:var(--miss)}
.s-needs_review{background:var(--rev-bg);color:var(--rev)}
.s-approved{background:var(--accent-soft);color:var(--accent)}
.s-rejected,.s-na{background:var(--soft);color:var(--muted)}
.paused{background:var(--bad);color:#fff;border-radius:6px;padding:1px 8px;font-size:12px;
  font-weight:600;white-space:nowrap}
.activeTag{color:var(--ok);font-size:12px;font-weight:600}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.toolbar input,.toolbar select{border:1px solid var(--line);background:var(--panel);
  border-radius:8px;padding:7px 10px;font:inherit;color:inherit;min-width:0}
.toolbar input{flex:1 1 220px}
.tablewrap{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  overflow-x:auto}
table{width:100%;border-collapse:collapse}
th{text-align:left;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--muted);font-weight:600;padding:10px 12px;border-bottom:1px solid var(--line);
  background:#fafafa;white-space:nowrap}
td{padding:11px 12px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
tbody tr.click{cursor:pointer}
tbody tr.click:hover{background:#fafbff}
.nm{font-weight:600}
.why{color:var(--ink2);font-size:12px;margin-top:3px;max-width:240px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);
  border-radius:8px;padding:2px 8px;font-size:12px;background:#fff;white-space:nowrap}
.chip.ok{color:var(--ok)} .chip.no{color:var(--bad);border-color:#f5c6c0}
.chip.rv{color:var(--rev);border-color:#ddd0fb} .chip.wn{color:var(--warn);border-color:#f1e1a6}
.note{background:var(--warn-bg);color:#713f12;border:1px solid #f1e1a6;border-radius:10px;
  padding:9px 12px;margin-bottom:12px;font-size:13px}
.qcard{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;
  margin-bottom:10px}
.qtop{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
.kind{font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase;
  letter-spacing:.04em}
.qsub{font-weight:600;margin:4px 0 2px}
.key{background:var(--soft);border-radius:6px;padding:2px 6px;display:inline-block;
  word-break:break-all}
.actions{display:flex;gap:8px;margin-top:10px}
.btn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 12px;
  cursor:pointer;font-weight:500}
.btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.btn:hover{filter:brightness(.97)}
details summary{cursor:pointer;color:var(--accent);font-size:13px;margin-top:8px}
pre.body{white-space:pre-wrap;background:var(--soft);border-radius:8px;padding:10px;
  font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;margin:8px 0 0}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;
  background:#fff}
.seg button{border:0;background:none;padding:6px 11px;cursor:pointer;color:var(--ink2)}
.seg button.on{background:var(--accent-soft);color:var(--accent);font-weight:600}
.backdrop{position:fixed;inset:0;background:rgba(17,24,39,.35);z-index:10}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(640px,100%);background:var(--panel);
  z-index:11;box-shadow:-12px 0 30px rgba(0,0,0,.12);overflow-y:auto;padding:22px 24px 40px}
.drawer .x{position:absolute;top:14px;right:16px}
.dhead{padding-right:60px;margin-bottom:14px}
.dhead h2{font-size:19px;margin:0}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:13px}
.kv dt{color:var(--muted)} .kv dd{margin:0}
.src{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;border-radius:4px;
  padding:0 5px;margin-left:6px;background:var(--soft);color:var(--muted)}
.doc{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:12px}
.doc h3{font-size:14px;margin:0;display:flex;justify-content:space-between;gap:8px;
  align-items:center;flex-wrap:wrap}
.flag{background:var(--rev-bg);border-radius:8px;padding:8px 10px;margin:10px 0 0;
  color:#3b0764;font-size:13px}
.flag.bad{background:var(--bad-bg);color:#7a1a12}
.flag ul{margin:4px 0 0 18px;padding:0}
.checks{list-style:none;padding:0;margin:10px 0 0;font-size:13px}
.checks li{display:flex;gap:8px;padding:3px 0}
.checks .i{width:18px;flex:none;font-weight:700}
.checks .y{color:var(--ok)} .checks .n{color:var(--bad)}
.fields{margin-top:10px;font-size:12.5px}
.fields td{padding:7px 8px}
.quote{border-left:3px solid #c7d2fe;padding-left:8px;color:var(--ink2)}
.ver{font-size:11px;font-weight:600}
.ver.y{color:var(--ok)} .ver.n{color:var(--warn)}
.flow{display:flex;flex-wrap:wrap;gap:8px;align-items:stretch}
.step{flex:1 1 150px;background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:12px;position:relative}
.step b{display:block;margin-bottom:3px}
.step .muted{font-size:12.5px}
.tiers{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.tier .t{font-size:12px;font-weight:700;color:var(--accent);text-transform:uppercase;
  letter-spacing:.05em}
.trail li{display:block}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
  .grid2{grid-template-columns:1fr}}
@media (max-width:820px){
  .app{grid-template-columns:minmax(0,1fr)}
  .side{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);
    padding:10px 12px}
  .brand{padding:0 2px 8px}
  nav{flex-direction:row;overflow-x:auto;gap:4px}
  nav a{white-space:nowrap;gap:6px}
  .side-foot{display:none}
  main{padding:18px 16px 50px}
  .tiers{grid-template-columns:1fr}
  .hide-sm{display:none}
}
@media (max-width:520px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .drawer{padding:18px 16px 40px}
  .fields table,.fields tbody,.fields tr,.fields td{display:block}
  .fields thead{display:none}
  .fields tr{border-bottom:1px solid var(--line);padding:6px 0}
  .fields tr:last-child{border-bottom:0}
  .fields td{border:0;padding:2px 10px}
  .qsub,.small{overflow-wrap:anywhere}}
</style>
</head>
<body>
<div class="banner">Demo on synthetic data. Not affiliated with Buildium, LeadSimple, QuickBooks or DocuSign.</div>
<div class="app">
  <aside class="side">
    <div class="brand"><span class="logo">&#10003;</span>
      <div><b>Compliance Desk</b><small>Sample Residential Management</small></div></div>
    <nav>
      <a href="#dashboard" data-view="dashboard">Dashboard</a>
      <a href="#vendors" data-view="vendors">Vendors</a>
      <a href="#owners" data-view="owners">Owners</a>
      <a href="#queue" data-view="queue">Approval queue <span class="badge" id="pending"></span></a>
      <a href="#how" data-view="how">How it works</a>
    </nav>
    <div class="side-foot">Audit as of __AS_OF__<br>Offline replay of recorded extractions</div>
  </aside>
  <main id="main"></main>
</div>
<div id="drawerRoot"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
"use strict";
var D = JSON.parse(document.getElementById("data").textContent);
var LABEL = {compliant: "Compliant", expiring_soon: "Expiring soon", expired: "Expired",
  missing: "Missing", needs_review: "Needs review", pending: "Pending", approved: "Approved",
  rejected: "Rejected", sent: "Sent (stub)", na: "Not required"};
var ORDER = {compliant: 0, expiring_soon: 1, needs_review: 2, missing: 3, expired: 4};
var COLOR = {compliant: "var(--ok)", expiring_soon: "var(--warn)", expired: "var(--bad)",
  missing: "var(--miss)", needs_review: "var(--rev)"};
var KIND = {renewal_reminder: "Renewal reminder", document_request: "Document request",
  owner_followup: "Owner follow-up", review_task: "Review task", buildium_change: "Buildium change"};
var TRADE = {hvac: "HVAC", electrical: "Electrical", plumbing: "Plumbing",
  landscaping: "Landscaping", cleaning: "Cleaning"};
var main = document.getElementById("main");
var F = {q: "", status: "", trade: ""};
var QF = "all";

function esc(s) {
  return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, function (c) {
    return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
  });
}
function pill(s) { return '<span class="pill s-' + esc(s) + '">' + esc(LABEL[s] || s) + "</span>"; }
function trade(t) { return TRADE[t] || t; }
function fmtDate(iso) {
  if (!iso) return "";
  var p = iso.split("-");
  return ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][+p[1] - 1] +
    " " + (+p[2]) + ", " + p[0];
}

// ---- client-side approval state (never sends anything) -----------------
var KEY = "pmc-demo-state-v1";
function loadState() {
  try { return JSON.parse(localStorage.getItem(KEY)) || {decisions: {}, trail: []}; }
  catch (e) { return {decisions: {}, trail: []}; }
}
var S = loadState();
function saveState() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} }
function qStatus(q) { return (S.decisions[q.id] || {}).status || q.status; }

function allEntities() { return D.vendors.concat(D.owners); }
function findEntity(id) {
  var all = allEntities();
  for (var i = 0; i < all.length; i++) if (all[i].id === id) return all[i];
  return null;
}
function docOf(e, t) {
  for (var i = 0; i < e.docs.length; i++) if (e.docs[i].doc_type === t) return e.docs[i];
  return null;
}
function docCell(d) {
  if (!d) return pill("na");
  var h = pill(d.status);
  if (d.expiry) h += '<div class="small muted">exp. ' + esc(fmtDate(d.expiry)) + "</div>";
  if (d.status !== "compliant" && d.reasons.length)
    h += '<div class="why">' + esc(d.reasons[0]) + "</div>";
  return h;
}

// ---- views ---------------------------------------------------------------
function dashboard() {
  var counts = {}, split = {};
  Object.keys(ORDER).forEach(function (k) { counts[k] = 0; split[k] = {v: 0, o: 0}; });
  D.vendors.forEach(function (e) { e.docs.forEach(function (d) { counts[d.status]++; split[d.status].v++; }); });
  D.owners.forEach(function (e) { e.docs.forEach(function (d) { counts[d.status]++; split[d.status].o++; }); });
  var kpis = ["compliant", "expiring_soon", "expired", "missing", "needs_review"].map(function (k) {
    return '<button class="kpi" data-goto="' + k + '"><div class="n">' + counts[k] +
      '</div><div class="l"><span class="dot" style="background:' + COLOR[k] + '"></span>' +
      (k === "expiring_soon" ? "Expiring in 30 days" : esc(LABEL[k])) +
      '</div><div class="s">' + split[k].v + " vendor &middot; " + split[k].o + " owner docs</div></button>";
  }).join("");
  var paused = D.vendors.filter(function (v) { return v.dispatch_paused; });
  var pausedHtml = paused.length ? paused.map(function (v) {
    var why = v.docs.filter(function (d) { return d.blocks_dispatch && (d.status === "expired" || d.status === "missing"); })
      .map(function (d) { return d.label + " " + LABEL[d.status].toLowerCase() + (d.expiry ? " " + fmtDate(d.expiry) : ""); });
    return '<li><div><a href="#vendors/' + esc(v.id) + '" class="nm">' + esc(v.name) + '</a><div class="small muted">' +
      esc(why.join("; ")) + '</div></div><span class="paused">Paused</span></li>';
  }).join("") : '<li class="muted">No vendor is paused.</li>';
  var att = [];
  allEntities().forEach(function (e) {
    e.docs.forEach(function (d) { if (d.status !== "compliant") att.push({e: e, d: d}); });
  });
  att.sort(function (a, b) { return ORDER[b.d.status] - ORDER[a.d.status] || a.e.name.localeCompare(b.e.name); });
  var attHtml = att.map(function (x) {
    var view = x.e.id.charAt(0) === "V" ? "vendors" : "owners";
    return '<tr class="click" data-open="' + view + "/" + esc(x.e.id) + '"><td><div class="nm">' + esc(x.e.name) +
      '</div><div class="small muted">' + esc(x.e.id) + "</div></td><td>" + esc(x.d.label) + "</td><td>" +
      pill(x.d.status) + '</td><td class="hide-sm"><div class="why">' + esc(x.d.reasons.join("; ")) + "</div></td></tr>";
  }).join("");
  var soon = [];
  allEntities().forEach(function (e) {
    e.docs.forEach(function (d) { if (d.days_left !== null && d.days_left >= 0 && d.days_left <= 120) soon.push({e: e, d: d}); });
  });
  soon.sort(function (a, b) { return a.d.days_left - b.d.days_left; });
  var soonHtml = soon.length ? soon.map(function (x) {
    return "<li><div><span class=\"nm\">" + esc(x.e.name) + '</span><div class="small muted">' + esc(x.d.label) +
      " &middot; " + esc(fmtDate(x.d.expiry)) + "</div></div><span class=\"small\">" + x.d.days_left + " days</span></li>";
  }).join("") : '<li class="muted">Nothing in the next 120 days.</li>';
  var pending = D.queue.filter(function (q) { return qStatus(q) === "pending"; }).length;
  return '<div class="head"><div><h1>Dashboard</h1><p class="sub">Audit as of ' + esc(fmtDate(D.as_of)) + " &middot; " +
    D.vendors.length + " active vendors &middot; " + D.owners.length + " owners &middot; documents by status</p></div>" +
    '<a class="btn primary" href="#queue">' + pending + " waiting for approval</a></div>" +
    '<div class="kpis">' + kpis + "</div>" +
    '<div class="grid2"><div class="box"><h2>Needs attention</h2><div class="tablewrap" style="border:0">' +
    "<table><thead><tr><th>Who</th><th>Document</th><th>Status</th><th class=\"hide-sm\">Why</th></tr></thead><tbody>" +
    attHtml + "</tbody></table></div></div>" +
    '<div class="stack"><div class="box"><h2>Dispatch paused</h2><ul class="list">' + pausedHtml + "</ul></div>" +
    '<div class="box"><h2>Upcoming expirations</h2><ul class="list">' + soonHtml + "</ul></div></div></div>";
}

function vendorRows() {
  var q = F.q.toLowerCase();
  var rows = D.vendors.filter(function (v) {
    if (F.status && v.status !== F.status && !v.docs.some(function (d) { return d.status === F.status; })) return false;
    if (F.trade && v.trade !== F.trade) return false;
    if (q && (v.name + " " + v.id + " " + v.email).toLowerCase().indexOf(q) < 0) return false;
    return true;
  });
  if (!rows.length) return '<tr><td colspan="7" class="muted">No vendors match these filters.</td></tr>';
  return rows.map(function (v) {
    return '<tr class="click" data-open="vendors/' + esc(v.id) + '"><td><div class="nm">' + esc(v.name) +
      '</div><div class="small muted">' + esc(v.id) + "</div></td><td>" + esc(trade(v.trade)) + "</td><td>" +
      pill(v.status) + "</td><td>" + docCell(docOf(v, "coi")) + '</td><td class="hide-sm">' + docCell(docOf(v, "w9")) +
      '</td><td class="hide-sm">' + docCell(docOf(v, "trade_license")) + "</td><td>" +
      (v.dispatch_paused ? '<span class="paused">Paused</span>' : '<span class="activeTag">Active</span>') + "</td></tr>";
  }).join("");
}
function vendors() {
  var trades = [];
  D.vendors.forEach(function (v) { if (trades.indexOf(v.trade) < 0) trades.push(v.trade); });
  var opt = function (val, txt, cur) { return '<option value="' + esc(val) + '"' + (val === cur ? " selected" : "") + ">" + esc(txt) + "</option>"; };
  return '<div class="head"><div><h1>Vendors</h1><p class="sub">Certificate of insurance, W-9 and trade licence for every active contractor. Click a row for the evidence.</p></div></div>' +
    '<div class="toolbar"><input id="fq" type="search" placeholder="Search vendor, ID or email" value="' + esc(F.q) + '">' +
    '<select id="fs">' + opt("", "All statuses", F.status) + Object.keys(ORDER).map(function (k) { return opt(k, LABEL[k], F.status); }).join("") + "</select>" +
    '<select id="ft">' + opt("", "All trades", F.trade) + trades.sort().map(function (t) { return opt(t, trade(t), F.trade); }).join("") + "</select></div>" +
    '<div class="tablewrap"><table><thead><tr><th>Vendor</th><th>Trade</th><th>Overall</th><th>Insurance (COI)</th>' +
    '<th class="hide-sm">W-9</th><th class="hide-sm">Trade licence</th><th>Dispatch</th></tr></thead><tbody id="vbody">' +
    vendorRows() + "</tbody></table></div>" +
    (D.skipped.length ? '<p class="small muted">Not audited: ' + esc(D.skipped.join("; ")) + "</p>" : "");
}

function owners() {
  var rows = D.owners.map(function (o) {
    var chips = o.docs.map(function (d) {
      var c = d.status === "compliant" ? "ok" : d.status === "needs_review" ? "rv" : d.status === "expiring_soon" ? "wn" : "no";
      var icon = d.status === "compliant" ? "&#10003;" : d.status === "needs_review" ? "?" : d.status === "expiring_soon" ? "!" : "&#10007;";
      return '<span class="chip ' + c + '" title="' + esc(LABEL[d.status]) + '">' + icon + " " + esc(d.label) + "</span>";
    }).join("");
    var need = o.docs.filter(function (d) { return d.status === "missing" || d.status === "expired" || d.status === "expiring_soon"; });
    var needHtml = need.length ? need.map(function (d) { return esc(d.label) + ' <span class="small muted">(' + esc(LABEL[d.status].toLowerCase()) + ")</span>"; }).join("<br>") : '<span class="muted">Nothing</span>';
    var props = o.properties.map(function (p) { return esc(p.address.split(",")[0]) + (p.has_hoa ? ' <span class="src">HOA</span>' : ""); }).join("<br>");
    return '<tr class="click" data-open="owners/' + esc(o.id) + '"><td><div class="nm">' + esc(o.name) + '</div><div class="small muted">' +
      esc(o.id) + '</div></td><td class="hide-sm small">' + props + "</td><td>" + pill(o.status) + '</td><td><div class="chips">' + chips +
      '</div></td><td class="hide-sm">' + needHtml + "</td></tr>";
  }).join("");
  return '<div class="head"><div><h1>Owners</h1><p class="sub">Onboarding checklist: W-9, landlord insurance, signed management agreement, direct deposit form, and HOA rules when a property has an HOA.</p></div></div>' +
    '<div class="tablewrap"><table><thead><tr><th>Owner</th><th class="hide-sm">Properties</th><th>Overall</th><th>Checklist</th><th class="hide-sm">Still needed</th></tr></thead><tbody>' +
    rows + "</tbody></table></div>";
}

function queue() {
  var items = D.queue.filter(function (q) { return QF === "all" || qStatus(q) === QF; });
  var cards = items.map(function (q) {
    var st = qStatus(q), dec = S.decisions[q.id];
    var to = q.kind === "buildium_change" ? "Buildium via " + (q.payload.tier === "api" ? "API" : "approved browser step") : q.recipient;
    var by = dec ? dec.by + " (this browser)" : q.decided_by;
    return '<div class="qcard"><div class="qtop"><div><span class="kind">' + esc(KIND[q.kind] || q.kind) + " &middot; #" + q.id +
      '</span><div class="qsub">' + esc(q.subject) + '</div><div class="small muted">' + esc(q.entity_name) + " (" + esc(q.entity_id) +
      ") &middot; to " + esc(to) + "</div></div><div>" + pill(st) + (by ? '<div class="small muted">by ' + esc(by) + "</div>" : "") + "</div></div>" +
      '<div class="small" style="margin-top:8px">Idempotency key <span class="key mono">' + esc(q.idem_key) + "</span></div>" +
      "<details><summary>Show draft</summary><pre class=\"body\">" + esc(q.body) + "</pre></details>" +
      (st === "pending" ? '<div class="actions"><button class="btn primary" data-act="approve" data-id="' + q.id +
        '">Approve</button><button class="btn" data-act="reject" data-id="' + q.id + '">Reject</button></div>' : "") + "</div>";
  }).join("") || '<p class="muted">No items with this status.</p>';
  var seg = ["all", "pending", "approved", "rejected", "sent"].map(function (k) {
    return '<button data-qf="' + k + '" class="' + (QF === k ? "on" : "") + '">' + (k === "all" ? "All" : esc(LABEL[k])) + "</button>";
  }).join("");
  var trail = S.trail.slice().reverse().map(function (t) {
    return '<li><span class="mono muted">' + esc(t.at) + "</span> &nbsp;" + esc(t.text) + "</li>";
  }).join("") || '<li class="muted">No actions in this browser yet.</li>';
  var server = D.audit.filter(function (a) { return ["approved", "rejected", "sent", "send_refused", "dispatch_paused", "status_change"].indexOf(a.event) >= 0; })
    .slice(-12).reverse().map(function (a) {
      return '<li><span class="mono muted">' + esc(a.ts) + "</span> &nbsp;<b>" + esc(a.event) + "</b> " + esc(a.entity_id || "") + " &middot; " + esc(a.detail) + " <span class=\"muted\">(" + esc(a.actor) + ")</span></li>";
    }).join("");
  return '<div class="head"><div><h1>Approval queue</h1><p class="sub">Reminders, follow-ups, review tasks and proposed Buildium changes. Nothing leaves without a person approving it.</p></div>' +
    '<div class="seg">' + seg + "</div></div>" +
    '<div class="note"><b>Demo: approvals here don\'t send anything.</b> Decisions are kept in this browser only (localStorage). <a href="#queue" data-act="reset">Reset demo state</a></div>' +
    cards + '<div class="grid2" style="margin-top:16px"><div class="box"><h2>Your actions in this session</h2><ul class="list trail">' + trail +
    '</ul></div><div class="box"><h2>Audit log from the pipeline run</h2><ul class="list trail">' + server + "</ul></div></div>";
}

function how() {
  var steps = [["Directory", "Vendors and owners from the Buildium API; gaps filled from CSV exports."],
    ["Documents", "Files attached to each vendor or owner. PDFs with text go to pypdf; scans go to the vision path."],
    ["Extraction", "Claude returns fields as JSON, each with page and source line. Offline, recorded results replay by SHA-256."],
    ["Checks in code", "Dates, coverage minimums, name match, signatures, requirement matrix. Statuses decided here, not by the model."],
    ["Approval queue", "Reminders, follow-ups and Buildium changes wait for a person. Idempotency keys stop duplicates."],
    ["Send + verify", "Approved items go out; Buildium changes are read back before they count as done."]];
  var flow = steps.map(function (s, i) { return '<div class="step"><span class="small muted">' + (i + 1) + "</span><b>" + esc(s[0]) + '</b><div class="muted">' + esc(s[1]) + "</div></div>"; }).join("");
  return '<div class="head"><div><h1>How it works</h1><p class="sub">The model reads documents. Code makes the decisions. People approve anything that leaves the building.</p></div></div>' +
    '<div class="flow">' + flow + "</div>" +
    '<h2 style="margin-top:24px">Working around Buildium API gaps</h2><div class="tiers">' +
    '<div class="box tier"><div class="t">1 &middot; API first</div><p>Read vendors, owners and properties through the API. Write where the API allows (for example the vendor insurance date).</p></div>' +
    '<div class="box tier"><div class="t">2 &middot; Exports and email</div><p>Fields the API does not return (licence number and expiry, HOA flag) come from scheduled CSV exports or parsed emails. Also the fallback when the API is down.</p></div>' +
    '<div class="box tier"><div class="t">3 &middot; Approved browser step</div><p>For fields with no API and no bulk update (a do-not-dispatch hold), the system proposes the exact UI change. A person approves, it is applied, then read back to confirm.</p></div></div>' +
    '<div class="grid2" style="margin-top:16px"><div class="box"><h2>Human in the loop</h2><ul class="list">' +
    "<li>Every email, follow-up and Buildium change is a draft until someone approves it.</li>" +
    "<li>Financial and legal documents (W-9, management agreement, direct deposit) are never auto-accepted when anything is unclear.</li>" +
    "<li>Low confidence, a name mismatch or a quote not found in the PDF goes to a review task.</li>" +
    "<li>Dispatch pauses automatically in this system (fail closed); mirroring it into Buildium is approved.</li></ul></div>" +
    '<div class="box"><h2>PII care</h2><ul class="list">' +
    "<li>Tax IDs and bank account numbers are masked to the last 4 digits before text goes to the model, and in every log, report and file.</li>" +
    "<li>Original PDFs stay where they are; the system stores extracted fields and quotes, not copies.</li>" +
    "<li>This page holds synthetic data only.</li></ul></div></div>";
}

var VIEWS = {dashboard: dashboard, vendors: vendors, owners: owners, queue: queue, how: how};

// ---- drawer ----------------------------------------------------------------
function drawerHtml(e) {
  var isV = e.id.charAt(0) === "V";
  var srcTag = function (k) { return e.sources && e.sources[k] ? '<span class="src">' + esc(e.sources[k]) + "</span>" : ""; };
  var info = isV ?
    "<dt>Trade</dt><dd>" + esc(trade(e.trade)) + srcTag("trade") + "</dd><dt>Email</dt><dd>" + esc(e.email) + srcTag("email") +
    "</dd><dt>Insurance exp. in Buildium</dt><dd>" + esc(fmtDate(e.record.insurance_expiration) || "none") + srcTag("insurance_expiration") +
    "</dd><dt>Licence in Buildium</dt><dd>" + esc(e.record.license_number || "none") + (e.record.license_expiration ? ", exp. " + esc(fmtDate(e.record.license_expiration)) : "") + srcTag("license_number") +
    "</dd><dt>Dispatch</dt><dd>" + (e.dispatch_paused ? '<span class="paused">Paused</span>' : '<span class="activeTag">Active</span>') + "</dd>"
    : "<dt>Email</dt><dd>" + esc(e.email) + srcTag("name") + "</dd><dt>Properties</dt><dd>" + e.properties.map(function (p) {
      return esc(p.address) + (p.has_hoa ? ' <span class="src">HOA: ' + esc(p.hoa_name) + "</span>" : "");
    }).join("<br>") + "</dd>";
  var docs = e.docs.map(function (d) {
    var flagged = d.status !== "compliant" && d.reasons.length ?
      '<div class="flag' + (d.status === "expired" || d.status === "missing" ? " bad" : "") + '"><b>Why it is flagged</b><ul>' +
      d.reasons.map(function (r) { return "<li>" + esc(r) + "</li>"; }).join("") + "</ul></div>" : "";
    var checks = d.checks.length ? '<ul class="checks">' + d.checks.map(function (c) {
      return '<li><span class="i ' + (c.ok ? "y" : "n") + '">' + (c.ok ? "&#10003;" : "&#10007;") + "</span><span>" + esc(c.name) +
        ' <span class="muted">&middot; ' + esc(c.detail) + "</span></span></li>";
    }).join("") + "</ul>" : "";
    var fields = d.fields.length ? '<div class="tablewrap fields"><table><thead><tr><th>Field</th><th>Value</th><th>Evidence</th></tr></thead><tbody>' +
      d.fields.map(function (f) {
        var ver = f.verified === true ? '<span class="ver y">&#10003; found in PDF text</span>' : f.verified === null ? '<span class="ver n">from scan, not checkable</span>' : '<span class="ver n">not found in text</span>';
        return "<tr><td class=\"mono\">" + esc(f.name) + "</td><td>" + esc(f.value) + '</td><td><div class="quote">&ldquo;' + esc(f.line) +
          '&rdquo;</div><div class="small muted">page ' + f.page + " &middot; confidence " + Number(f.confidence).toFixed(2) + " &middot; " + ver + "</div></td></tr>";
      }).join("") + "</tbody></table></div>" : "";
    var meta = d.file ? '<div class="small muted" style="margin-top:4px">' + esc(d.file) + " &middot; " + (d.route === "vision" ? "scan, vision path" : "text layer") + " &middot; " + esc(d.extractor) + "</div>" : '<div class="small muted" style="margin-top:4px">No file attached.</div>';
    return '<div class="doc"><h3><span>' + esc(d.label) + "</span><span>" + pill(d.status) + (d.expiry ? ' <span class="small muted">exp. ' + esc(fmtDate(d.expiry)) + "</span>" : "") +
      "</span></h3>" + meta + flagged + checks + fields + "</div>";
  }).join("");
  var related = D.queue.filter(function (q) { return q.entity_id === e.id; }).map(function (q) {
    return "<li><div><b>" + esc(KIND[q.kind] || q.kind) + "</b> &middot; " + esc(q.subject) + '<div class="small muted mono">' + esc(q.idem_key) + "</div></div>" + pill(qStatus(q)) + "</li>";
  }).join("");
  return '<div class="backdrop" data-close="1"></div><aside class="drawer" role="dialog" aria-label="' + esc(e.name) + '">' +
    '<button class="btn x" data-close="1">Close</button><div class="dhead"><div class="small muted">' + esc(e.id) + (isV ? " &middot; vendor" : " &middot; owner") +
    "</div><h2>" + esc(e.name) + "</h2><div style=\"margin-top:6px\">" + pill(e.status) + "</div></div>" +
    '<dl class="kv">' + info + "</dl>" + docs +
    (related ? '<h2 style="margin-top:20px">Queue items</h2><ul class="list">' + related + "</ul>" : "") + "</aside>";
}
function openDrawer(id) {
  var e = findEntity(id);
  var root = document.getElementById("drawerRoot");
  if (!e) { root.innerHTML = ""; return; }
  root.innerHTML = drawerHtml(e);
}
function closeDrawer() { document.getElementById("drawerRoot").innerHTML = ""; }

// ---- router and events -----------------------------------------------------------
function currentView() {
  var h = (location.hash || "#dashboard").slice(1).split("/");
  return {view: VIEWS[h[0]] ? h[0] : "dashboard", id: h[1] || ""};
}
function badge() {
  var n = D.queue.filter(function (q) { return qStatus(q) === "pending"; }).length;
  document.getElementById("pending").textContent = n;
}
function render() {
  var r = currentView();
  var links = document.querySelectorAll("nav a");
  for (var i = 0; i < links.length; i++) links[i].classList.toggle("on", links[i].getAttribute("data-view") === r.view);
  main.innerHTML = VIEWS[r.view]();
  if (r.id) openDrawer(r.id); else closeDrawer();
  badge();
}
window.addEventListener("hashchange", render);
main.addEventListener("input", function (ev) {
  var t = ev.target;
  if (t.id === "fq") F.q = t.value;
  else if (t.id === "fs") F.status = t.value;
  else if (t.id === "ft") F.trade = t.value;
  else return;
  document.getElementById("vbody").innerHTML = vendorRows();
});
document.addEventListener("click", function (ev) {
  var t = ev.target.closest("[data-open],[data-goto],[data-act],[data-qf],[data-close]");
  if (!t) return;
  if (t.hasAttribute("data-close")) { location.hash = currentView().view; return; }
  if (t.hasAttribute("data-open")) { location.hash = t.getAttribute("data-open"); return; }
  if (t.hasAttribute("data-goto")) { F.status = t.getAttribute("data-goto"); F.trade = ""; F.q = ""; location.hash = "vendors"; render(); return; }
  if (t.hasAttribute("data-qf")) { QF = t.getAttribute("data-qf"); render(); return; }
  var act = t.getAttribute("data-act");
  if (act === "reset") { ev.preventDefault(); S = {decisions: {}, trail: []}; saveState(); render(); return; }
  var id = +t.getAttribute("data-id");
  var q = D.queue.filter(function (x) { return x.id === id; })[0];
  if (!q || qStatus(q) !== "pending") return;
  var now = new Date().toISOString().replace("T", " ").slice(0, 19);
  S.decisions[id] = {status: act === "approve" ? "approved" : "rejected", by: "You", at: now};
  S.trail.push({at: now, text: (act === "approve" ? "Approved" : "Rejected") + " #" + id + " " + (KIND[q.kind] || q.kind) +
    " for " + q.entity_name + " (key " + q.idem_key + "). Nothing was sent."});
  saveState(); render();
});
document.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && currentView().id) location.hash = currentView().view; });
render();
})();
</script>
</body>
</html>
"""


def main() -> int:
    from .demo import main as demo_main
    return demo_main([])


if __name__ == "__main__":
    raise SystemExit(main())
