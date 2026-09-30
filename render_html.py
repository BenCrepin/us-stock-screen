"""
Builds the shareable web page for a screen run (Section 14 of the rules).

Called by screen.write_archive() on every run, so each archive folder gets:
  report.html     standalone page, opens in any browser (OneDrive share link works)
  artifact.html   the same page as a fragment for publishing on claude.ai, where
                  viewers keep personal watchlists in the page's database.

By hand, on an existing archive folder:
    python render_html.py archive/2026-09-29
"""
import argparse
import glob
import html
import json
import math
import os
import re

import pandas as pd

WINDOWS = (20, 50, 100, 200)

REASON_GROUPS = [
    (r"outside band", "Outside SMA200 band"),
    (r"^growth .* below threshold", "Reported growth under 10%"),
    (r"^expected growth", "Expected growth under 10%"),
    (r"non-positive", "Loss-making quarter"),
    (r"stale filing", "Stale filing"),
    (r"analysts|no consensus", "Thin analyst coverage"),
    (r"insufficient|no reported", "Insufficient data"),
    (r"market cap|price below|illiquid|not common", "Universe filter"),
]


def reason_group(reason):
    for pat, label in REASON_GROUPS:
        if re.search(pat, str(reason)):
            return label
    return "Other"


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _bool(v):
    if isinstance(v, str):
        return v.strip().lower() == "true"
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return bool(v)


def _date(v):
    s = "" if v is None else str(v)
    return "" if s in ("nan", "None", "NaT") else s[:10]


def esc(v):
    return html.escape("" if v is None else str(v))


def pct(v, signed=True, dp=1):
    f = _num(v)
    if f is None:
        return "n/a"
    return f"{f:+.{dp}%}" if signed else f"{f:.{dp}%}"


def money(v, dp=2):
    f = _num(v)
    return "n/a" if f is None else f"{f:,.{dp}f}"


def band_distance(reason):
    m = re.search(r"distance ([+-][0-9.]+)% outside band", str(reason))
    return float(m.group(1)) / 100 if m else None


def sma_cells(row):
    """Four cells: sessions below each SMA (tinted) or 'above' (quiet)."""
    out = []
    for w in WINDOWS:
        below = _bool(row.get(f"below{w}"))
        days = _num(row.get(f"days{w}"))
        if below is None:
            out.append('<td class="num na" data-sort="-1">n/a</td>')
        elif below:
            d = int(days or 0)
            out.append(f'<td class="num below {"hot" if d >= 20 else "warm"}" data-sort="{d}">{d}</td>')
        else:
            out.append('<td class="num above" data-sort="0">above</td>')
    return "".join(out)


def star(ticker):
    return (f'<td class="star-cell"><button type="button" class="star" data-t="{esc(ticker)}" '
            f'aria-pressed="false" aria-label="Watch {esc(ticker)}" title="Add to my watchlist">&#9734;</button></td>')


# ----------------------------------------------------------------------------- tables

