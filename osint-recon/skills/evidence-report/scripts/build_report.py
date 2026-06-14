#!/usr/bin/env python3
"""
osint-recon : build_report.py
================================

Turn a set of OSINT findings + screenshot evidence into a single, self-contained,
court-ready HTML report. The output is ONE .html file: all CSS, JavaScript, and
screenshots (base64-embedded) live inside it, so it opens offline anywhere and can
be archived or attached as a single artifact.

This script uses ONLY the Python standard library (no `pip install`).

Court-ready features
--------------------
  * Per-finding capture metadata: full URL, UTC capture timestamp, capture method,
    page title, HTTP status, and investigator notes.
  * SHA-256 hash of every screenshot, computed from the file bytes at build time
    and printed beside the image (chain-of-custody / integrity).
  * In-browser re-verification: the page recomputes each screenshot's SHA-256 from
    the embedded bytes (Web Crypto) and shows VERIFIED / MISMATCH, so a reviewer
    can confirm nothing was altered after the report was built.
  * Case header (case id, investigator, subject, authorization basis, dates).
  * Search + status/category filtering, screenshot lightbox, and clean print CSS
    (prints/export-to-PDF with every screenshot expanded).

Usage
-----
  # 1. Scaffold a case file you can fill in (or have Claude fill in):
  python3 build_report.py --init case.json --case-id CASE-2026-014 --subject johndoe

  # 2. Build the report from the case file:
  python3 build_report.py case.json --out report.html

Screenshot paths in the case file may be absolute or relative to the case file's
own directory. Run `python3 build_report.py --help` for all options.

Authorized use only. See the plugin NOTICE and the username-search skill's
authorized-use gate.
"""

import argparse
import base64
import hashlib
import html
import json
import os
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# Category -> CSS accent class (purely cosmetic grouping in the report).
KNOWN_CATEGORIES = [
    "social", "dev", "gaming", "forum", "professional",
    "media", "commerce", "crypto", "other",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def esc(value):
    """HTML-escape any value (None -> empty string)."""
    return html.escape("" if value is None else str(value), quote=True)


def sha256_file(path):
    """Return (hex_digest, byte_size) for a file, streaming so big images are fine."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def data_uri(path):
    """Read a file and return a base64 data: URI plus its MIME type."""
    ext = os.path.splitext(path)[1].lower()
    mime = MIME_BY_EXT.get(ext, "application/octet-stream")
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}", mime


def fmt_size(num_bytes):
    """Human-readable byte size."""
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{num_bytes} B"


# --------------------------------------------------------------------------- #
# Case loading / normalization
# --------------------------------------------------------------------------- #

def load_case(case_path):
    with open(case_path, "r", encoding="utf-8") as fh:
        case = json.load(fh)
    if "findings" not in case or not isinstance(case["findings"], list):
        raise SystemExit("[!] Case file must contain a 'findings' array.")
    case.setdefault("case", {})
    return case


def resolve_screenshot(case_dir, ss_path):
    """Resolve a screenshot path: absolute as-is, else relative to the case file."""
    if not ss_path:
        return None
    if os.path.isabs(ss_path):
        return ss_path
    return os.path.normpath(os.path.join(case_dir, ss_path))


def prepare_findings(case, case_dir):
    """Compute hashes + embed images. Returns list of enriched finding dicts."""
    enriched = []
    for i, f in enumerate(case["findings"], start=1):
        item = dict(f)  # shallow copy
        item.setdefault("status", "found")
        item.setdefault("category", "other")
        item["_index"] = i
        ss = resolve_screenshot(case_dir, f.get("screenshot"))
        item["_has_image"] = False
        item["_sha256"] = None
        item["_img_uri"] = None
        item["_img_bytes"] = None
        item["_img_missing"] = False
        if ss:
            if os.path.exists(ss):
                digest, size = sha256_file(ss)
                uri, _mime = data_uri(ss)
                item["_has_image"] = True
                item["_sha256"] = digest
                item["_img_uri"] = uri
                item["_img_bytes"] = size
            else:
                item["_img_missing"] = True
                item["_missing_path"] = ss
        enriched.append(item)
    return enriched


# --------------------------------------------------------------------------- #
# Static assets (kept as plain strings so CSS/JS braces don't fight Python)
# --------------------------------------------------------------------------- #

CSS = r"""
:root{
  --bg:#0f1419; --panel:#161b22; --panel2:#1c232c; --line:#2b3440;
  --ink:#e6edf3; --muted:#8b98a5; --accent:#3fb950; --accent2:#58a6ff;
  --warn:#d29922; --bad:#f85149; --chip:#21262d;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
a{color:var(--accent2);text-decoration:none}
a:hover{text-decoration:underline}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px}

/* Header */
.report-head{background:linear-gradient(135deg,#11161c,#1b2530);border:1px solid var(--line);
  border-radius:14px;padding:24px 26px;margin-bottom:22px}
.brand{display:flex;align-items:center;gap:12px;color:var(--muted);
  font-size:12px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:10px}
.brand .dot{width:9px;height:9px;border-radius:50%;background:var(--accent);
  box-shadow:0 0 0 3px rgba(63,185,80,.18)}
.report-head h1{margin:0 0 4px;font-size:25px;letter-spacing:.2px}
.report-head .subj{color:var(--accent2);font-weight:600}
.meta-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:10px 26px;margin-top:18px}
.meta-grid .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.meta-grid .v{font-size:14px;margin-top:1px}

/* Summary stats */
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 12px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:11px;
  padding:12px 16px;min-width:104px}