def qualifying_rows(q, new_set):
    ncols = 15 + len(WINDOWS)
    if q is None or q.empty or "sector" not in q:
        return f'<tr><td colspan="{ncols}" class="empty">No shares passed all three criteria on this close.</td></tr>'
    q = q.sort_values(["sector", "industry", "ticker"])
    out = []
    for (sector, industry), g in q.groupby(["sector", "industry"], sort=False):
        out.append(f'<tr class="group"><th colspan="{ncols}">{esc(sector)} <span class="sep">/</span> '
                   f'{esc(industry)} <span class="count">{len(g)}</span></th></tr>')
        for _, r in g.iterrows():
            t = str(r["ticker"])
            dist = _num(r.get("distance"))
            side_cls = "pos" if (dist or 0) > 0 else "neg"
            rev = str(r.get("revision_trend", ""))
            rev_cls = {"Up": "pos", "Down": "neg"}.get(rev, "flat")
            ni0, nip = _num(r.get("ni_q0")), _num(r.get("ni_prev"))
            mc = _num(r.get("market_cap"))
            new_badge = ' <span class="badge new">new</span>' if t in new_set else ""
            out.append(
                f'<tr data-t="{esc(t)}">{star(t)}'
                f'<td class="tick"><b>{esc(t)}</b>{new_badge}<span class="co">{esc(r.get("company", ""))}</span></td>'
                f'<td class="num">{money(r.get("close"))}</td>'
                f'<td class="num">{money(r.get("sma200"))}<span class="sub {side_cls}">{pct(dist, dp=2)}</span></td>'
                f'<td class="slope {esc(str(r.get("slope", "")).lower())}">{esc(r.get("slope"))}</td>'
                f'<td class="num">{money(r.get("ytd_high"))}<span class="sub">{esc(_date(r.get("ytd_high_date")))}</span></td>'
                f'<td class="num neg">{pct(r.get("off_ytd_high"))}</td>'
                f'<td class="num">{money(ni0 / 1e6 if ni0 is not None else None, 1)}'
                f'<span class="sub">prev {money(nip / 1e6 if nip is not None else None, 1)}</span></td>'
                f'<td class="num pos strong">{pct(r.get("growth"), signed=False)}</td>'
                f'<td class="num">{money(r.get("eps_actual_q0"))}<span class="sub">est {money(r.get("eps_est_q1"))}</span></td>'
                f'<td class="num pos strong">{pct(r.get("expected_growth"), signed=False)}</td>'
                f'<td class="num">{int(_num(r.get("analysts")) or 0)}<span class="sub {rev_cls}">{esc(rev)}</span></td>'
                f'<td class="date">{esc(_date(r.get("q0_end")))}</td>'
                f'<td class="num">{money(mc / 1e9 if mc is not None else None, 1)}</td>'
                f"{sma_cells(r)}</tr>")
    return "\n".join(out)


def monitoring_rows(m):
    if m is None or m.empty:
        return ""
    out = []
    for _, r in m.sort_values("ticker").iterrows():
        t = str(r["ticker"])
        grp = reason_group(r.get("reason"))
        dist = band_distance(r.get("reason"))
        if dist is not None:
            dist_html = f'<td class="num {"pos" if dist > 0 else "neg"}" data-sort="{dist:.4f}">{pct(dist)}</td>'
        else:
            dist_html = '<td class="num in-band" data-sort="0">in band</td>'
        out.append(
            f'<tr data-t="{esc(t)}" data-group="{esc(grp)}">{star(t)}'
            f'<td class="tick"><b>{esc(t)}</b></td>'
            f'<td class="reason"><span class="chip">{esc(grp)}</span></td>'
            f"{dist_html}"
            f'<td class="num">{money(r.get("ytd_high"))}<span class="sub">{esc(_date(r.get("ytd_high_date")))}</span></td>'
            f'<td class="num neg">{pct(r.get("off_ytd_high"))}</td>'
            f"{sma_cells(r)}</tr>")
    return "\n".join(out)


def data_map(q, m):
    """Compact per-ticker record the page uses to render watchlists."""
    d = {}

    def trend(row):
        o = {}
        for w in WINDOWS:
            b = _bool(row.get(f"below{w}"))
            o[f"d{w}"] = None if b is None else (int(_num(row.get(f"days{w}")) or 0) if b else 0)
        return o

    if m is not None and not m.empty:
        for _, r in m.iterrows():
            d[str(r["ticker"])] = dict(
                s=reason_group(r.get("reason")), dist=band_distance(r.get("reason")),
                hi=_num(r.get("ytd_high")), hd=_date(r.get("ytd_high_date")), off=_num(r.get("off_ytd_high")),
                **trend(r))
    if q is not None and not q.empty and "ticker" in q:
        for _, r in q.iterrows():
            d[str(r["ticker"])] = dict(
                s="Qualifying", co=str(r.get("company", "")), ind=str(r.get("industry", "")),
                dist=_num(r.get("distance")), close=_num(r.get("close")),
                hi=_num(r.get("ytd_high")), hd=_date(r.get("ytd_high_date")), off=_num(r.get("off_ytd_high")),
                g=_num(r.get("growth")), eg=_num(r.get("expected_growth")), **trend(r))
    return d


# ----------------------------------------------------------------------------- page

STYLE = """
<style>
/* Layout: header + summary tiles, personal watchlist, then two full-width data tables.
   Teal-biased slate neutrals, mono numerals, semantic green/red kept separate from the accent. */
:root{
  --bg:#f4f6f7; --panel:#ffffff; --fg:#1b2429; --muted:#5c6b73; --line:#d9e0e3;
  --accent:#0e6f74; --accent-soft:#dcefef; --star:#c98a1a;
  --pos:#1f7a4d; --neg:#b3392f; --warm:#fbe9d2; --hot:#f5c8c2; --new:#e8f1fb; --new-fg:#22558a;
  --display:"Instrument Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#111719; --panel:#181f22; --fg:#e6ecee; --muted:#93a3aa; --line:#2a3438;
  --accent:#5fc3c7; --accent-soft:#163538; --star:#e9b64a; --pos:#5ccf8f; --neg:#f08a7d;
  --warm:#4a3418; --hot:#5a231c; --new:#1a2c40; --new-fg:#8fb8e8; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#111719; --panel:#181f22; --fg:#e6ecee; --muted:#93a3aa; --line:#2a3438;
  --accent:#5fc3c7; --accent-soft:#163538; --star:#e9b64a; --pos:#5ccf8f; --neg:#f08a7d;
  --warm:#4a3418; --hot:#5a231c; --new:#1a2c40; --new-fg:#8fb8e8; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--display);margin:0;padding-block:24px 48px;padding-inline:clamp(16px,3vw,40px);line-height:1.45}
h1,h2{text-wrap:balance;margin:0}
h1{font-size:clamp(22px,3vw,30px);font-weight:600;letter-spacing:-.01em}
h2{font-size:17px;font-weight:600;margin-block:32px 10px;display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
h2 .n{font-family:var(--mono);font-size:13px;color:var(--muted);font-weight:400}
.meta{font-family:var(--mono);font-size:12.5px;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:6px}
.meta b{color:var(--fg);font-weight:500}
.rules{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}
.rules span{font-size:12.5px;padding:4px 10px;border-radius:999px;background:var(--accent-soft);color:var(--accent)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:22px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;min-width:0}
.tile .k{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.tile .v{font-family:var(--mono);font-size:26px;font-weight:500;line-height:1.1;margin-top:6px;font-variant-numeric:tabular-nums}
.tile .v small{font-size:13px;color:var(--muted);margin-left:4px}
.tile.accent .v{color:var(--accent)}
.changes{font-size:13px;color:var(--muted);margin-top:10px;display:flex;flex-wrap:wrap;gap:4px 18px}
.changes b{font-family:var(--mono);font-weight:500;color:var(--fg)}
.sectors{list-style:none;padding:0;margin:0;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px}
.sectors li{display:flex;gap:6px;align-items:baseline}
.sectors b{font-family:var(--mono);font-weight:500;color:var(--accent)}
.controls{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin-bottom:8px;font-size:13px}
.controls input,.controls select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--fg);min-width:0}
.controls input[type=search]{width:min(240px,100%)}
.controls label{display:flex;gap:6px;align-items:center;cursor:pointer}
.controls .shown{font-family:var(--mono);color:var(--muted);font-size:12px;margin-left:auto}
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:900px}
#watch{min-width:700px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;white-space:nowrap}
thead th{position:sticky;top:0;background:var(--panel);font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:500;z-index:1;cursor:pointer;user-select:none}
thead th.num{text-align:right}
thead th.star-cell{cursor:default;width:34px}
thead th[aria-sort="ascending"]::after{content:" \\2191";color:var(--accent)}
thead th[aria-sort="descending"]::after{content:" \\2193";color:var(--accent)}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:color-mix(in srgb,var(--accent-soft) 40%,transparent)}
tr.group th{background:var(--bg);font-weight:500;font-size:12.5px;color:var(--fg);padding-block:8px}
tr.group .sep{color:var(--muted);margin-inline:4px}
tr.group .count{font-family:var(--mono);color:var(--muted);margin-left:8px;font-size:12px}
td.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums}
td .sub{display:block;font-size:11px;color:var(--muted);font-family:var(--mono)}
td .co{display:block;font-size:11.5px;color:var(--muted);font-weight:400;max-width:180px;overflow:hidden;text-overflow:ellipsis}
td.tick b{font-family:var(--mono);font-weight:600;letter-spacing:.02em}
.pos{color:var(--pos)} .neg{color:var(--neg)} .flat{color:var(--muted)}
td .sub.pos{color:var(--pos)} td .sub.neg{color:var(--neg)}
td.strong{font-weight:600}
td.slope{font-size:12px} td.slope.rising{color:var(--pos)} td.slope.falling{color:var(--neg)} td.slope.flat{color:var(--muted)}
td.below.warm{background:var(--warm)} td.below.hot{background:var(--hot);font-weight:600}
td.above,td.in-band{color:var(--muted);font-size:11.5px;font-family:var(--display)}
td.na{color:var(--muted)}
td.date{font-family:var(--mono);color:var(--muted)}
.chip{font-size:11.5px;padding:2px 8px;border-radius:999px;background:var(--bg);border:1px solid var(--line);color:var(--muted)}
.chip.q{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.badge{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;padding:1px 6px;border-radius:4px;vertical-align:2px;margin-left:6px;font-family:var(--display);font-weight:600}
.badge.new{background:var(--new);color:var(--new-fg)}
td.empty{text-align:center;color:var(--muted);padding-block:28px;white-space:normal}
td.star-cell{padding:4px 6px;width:34px}
.star{background:none;border:0;cursor:pointer;font-size:18px;line-height:1;color:var(--muted);padding:2px 4px;border-radius:4px}
.star:hover{color:var(--star)}
.star[aria-pressed="true"]{color:var(--star)}
.remove{background:none;border:1px solid var(--line);color:var(--muted);border-radius:4px;padding:2px 8px;font:inherit;font-size:12px;cursor:pointer}
.remove:hover{color:var(--neg);border-color:var(--neg)}
.note{font-size:12.5px;color:var(--muted)}
.note.warn{color:var(--neg)}
.legend{font-size:12px;color:var(--muted);margin-top:8px;display:flex;flex-wrap:wrap;gap:6px 16px}
.legend i{display:inline-block;width:12px;height:12px;border-radius:2px;vertical-align:-2px;margin-right:4px;border:1px solid var(--line)}
.legend .w{background:var(--warm)} .legend .h{background:var(--hot)}
.foot{margin-top:28px;font-size:12px;color:var(--muted);max-width:70ch}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:600px){.tile .v{font-size:22px}}
@media (prefers-reduced-motion:no-preference){.star{transition:transform .12s}.star:active{transform:scale(1.25)}}
</style>"""