.stat .n{font-size:22px;font-weight:700}
.stat .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.stat.found .n{color:var(--accent)}
.stat.review .n{color:var(--warn)}

/* Controls */
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:16px 0 18px;
  position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:5;border-bottom:1px solid var(--line)}
.controls input[type=search]{flex:1;min-width:220px;background:var(--panel);border:1px solid var(--line);
  color:var(--ink);border-radius:9px;padding:10px 12px;font-size:14px}
.filterbtn{background:var(--chip);border:1px solid var(--line);color:var(--muted);
  border-radius:999px;padding:7px 13px;font-size:12.5px;cursor:pointer;text-transform:capitalize}
.filterbtn.active{color:var(--ink);border-color:var(--accent2);background:#15314e}
.count-note{color:var(--muted);font-size:12.5px;margin-left:auto}

/* Finding cards */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;overflow:hidden;
  display:flex;flex-direction:column}
.card .shot{position:relative;background:#0b0e12;cursor:zoom-in;border-bottom:1px solid var(--line);
  aspect-ratio:16/10;overflow:hidden}
.card .shot img{width:100%;height:100%;object-fit:cover;object-position:top;display:block}
.card .shot .noimg{display:flex;align-items:center;justify-content:center;height:100%;
  color:var(--muted);font-size:13px;text-align:center;padding:20px}