SCRIPT = r"""
<script>
(function(){
  'use strict';
  var DATA = JSON.parse(document.getElementById('screen-data').textContent);
  var W = [20,50,100,200];
  var watch = {};                 // ticker -> {added:'YYYY-MM-DD'}
  var mode = 'local';             // 'cloud' once the page database is available for this viewer
  var ref = null, writeChain = Promise.resolve();
  var use = (window.claude && typeof window.claude.use === 'function') ? function(n){return window.claude.use(n);} : function(){return Promise.resolve(null);};

  // ---------- storage
  function loadLocal(){ try{ var s=localStorage.getItem('screen-watchlist'); if(s) watch=JSON.parse(s)||{}; }catch(e){} }
  function saveLocal(){ try{ localStorage.setItem('screen-watchlist', JSON.stringify(watch)); }catch(e){} }
  function persist(){
    if(mode==='cloud' && ref){
      var body={tickers:JSON.parse(JSON.stringify(watch)),updated:new Date().toISOString()};
      writeChain = writeChain.then(function(){ return ref.set(body); }).catch(function(e){
        if(e && e.code==='invalid_argument'){ mode='local'; saveLocal(); setNote('You have view-only access to this page, so your watchlist is saved in this browser only.', true); }
      });
    } else { saveLocal(); }
  }
  function setNote(text, warn){ var n=document.getElementById('watch-note'); n.textContent=text; n.className='note'+(warn?' warn':''); }

  // ---------- rendering
  function fmtPct(v,dp){ return (v===null||v===undefined)?'n/a':((v>0?'+':'')+(v*100).toFixed(dp===undefined?1:dp)+'%'); }
  function fmtNum(v,dp){ return (v===null||v===undefined)?'n/a':Number(v).toLocaleString(undefined,{minimumFractionDigits:dp,maximumFractionDigits:dp}); }
  function smaTd(d){
    if(d===null||d===undefined) return '<td class="num na">n/a</td>';
    if(d===0) return '<td class="num above">above</td>';
    return '<td class="num below '+(d>=20?'hot':'warm')+'">'+d+'</td>';
  }
  function esc(s){ return String(s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function renderWatch(){
    var body=document.getElementById('watch-body'), keys=Object.keys(watch).sort(), html='';
    if(!keys.length){
      html='<tr><td colspan="'+(8+W.length)+'" class="empty">Nothing watched yet. Use the &#9734; on any row below to add it here.</td></tr>';
    } else keys.forEach(function(t){
      var r=DATA.tickers[t], added=(watch[t]&&watch[t].added)||'';
      if(!r){ html+='<tr><td class="tick"><b>'+esc(t)+'</b></td><td colspan="'+(6+W.length)+'" class="note">Not in the current universe</td><td><button type="button" class="remove" data-t="'+esc(t)+'">Remove</button></td></tr>'; return; }
      var q=r.s==='Qualifying';
      html+='<tr data-t="'+esc(t)+'">'
        +'<td class="tick"><b>'+esc(t)+'</b>'+(r.co?'<span class="co">'+esc(r.co)+'</span>':'')+'</td>'
        +'<td><span class="chip'+(q?' q':'')+'">'+esc(r.s)+'</span>'+(q&&r.ind?'<span class="sub">'+esc(r.ind)+'</span>':'')+'</td>'
        +'<td class="num '+(r.dist===null?'in-band':(r.dist>0?'pos':'neg'))+'">'+(r.dist===null?'in band':fmtPct(r.dist,q?2:1))+'</td>'
        +'<td class="num">'+fmtNum(r.hi,2)+'<span class="sub">'+esc(r.hd||'')+'</span></td>'
        +'<td class="num neg">'+fmtPct(r.off)+'</td>'
        +W.map(function(w){return smaTd(r['d'+w]);}).join('')
        +'<td class="date">'+esc(added)+'</td>'
        +'<td><button type="button" class="remove" data-t="'+esc(t)+'">Remove</button></td></tr>';
    });
    body.innerHTML=html;
    document.getElementById('watch-count').textContent=keys.length+' watched';
    document.querySelectorAll('button.star').forEach(function(b){ b.setAttribute('aria-pressed', watch[b.dataset.t]?'true':'false'); b.textContent = watch[b.dataset.t]?'★':'☆'; b.title = watch[b.dataset.t]?'Remove from my watchlist':'Add to my watchlist'; });
    applyFilter();
  }
  function toggle(t){
    if(watch[t]) delete watch[t]; else watch[t]={added:DATA.asof||new Date().toISOString().slice(0,10)};
    renderWatch(); persist();
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest('button.star, button.remove'); if(!b) return;
    toggle(b.dataset.t);
  });

  // ---------- monitoring filter
  var text=document.getElementById('q-filter'), grp=document.getElementById('g-filter'), only=document.getElementById('w-filter'),
      rows=Array.prototype.slice.call(document.querySelectorAll('#mon tbody tr')), shown=document.getElementById('shown');
  function applyFilter(){
    var t=text.value.trim().toUpperCase(), g=grp.value, w=only.checked, n=0;
    rows.forEach(function(r){ var ok=(!t||r.dataset.t.indexOf(t)===0)&&(!g||r.dataset.group===g)&&(!w||!!watch[r.dataset.t]); r.hidden=!ok; if(ok)n++; });
    shown.textContent=n+' of '+rows.length+' shown';
  }
  text.addEventListener('input',applyFilter); grp.addEventListener('change',applyFilter); only.addEventListener('change',applyFilter);
  try{ var s=localStorage.getItem('screen-group'); if(s) grp.value=s; }catch(e){}
  grp.addEventListener('change',function(){ try{ localStorage.setItem('screen-group',grp.value); }catch(e){} });

  // ---------- sortable headers
  function sortable(table){
    var ths=Array.prototype.slice.call(table.querySelectorAll('thead th'));
    ths.forEach(function(th,i){
      if(th.classList.contains('star-cell')) return;
      th.addEventListener('click',function(){
        var body=table.tBodies[0], trs=Array.prototype.slice.call(body.rows).filter(function(r){return !r.classList.contains('group');});
        var dir=th.getAttribute('aria-sort')==='ascending'?'descending':'ascending';
        ths.forEach(function(o){o.removeAttribute('aria-sort');}); th.setAttribute('aria-sort',dir);
        var numeric=th.classList.contains('num');
        trs.sort(function(a,b){
          var ca=a.cells[i], cb=b.cells[i]; if(!ca||!cb) return 0;
          var va=ca.dataset.sort!==undefined?ca.dataset.sort:ca.textContent, vb=cb.dataset.sort!==undefined?cb.dataset.sort:cb.textContent;
          if(numeric){ va=parseFloat(String(va).replace(/[^0-9.+-]/g,'')); vb=parseFloat(String(vb).replace(/[^0-9.+-]/g,'')); va=isNaN(va)?-Infinity:va; vb=isNaN(vb)?-Infinity:vb; return dir==='ascending'?va-vb:vb-va; }
          return dir==='ascending'?String(va).localeCompare(String(vb)):String(vb).localeCompare(String(va));
        });
        Array.prototype.slice.call(body.querySelectorAll('tr.group')).forEach(function(g){g.remove();});
        trs.forEach(function(r){body.appendChild(r);});
      });
    });
  }
  sortable(document.getElementById('mon')); sortable(document.getElementById('qual'));

  // ---------- boot: local first, then the page database if this viewer has one
  loadLocal(); renderWatch();
  setNote('Watchlist saved in this browser. Signed-in viewers on claude.ai keep theirs across devices.', false);
  Promise.all([use('user'), use('db')]).then(function(res){
    var user=res[0], db=res[1];
    if(!user||!db) return;
    return user.id().then(function(id){
      if(!id) return;
      ref=db.doc('data/users/'+id+'/watchlist');
      var localCopy=watch, first=true;
      ref.onSnapshot(function(snap){
        var d=snap.exists?snap.data():null;
        if(first){
          first=false; mode='cloud';
          setNote('Your watchlist is private to you and follows you across devices.', false);
          if(!d && Object.keys(localCopy).length){ watch=localCopy; renderWatch(); persist(); return; }
        }
        watch=(d&&d.tickers)||{}; renderWatch();
      }, function(err){ mode='local'; setNote('Watchlist saved in this browser only ('+(err&&err.code||'unavailable')+').', true); });
    });
  }).catch(function(){});
})();
</script>"""