.card .shot .expand{position:absolute;right:8px;bottom:8px;background:rgba(0,0,0,.6);
  color:#fff;border-radius:6px;font-size:11px;padding:3px 7px}
.card .body{padding:13px 15px 15px;display:flex;flex-direction:column;gap:9px;flex:1}
.row1{display:flex;align-items:center;gap:8px}
.site{font-weight:700;font-size:15.5px}
.badge{font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;border-radius:6px;
  padding:2px 7px;border:1px solid var(--line);color:var(--muted)}
.badge.cat{margin-left:0}
.badge.status{margin-left:auto}
.badge.found{color:var(--accent);border-color:#1f6f33;background:rgba(63,185,80,.10)}
.badge.review,.badge.waf{color:var(--warn);border-color:#7a5a18;background:rgba(210,153,34,.10)}
.badge.error,.badge.not_found{color:var(--bad);border-color:#7a2620;background:rgba(248,81,73,.08)}
.url{font-size:12.5px;word-break:break-all}
.kv{display:flex;gap:8px;font-size:12px;color:var(--muted)}
.kv b{color:var(--ink);font-weight:600}
.hash{font-size:11px;color:var(--muted);word-break:break-all;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.hash .integrity{font-size:10px;border-radius:5px;padding:1px 6px;border:1px solid var(--line)}
.hash .integrity.ok{color:var(--accent);border-color:#1f6f33}
.hash .integrity.bad{color:var(--bad);border-color:#7a2620}
.hash .integrity.pending{color:var(--muted)}
.notes{font-size:12.5px;color:#c9d4df;background:var(--panel2);border:1px solid var(--line);
  border-radius:8px;padding:8px 10px;white-space:pre-wrap}
.copybtn{background:none;border:1px solid var(--line);color:var(--muted);border-radius:5px;
  font-size:10px;padding:1px 6px;cursor:pointer}
.copybtn:hover{color:var(--ink)}

/* Relevance selection + export */
.selstrip{display:flex;align-items:center;gap:8px;padding:8px 12px;font-size:12px;color:var(--muted);
  background:var(--panel2);border-bottom:1px solid var(--line);cursor:pointer;user-select:none}
.selstrip input{accent-color:var(--accent);width:15px;height:15px;cursor:pointer}
.card.not-relevant{border-style:dashed}
.card.not-relevant .shot,.card.not-relevant .body{opacity:.38}
.exportbar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 18px;
  background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:10px 14px}
.exportbar .lbl{color:var(--muted);font-size:12.5px}
.exportbar .selcount{color:var(--accent);font-weight:700;font-size:15px;margin-right:6px}
.exportbar .sep{flex:1}
.btn{background:var(--chip);border:1px solid var(--line);color:var(--ink);border-radius:8px;
  padding:7px 12px;font-size:12.5px;cursor:pointer}
.btn:hover{border-color:var(--accent2)}
.btn.ghost{background:none;color:var(--muted)}
.btn.ghost:hover{color:var(--ink)}
.btn.primary{background:#15314e;border-color:var(--accent2);color:#cfe4ff}
.btn.primary.on{background:#1f6f33;border-color:var(--accent)}

/* Lightbox */
.lb{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;align-items:center;
  justify-content:center;z-index:50;flex-direction:column;padding:24px}
.lb.open{display:flex}
.lb img{max-width:96vw;max-height:82vh;object-fit:contain;border:1px solid #333;border-radius:6px}
.lb .cap{color:#ccc;font-size:13px;margin-top:12px;text-align:center;max-width:90vw}
.lb .x{position:absolute;top:16px;right:22px;color:#fff;font-size:30px;cursor:pointer;line-height:1}

/* Footer */
.foot{margin-top:34px;border-top:1px solid var(--line);padding-top:18px;color:var(--muted);
  font-size:12.5px;line-height:1.7}
.foot h3{color:var(--ink);font-size:13px;text-transform:uppercase;letter-spacing:.08em;margin:0 0 6px}
.hidden{display:none!important}

@media print{
  body{background:#fff;color:#000}
  .controls,.lb,.expand,.copybtn,.exportbar,.selstrip{display:none!important}
  .card.not-relevant{display:none!important}
  .wrap{max-width:none;padding:0}
  .report-head{background:#fff;border-color:#999}
  .card{break-inside:avoid;border-color:#999}
  .card .shot{aspect-ratio:auto;cursor:default}
  .card .shot img{height:auto;object-fit:contain}
  a{color:#000}
  .grid{grid-template-columns:1fr}
}
"""

JS = r"""
(function(){
  // ---- Search + filter -------------------------------------------------
  var search = document.getElementById('q');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var note = document.getElementById('countnote');
  var activeStatus = 'all', activeCat = 'all', relevantOnly = false;
  function isRel(c){ var cb=c.querySelector('.relflag'); return !cb || cb.checked; }

  function apply(){
    var q = (search.value||'').toLowerCase().trim();
    var shown = 0;
    cards.forEach(function(c){
      var hay = c.getAttribute('data-search')||'';
      var st = c.getAttribute('data-status')||'';
      var cat = c.getAttribute('data-category')||'';
      var ok = (!q || hay.indexOf(q)>=0)
            && (activeStatus==='all' || st===activeStatus)
            && (activeCat==='all' || cat===activeCat)
            && (!relevantOnly || isRel(c));
      c.classList.toggle('hidden', !ok);
      if(ok) shown++;
    });
    if(note) note.textContent = shown + ' of ' + cards.length + ' findings shown';
  }
  if(search) search.addEventListener('input', apply);

  Array.prototype.slice.call(document.querySelectorAll('.filterbtn')).forEach(function(b){
    b.addEventListener('click', function(){
      var grp = b.getAttribute('data-group');
      var val = b.getAttribute('data-value');
      document.querySelectorAll('.filterbtn[data-group="'+grp+'"]').forEach(function(x){x.classList.remove('active');});
      b.classList.add('active');
      if(grp==='status') activeStatus = val; else activeCat = val;
      apply();
    });
  });

  // ---- Lightbox --------------------------------------------------------
  var lb = document.getElementById('lb');
  var lbImg = document.getElementById('lbimg');
  var lbCap = document.getElementById('lbcap');
  document.querySelectorAll('.shot[data-full]').forEach(function(s){
    s.addEventListener('click', function(){
      lbImg.src = s.getAttribute('data-full');
      lbCap.textContent = s.getAttribute('data-cap')||'';
      lb.classList.add('open');
    });
  });
  function closeLb(){ lb.classList.remove('open'); lbImg.src=''; }
  if(lb){
    lb.addEventListener('click', function(e){ if(e.target===lb || e.target.classList.contains('x')) closeLb(); });
    document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeLb(); });
  }

  // ---- Copy hash -------------------------------------------------------
  document.querySelectorAll('.copybtn').forEach(function(b){
    b.addEventListener('click', function(){
      var t = b.getAttribute('data-copy')||'';
      if(navigator.clipboard){ navigator.clipboard.writeText(t).then(function(){
        var old=b.textContent; b.textContent='copied'; setTimeout(function(){b.textContent=old;},900);
      }); }
    });
  });

  // ---- In-browser integrity re-verification (Web Crypto) ---------------
  // Recompute SHA-256 of each embedded screenshot and compare to the value
  // recorded at build time. Confirms the image was not altered post-build.
  function b64ToBytes(dataUri){
    var b64 = dataUri.split(',')[1] || '';
    var bin = atob(b64); var len = bin.length; var bytes = new Uint8Array(len);
    for(var i=0;i<len;i++) bytes[i]=bin.charCodeAt(i);
    return bytes;
  }
  function hex(buf){
    return Array.prototype.map.call(new Uint8Array(buf), function(b){
      return ('0'+b.toString(16)).slice(-2);
    }).join('');
  }
  if(window.crypto && window.crypto.subtle){
    document.querySelectorAll('.shot[data-full][data-sha256]').forEach(function(s){
      try{
        var bytes = b64ToBytes(s.getAttribute('data-full'));
        var expected = s.getAttribute('data-sha256');
        var badge = document.querySelector('.integrity[data-for="'+s.getAttribute('data-id')+'"]');
        window.crypto.subtle.digest('SHA-256', bytes).then(function(buf){
          var got = hex(buf);
          if(!badge) return;
          if(got===expected){ badge.textContent='✓ integrity verified'; badge.className='integrity ok'; }
          else { badge.textContent='✗ hash mismatch'; badge.className='integrity bad'; }
        });
      }catch(e){ /* leave as recorded */ }
    });
  }

  // ---- Relevance selection + export -----------------------------------
  var selcount = document.getElementById('selcount');
  var STORE_KEY = 'osint-evidence-' + ((window.CASE && CASE.case_id) ? CASE.case_id : 'case');

  function relCards(){ return cards.filter(isRel); }
  function updateSel(){
    var n = relCards().length;
    if(selcount) selcount.textContent = n;
    cards.forEach(function(c){ c.classList.toggle('not-relevant', !isRel(c)); });
    persist();
  }
  function persist(){
    try{
      var sel = {};
      cards.forEach(function(c){ var cb=c.querySelector('.relflag'); if(cb) sel[cb.getAttribute('data-idx')]=cb.checked; });
      localStorage.setItem(STORE_KEY, JSON.stringify(sel));
    }catch(e){}
  }
  function restore(){
    try{
      var raw = localStorage.getItem(STORE_KEY); if(!raw) return;
      var sel = JSON.parse(raw);
      cards.forEach(function(c){ var cb=c.querySelector('.relflag'); var k=cb&&cb.getAttribute('data-idx');
        if(cb && k in sel) cb.checked = !!sel[k]; });
    }catch(e){}
  }

  cards.forEach(function(c){ var cb=c.querySelector('.relflag');
    if(cb) cb.addEventListener('change', function(){ updateSel(); if(relevantOnly) apply(); }); });

  function setAll(v){ cards.forEach(function(c){ var cb=c.querySelector('.relflag'); if(cb) cb.checked=v; });
    updateSel(); if(relevantOnly) apply(); }
  function onlyFound(){ cards.forEach(function(c){ var cb=c.querySelector('.relflag');
    if(cb) cb.checked = (c.getAttribute('data-status')==='found'); }); updateSel(); if(relevantOnly) apply(); }

  var bAll=document.getElementById('selall'), bNone=document.getElementById('selnone'),
      bFound=document.getElementById('selfound'), bRel=document.getElementById('relonly');
  if(bAll) bAll.addEventListener('click', function(){ setAll(true); });
  if(bNone) bNone.addEventListener('click', function(){ setAll(false); });
  if(bFound) bFound.addEventListener('click', onlyFound);
  if(bRel) bRel.addEventListener('click', function(){ relevantOnly=!relevantOnly;
    bRel.classList.toggle('primary', relevantOnly); bRel.classList.toggle('on', relevantOnly);
    bRel.textContent = relevantOnly ? 'Showing relevant only' : 'Show relevant only'; apply(); });

  // ---- Export the selected (relevant) subset --------------------------
  function selectedFindings(){
    var keep={}; relCards().forEach(function(c){ keep[c.querySelector('.relflag').getAttribute('data-idx')]=1; });
    return (window.FINDINGS||[]).filter(function(f){ return keep[String(f.idx)]; });
  }
  function download(name, text, mime){
    var blob = new Blob([text], {type:mime||'text/plain'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a'); a.href=url; a.download=name;
    document.body.appendChild(a); a.click();
    setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);
  }
  function fname(ext){ var base=(window.CASE&&(CASE.case_id||CASE.subject))||'evidence';
    return 'relevant_'+String(base).replace(/[^A-Za-z0-9_.-]+/g,'_')+'.'+ext; }
  function csvCell(v){ v=(v==null?'':String(v)); return '"'+v.replace(/"/g,'""')+'"'; }
  function exportCSV(){
    var cols=['site','category','status','profile_url','captured_at','method','page_title','http_status','sha256','screenshot','notes'];
    var rows=[cols.join(',')];
    selectedFindings().forEach(function(f){ rows.push(cols.map(function(k){ return csvCell(f[k]); }).join(',')); });
    if(rows.length<2){ alert('Nothing selected to export.'); return; }
    download(fname('csv'), rows.join('\r\n'), 'text/csv');
  }
  function caseJSON(){
    var keep=['site','category','status','profile_url','captured_url','captured_at',
              'method','page_title','http_status','screenshot','notes','sha256'];
    var findings = selectedFindings().map(function(f){ var o={};
      keep.forEach(function(k){ if(f[k]!==undefined && f[k]!==null && f[k]!=='') o[k]=f[k]; }); return o; });
    return JSON.stringify({schema:(window.SCHEMA||'1.0'), case:(window.CASE||{}), findings:findings}, null, 2);
  }
  function exportJSON(){
    if(!selectedFindings().length){ alert('Nothing selected to export.'); return; }
    download(fname('json'), caseJSON(), 'application/json');
  }
  function copyForClaude(){
    var fs=selectedFindings(); if(!fs.length){ alert('Nothing selected to copy.'); return; }
    var subj=(window.CASE&&CASE.subject)||'the subject';
    var cid=(window.CASE&&CASE.case_id)||'';
    var msg='Here are '+fs.length+' relevant OSINT evidence findings for '+subj
          +(cid?(' (case '+cid+')'):'')+'. Please build an evidence summary from them '
          +'(or a new report). This JSON uses the osint-recon case-file schema:\n\n'
          +'```json\n'+caseJSON()+'\n```';
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(msg).then(function(){ flash('copyclaude','Copied ✓'); },
        function(){ alert('Copy failed. Your browser blocked clipboard access.'); });
    } else { alert('Clipboard not available in this browser.'); }
  }
  function flash(id,txt){ var b=document.getElementById(id); if(!b) return;
    var o=b.textContent; b.textContent=txt; setTimeout(function(){ b.textContent=o; }, 1100); }

  var bCsv=document.getElementById('expcsv'), bJson=document.getElementById('expjson'),
      bClaude=document.getElementById('copyclaude');
  if(bCsv) bCsv.addEventListener('click', exportCSV);
  if(bJson) bJson.addEventListener('click', exportJSON);
  if(bClaude) bClaude.addEventListener('click', copyForClaude);

  restore();
  updateSel();
  apply();
})();
"""


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #

def render_card(f):
    idx = f["_index"]
    site = esc(f.get("site") or "(unnamed site)")
    status = esc(f.get("status") or "found")
    status_class = status if status in ("found", "not_found", "waf", "error") else "review"
    category = esc(f.get("category") or "other")
    url = f.get("profile_url") or f.get("captured_url") or ""
    url_e = esc(url)
    captured_at = esc(f.get("captured_at") or "")
    method = esc(f.get("method") or "")
    page_title = esc(f.get("page_title") or "")
    http_status = f.get("http_status")
    notes = f.get("notes") or ""
    search_blob = esc(" ".join(str(x) for x in [
        f.get("site"), url, f.get("category"), f.get("status"),
        page_title, notes,
    ] if x))

    # Screenshot block
    shot_id = f"shot{idx}"
    if f["_has_image"]:
        cap = f"{f.get('site','')}  |  {url}  |  captured {f.get('captured_at','')}"
        shot = (
            f'<div class="shot" data-id="{shot_id}" data-full="{esc(f["_img_uri"])}" '
            f'data-sha256="{esc(f["_sha256"])}" data-cap="{esc(cap)}">'
            f'<img loading="lazy" src="{esc(f["_img_uri"])}" alt="Screenshot evidence: {site}">'
            f'<span class="expand">click to enlarge</span></div>'
        )
        size = fmt_size(f["_img_bytes"])
        hash_row = (
            f'<div class="hash mono">SHA-256 {esc(f["_sha256"])}'
            f'<button class="copybtn" data-copy="{esc(f["_sha256"])}">copy</button>'
            f'<span class="integrity pending" data-for="{shot_id}">checking…</span>'
            f'<span style="color:var(--muted)">({size})</span></div>'
        )
    elif f.get("_img_missing"):
        shot = (f'<div class="shot"><div class="noimg">screenshot file not found<br>'
                f'<span class="mono">{esc(f.get("_missing_path"))}</span></div></div>')
        hash_row = '<div class="hash">SHA-256 <span style="color:var(--bad)">n/a (file missing)</span></div>'
    else:
        shot = '<div class="shot"><div class="noimg">no screenshot captured</div></div>'
        hash_row = ''

    url_html = f'<a class="url" href="{url_e}" target="_blank" rel="noopener noreferrer">{url_e}</a>' if url else ''
    title_html = f'<div class="kv"><span>Title:</span> <b>{page_title}</b></div>' if page_title else ''
    cap_html = f'<div class="kv"><span>Captured (UTC):</span> <b>{captured_at}</b></div>' if captured_at else ''
    method_bits = []
    if method:
        method_bits.append(f"via {method}")
    if http_status not in (None, ""):
        method_bits.append(f"HTTP {esc(http_status)}")
    method_html = f'<div class="kv"><span>Method:</span> <b>{esc(" · ".join(method_bits))}</b></div>' if method_bits else ''
    notes_html = f'<div class="notes">{esc(notes)}</div>' if notes else ''

    return (
        f'<div class="card" data-idx="{idx}" data-status="{status}" data-category="{category}" data-search="{search_blob}">'
        f'<label class="selstrip"><input type="checkbox" class="relflag" data-idx="{idx}" checked> '
        f'Relevant, include in export</label>'
        f'{shot}'
        f'<div class="body">'
        f'<div class="row1"><span class="site">{site}</span>'
        f'<span class="badge cat">{category}</span>'
        f'<span class="badge status {status_class}">{status.replace("_"," ")}</span></div>'
        f'{url_html}{cap_html}{title_html}{method_html}{hash_row}{notes_html}'
        f'</div></div>'
    )


def render_report(case, enriched):
    c = case.get("case", {})
    title = c.get("title") or (f"Username footprint for {c.get('subject','')}" if c.get("subject") else "OSINT evidence report")
    subject = c.get("subject") or ""
    generated = now_utc_iso()

    # Summary counts
    total = len(enriched)
    by_status = {}
    cats_present = set()
    for f in enriched:
        by_status[f.get("status", "found")] = by_status.get(f.get("status", "found"), 0) + 1
        cats_present.add(f.get("category", "other"))
    found_n = by_status.get("found", 0)
    review_n = by_status.get("waf", 0) + by_status.get("error", 0)
    with_shots = sum(1 for f in enriched if f["_has_image"])

    # Header meta rows
    meta_fields = [
        ("Case ID", c.get("case_id")),
        ("Investigator", c.get("investigator") or c.get("examiner")),
        ("Subject username", subject),
        ("Authorization basis", c.get("authorization")),
        ("Opened", c.get("opened")),
        ("Report generated (UTC)", generated),
    ]
    meta_html = "".join(
        f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v) if v else "Not provided"}</div></div>'
        for k, v in meta_fields
    )

    # Stats
    stats_html = (
        f'<div class="stat found"><div class="n">{found_n}</div><div class="l">Accounts found</div></div>'
        f'<div class="stat"><div class="n">{total}</div><div class="l">Findings logged</div></div>'
        f'<div class="stat"><div class="n">{with_shots}</div><div class="l">With screenshot</div></div>'
    )
    if review_n:
        stats_html += f'<div class="stat review"><div class="n">{review_n}</div><div class="l">Needs review</div></div>'

    # Status filter buttons (only those present, plus "all")
    status_order = ["found", "not_found", "waf", "error"]
    present_statuses = [s for s in status_order if s in by_status] + \
        [s for s in by_status if s not in status_order]
    status_btns = '<button class="filterbtn active" data-group="status" data-value="all">all status</button>'
    for s in present_statuses:
        status_btns += f'<button class="filterbtn" data-group="status" data-value="{esc(s)}">{esc(s.replace("_"," "))}</button>'

    # Category filter buttons
    cat_btns = '<button class="filterbtn active" data-group="category" data-value="all">all categories</button>'
    for cat in sorted(cats_present):
        cat_btns += f'<button class="filterbtn" data-group="category" data-value="{esc(cat)}">{esc(cat)}</button>'

    cards_html = "".join(render_card(f) for f in enriched) or \
        '<p style="color:var(--muted)">No findings in this case file.</p>'

    methodology = esc(c.get("methodology") or
        "Findings were collected by navigating to each candidate profile URL in a "
        "real browser (browser automation MCP) and capturing a full screenshot of "
        "the rendered page. Only publicly accessible pages were viewed; no "
        "authentication, login, or access control was bypassed. Each screenshot's "
        "SHA-256 was computed from the saved file at report-build time.")
    case_notes = c.get("notes")
    notes_block = f'<p>{esc(case_notes)}</p>' if case_notes else ''

    parts = []
    parts.append("<!doctype html>")
    parts.append('<html lang="en"><head><meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f'<title>{esc(title)}</title>')
    parts.append('<meta name="generator" content="osint-recon evidence-report ' + SCHEMA_VERSION + '">')
    parts.append(f"<style>{CSS}</style></head><body><div class='wrap'>")

    # Header
    parts.append('<div class="report-head">')
    parts.append('<div class="brand"><span class="dot"></span> Claude OSINT Investigator</div>')
    parts.append(f'<h1>{esc(title)}</h1>')
    if subject:
        parts.append(f'<div>Subject username: <span class="subj">{esc(subject)}</span></div>')
    parts.append(f'<div class="meta-grid">{meta_html}</div>')
    parts.append('</div>')

    # Stats
    parts.append(f'<div class="stats">{stats_html}</div>')

    # Controls
    parts.append('<div class="controls">')
    parts.append('<input id="q" type="search" placeholder="Search site, URL, notes…" autocomplete="off">')
    parts.append(status_btns)
    parts.append(cat_btns)
    parts.append('<span class="count-note" id="countnote"></span>')
    parts.append('</div>')

    # Relevance selection + export toolbar
    parts.append('<div class="exportbar">')
    parts.append('<span class="lbl">Relevant selected:</span><span class="selcount" id="selcount">0</span>')
    parts.append('<button class="btn ghost" id="selall">Select all</button>')
    parts.append('<button class="btn ghost" id="selnone">None</button>')
    parts.append('<button class="btn ghost" id="selfound">Only &ldquo;found&rdquo;</button>')
    parts.append('<button class="btn ghost" id="relonly">Show relevant only</button>')
    parts.append('<span class="sep"></span>')
    parts.append('<button class="btn" id="expcsv">Export CSV</button>')
    parts.append('<button class="btn primary" id="expjson">Export JSON (case file)</button>')
    parts.append('<button class="btn primary" id="copyclaude">Copy for Claude</button>')
    parts.append('</div>')

    # Grid
    parts.append(f'<div class="grid">{cards_html}</div>')

    # Footer
    parts.append('<div class="foot">')
    parts.append('<h3>Methodology</h3>')
    parts.append(f'<p>{methodology}</p>')
    if notes_block:
        parts.append('<h3>Case notes</h3>')
        parts.append(notes_block)
    parts.append('<h3>Integrity &amp; verification</h3>')
    parts.append('<p>Each screenshot is embedded in this file and labelled with the '
                 'SHA-256 digest computed from the original capture. When opened in a '
                 'modern browser, this report recomputes each digest from the embedded '
                 'image bytes and displays &ldquo;integrity verified&rdquo; when they '
                 'match. To verify independently, run '
                 '<code>shasum -a 256 &lt;screenshot-file&gt;</code> against the original '
                 'capture and compare.</p>')
    parts.append('<h3>Evidentiary note</h3>')
    parts.append('<p>A discovered account is an investigative <b>lead</b>, not proof of '
                 'identity: the same username may belong to different people on different '
                 'sites. This report documents what was publicly visible at the capture '
                 'time only. Use for lawful, authorized purposes.</p>')
    parts.append('</div>')

    # Lightbox
    parts.append('<div class="lb" id="lb"><span class="x">&times;</span>'
                 '<img id="lbimg" alt="enlarged screenshot evidence">'
                 '<div class="cap" id="lbcap"></div></div>')

    # Metadata blob for client-side export (no base64, keeps it light).
    findings_js = []
    for f in enriched:
        findings_js.append({
            "idx": f["_index"],
            "site": f.get("site"),
            "category": f.get("category"),
            "status": f.get("status"),
            "profile_url": f.get("profile_url") or f.get("captured_url"),
            "captured_url": f.get("captured_url"),
            "captured_at": f.get("captured_at"),
            "method": f.get("method"),
            "page_title": f.get("page_title"),
            "http_status": f.get("http_status"),
            "sha256": f.get("_sha256"),
            "screenshot": f.get("screenshot"),
            "notes": f.get("notes"),
        })

    def js_var(name, obj):
        # Escape </ so a value can't terminate the <script> early.
        return f"var {name}=" + json.dumps(obj).replace("</", "<\\/") + ";"

    data_blob = ("<script>\n"
                 + js_var("SCHEMA", case.get("schema", "1.0")) + "\n"
                 + js_var("CASE", c) + "\n"
                 + js_var("FINDINGS", findings_js) + "\n</script>")

    parts.append(f"</div>{data_blob}<script>{JS}</script></body></html>")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# --init scaffold
# --------------------------------------------------------------------------- #

def write_template(path, args):
    template = {
        "schema": SCHEMA_VERSION,
        "case": {
            "title": args.title or "",
            "case_id": args.case_id or "",
            "investigator": args.investigator or args.examiner or "",
            "subject": args.subject or "",
            "authorization": "Self-footprint / consented investigation / authorized research",
            "opened": now_utc_iso(),
            "notes": "",
            "methodology": ""
        },
        "findings": [
            {
                "site": "GitHub",
                "category": "dev",
                "status": "found",
                "profile_url": "https://github.com/" + (args.subject or "username"),
                "captured_url": "https://github.com/" + (args.subject or "username"),
                "captured_at": now_utc_iso(),
                "method": "browser-mcp",
                "page_title": "",
                "http_status": 200,
                "screenshot": "evidence/github.png",
                "notes": "Replace this example with real findings."
            }
        ]
    }
    if os.path.exists(path) and not args.force:
        raise SystemExit(f"[!] {path} already exists (use --force to overwrite).")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2)
    print(f"[*] Wrote case template: {path}")
    print("    Fill in 'findings' (one per captured profile), then run:")
    print(f"    python3 {os.path.basename(__file__)} {path} --out report.html")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        prog="build_report.py",
        description="Build a self-contained, court-ready HTML OSINT evidence report "
                    "from a case file of findings + screenshots.",
    )
    p.add_argument("case", nargs="?", help="Path to the case JSON file.")
    p.add_argument("--out", help="Output HTML path (default: <case>.html or report.html).")
    p.add_argument("--init", metavar="CASE_JSON",
                   help="Scaffold a blank case file at this path and exit.")
    p.add_argument("--force", action="store_true", help="Overwrite when using --init.")
    # Optional pre-fills for --init:
    p.add_argument("--title", help="Case title (with --init).")
    p.add_argument("--case-id", dest="case_id", help="Case identifier (with --init).")
    p.add_argument("--investigator", help="Investigator name, optional (with --init).")
    p.add_argument("--examiner", help=argparse.SUPPRESS)  # backward-compatible alias for --investigator
    p.add_argument("--subject", help="Subject username (with --init).")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.init:
        write_template(args.init, args)
        return

    if not args.case:
        raise SystemExit("[!] Provide a case JSON path, or use --init to scaffold one. "
                         "See --help.")

    case_path = os.path.abspath(args.case)
    if not os.path.exists(case_path):
        raise SystemExit(f"[!] Case file not found: {case_path}")
    case_dir = os.path.dirname(case_path)

    case = load_case(case_path)
    enriched = prepare_findings(case, case_dir)
    html_out = render_report(case, enriched)

    out_path = args.out
    if not out_path:
        base, _ = os.path.splitext(case_path)
        out_path = base + ".html"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)

    found = sum(1 for f in enriched if f.get("status") == "found")
    shots = sum(1 for f in enriched if f["_has_image"])
    missing = sum(1 for f in enriched if f.get("_img_missing"))
    print(f"[*] Report written: {out_path}")
    print(f"    {len(enriched)} findings  |  {found} found  |  {shots} screenshots embedded"
          + (f"  |  {missing} screenshot file(s) MISSING" if missing else ""))
    if missing:
        print("[!] Some screenshot paths did not resolve. Check the case file.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