def build(q, m, meta, prev_qualifying=None, standalone=True):
    """q: qualifying DataFrame, m: monitoring DataFrame, meta: dict(asof, run, comparison),
    prev_qualifying: set of tickers that qualified on the previous run (None if unknown)."""
    n_q = 0 if q is None else len(q)
    n_m = 0 if m is None else len(m)
    cur = set(q["ticker"].astype(str)) if q is not None and not q.empty and "ticker" in q else set()
    new_set = (cur - prev_qualifying) if prev_qualifying is not None else set()
    dropped = sorted(prev_qualifying - cur) if prev_qualifying is not None else []
    below = {w: int(sum(1 for v in (m[f"below{w}"] if m is not None and f"below{w}" in m else []) if _bool(v))) for w in WINDOWS}
    groups = sorted(set(reason_group(r) for r in (m["reason"] if m is not None and "reason" in m else [])))
    group_opts = "".join(f'<option value="{esc(g)}">{esc(g)}</option>' for g in groups)
    sectors = {} if not cur or "sector" not in q else q.groupby("sector").size().sort_values(ascending=False).to_dict()
    sector_html = "".join(f"<li><span>{esc(s)}</span><b>{n}</b></li>" for s, n in sectors.items())
    sma_heads = "".join(f'<th class="num" title="Consecutive sessions below the {w}-day SMA">{w}d</th>' for w in WINDOWS)
    payload = json.dumps({"asof": meta.get("asof"), "tickers": data_map(q, m)}, separators=(",", ":")).replace("</", "<\\/")

    if prev_qualifying is None:
        changes = '<div class="changes"><span>First archived run, so no comparison with a previous close.</span></div>'
    else:
        changes = (f'<div class="changes"><span>Since {esc(meta.get("prev_asof", "previous run"))}: '
                   f'<b>{len(new_set)}</b> new qualifier{"s" if len(new_set) != 1 else ""}'
                   f'{" (" + ", ".join(sorted(new_set)) + ")" if new_set else ""}</span>'
                   f'<span><b>{len(dropped)}</b> dropped out{" (" + ", ".join(dropped) + ")" if dropped else ""}</span></div>')

    body = f"""
<header>
  <h1>US Stock Screen</h1>
  <div class="meta">
    <span>As of close <b>{esc(meta.get('asof'))}</b></span>
    <span>Run <b>{esc(meta.get('run'))}</b></span>
    <span>Universe <b>S&amp;P 500 + S&amp;P 400</b></span>
    <span>Comparison <b>{esc(str(meta.get('comparison', 'qoq')).upper())}</b></span>
  </div>
  <div class="rules">
    <span>Net income growth &ge; 10% vs prior quarter</span>
    <span>Close within &plusmn;2% of 200-day SMA</span>
    <span>Consensus EPS next quarter &ge; 10% above last</span>
    <span>Market cap &ge; $1bn</span>
  </div>
</header>

<section class="tiles">
  <div class="tile accent"><div class="k">Qualifying</div><div class="v">{n_q}<small>of {n_q + n_m}</small></div></div>
  <div class="tile"><div class="k">New this run</div><div class="v">{len(new_set) if prev_qualifying is not None else "&ndash;"}</div></div>
  <div class="tile"><div class="k">Below 20-day SMA</div><div class="v">{below[20]}<small>{below[20] / max(n_m, 1):.0%}</small></div></div>
  <div class="tile"><div class="k">Below 50-day SMA</div><div class="v">{below[50]}<small>{below[50] / max(n_m, 1):.0%}</small></div></div>
  <div class="tile"><div class="k">Below 200-day SMA</div><div class="v">{below[200]}<small>{below[200] / max(n_m, 1):.0%}</small></div></div>
</section>
{changes}

<h2>My watchlist <span class="n" id="watch-count">0 watched</span></h2>
<p class="note" id="watch-note"></p>
<div class="wrap"><table id="watch">
<thead><tr><th>Ticker</th><th>Status today</th><th class="num">vs SMA200</th><th class="num">YTD high &middot; date</th><th class="num">Off high</th>{sma_heads}<th>Added</th><th></th></tr></thead>
<tbody id="watch-body"></tbody></table></div>

<h2>Qualifying shares <span class="n">{n_q} &middot; grouped by sector and industry</span></h2>
<ul class="sectors">{sector_html}</ul>
<div class="wrap" style="margin-top:10px"><table id="qual">
<thead><tr>
  <th class="star-cell"></th><th>Ticker</th><th class="num">Close</th><th class="num">SMA200 &middot; dist</th><th>Slope</th>
  <th class="num">YTD high &middot; date</th><th class="num">Off high</th>
  <th class="num">Net income $m &middot; prev</th><th class="num">Growth</th>
  <th class="num">EPS &middot; est next</th><th class="num">Exp growth</th><th class="num">Analysts &middot; rev</th>
  <th>Q end</th><th class="num">Mkt cap $bn</th>{sma_heads}
</tr></thead>
<tbody>
{qualifying_rows(q, new_set)}
</tbody></table></div>
<div class="legend"><span>Last four columns: consecutive sessions closing below each moving average.</span>
<span><i class="w"></i>1 to 19 sessions</span><span><i class="h"></i>20 or more</span></div>

<h2>Monitoring list <span class="n">{n_m} excluded shares &middot; watch for names moving toward qualification</span></h2>
<div class="controls">
  <input id="q-filter" type="search" placeholder="Filter by ticker" aria-label="Filter by ticker">
  <select id="g-filter" aria-label="Filter by exclusion reason"><option value="">All reasons</option>{group_opts}</select>
  <label><input type="checkbox" id="w-filter"> Watched only</label>
  <span class="shown" id="shown"></span>
</div>
<div class="wrap"><table id="mon">
<thead><tr>
  <th class="star-cell"></th><th>Ticker</th><th>Why excluded</th><th class="num">vs SMA200</th>
  <th class="num">YTD high &middot; date</th><th class="num">Off high</th>{sma_heads}
</tr></thead>
<tbody>
{monitoring_rows(m)}
</tbody></table></div>

<p class="foot">Source: Yahoo Finance via yfinance. Industry labels are Yahoo's. Reported EPS is GAAP while consensus is
usually on an adjusted basis, so expected growth can be overstated where a company has large non-GAAP add-backs.
Intraday highs occasionally contain bad prints. This is a screen of a price and earnings pattern, not a recommendation.
Rules: US_Stock_Screen_Rules.md, version 1.6.</p>

<script id="screen-data" type="application/json">{payload}</script>
{SCRIPT}"""

    fonts = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600'
             '&family=IBM+Plex+Mono:wght@400;500;600&display=swap">')
    title = "<title>US Stock Screen</title>"
    if standalone:
        return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f"{title}{fonts}{STYLE}</head><body>{body}</body></html>")
    return f"{title}\n{fonts}\n{STYLE}\n{body}"


# ----------------------------------------------------------------------------- files

def previous_qualifying(archive_dir, asof):
    """Tickers that qualified in the most recent archived close before `asof`, or (None, None)."""
    days = sorted(d for d in glob.glob(os.path.join(archive_dir, "????-??-??")) if os.path.basename(d) < asof)
    if not days:
        return None, None
    prev = days[-1]
    path = os.path.join(prev, "qualifying.csv")
    if not os.path.exists(path):
        return None, None
    df = pd.read_csv(path)
    return (set(df["ticker"].astype(str)) if "ticker" in df else set()), os.path.basename(prev)


def write_pages(day_dir, q, m, meta, archive_dir=None):
    """Write report.html and artifact.html into day_dir; returns their paths."""
    prev, prev_asof = previous_qualifying(archive_dir, meta["asof"]) if archive_dir else (None, None)
    meta = dict(meta, prev_asof=prev_asof)
    paths = []
    for name, standalone in (("report.html", True), ("artifact.html", False)):
        p = os.path.join(day_dir, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(build(q, m, meta, prev, standalone))
        paths.append(p)
    return paths


def build_from_folder(folder):
    q = pd.read_csv(os.path.join(folder, "qualifying.csv"))
    m = pd.read_csv(os.path.join(folder, "monitoring.csv"))
    meta = {"asof": os.path.basename(os.path.normpath(folder)), "run": "", "comparison": "qoq"}
    rep = os.path.join(folder, "report.md")
    if os.path.exists(rep):
        with open(rep, encoding="utf-8") as fh:
            head = fh.read(600)
        for key, pat in (("asof", r"As of close: (\S+)"), ("run", r"Run: (\S+)"), ("comparison", r"Comparison: (\S+)")):
            mm = re.search(pat, head)
            if mm:
                meta[key] = mm.group(1)
    return write_pages(folder, q, m, meta, archive_dir=os.path.dirname(os.path.normpath(folder)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="an archive day folder, e.g. archive/2026-09-29")
    a = ap.parse_args()
    for p in build_from_folder(a.folder):
        print(f"wrote {p} ({os.path.getsize(p) // 1024} KB)")
