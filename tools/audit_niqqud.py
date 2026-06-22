# -*- coding: utf-8 -*-
"""
audit_niqqud.py — OFFLINE niqqud audit via Dicta Nakdan (NOT shipped, NOT a build gate).

WHAT THIS IS: a suspect-finder, not a certifier. It places every lexicon form in a
grammatical, correct-ROLE context sentence (so Nakdan can disambiguate by part-of-speech),
strips the niqqud, asks Dicta Nakdan to re-vocalize, and compares Nakdan's reading to our
stored niqqud. Empirically, context roughly DOUBLES agreement vs auditing isolated words
(52-69% -> 88-100%) and collapses most homograph false positives — but it still cannot
prove niqqud is CORRECT: our lexicon is LLM-generated and Nakdan is an LLM-grade
diacritizer, so a systematic convention error we BOTH make passes silently. Correcting
niqqud stays a human/SLP decision.

OUTPUT: tools/niqqud_review.html — an interactive review page. For each flagged form you pick
what's correct (ours / Nakdan / another option / a custom spelling / skip), then download a
decisions JSON and feed it to tools/apply_niqqud_fixes.py, which writes the corrections into
the source files and rebuilds.

KNOWN RESIDUAL FALSE POSITIVES (flagged, not errors): same-POS sense ambiguity, ktiv
haser/male skeleton divergence (~7% of forms — marked "ktiv?"), ultra-rare senses deep in
Nakdan's option list, and loanwords with no canonical niqqud.

Run:  python3 tools/audit_niqqud.py [--sample N] [--out tools/niqqud_review.html]
Network is used at build time only; raw API responses are cached in tools/.niqqud_cache.json.
Forms in tools/niqqud_accepted.json (confirmed correct by review) are no longer flagged.
"""

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
LEX = json.load(open(os.path.join(ROOT, "lexicon.json"), encoding="utf-8"))

API = "https://nakdan-2-0.loadbalancer.dicta.org.il/api"
CACHE_PATH = os.path.join(HERE, ".niqqud_cache.json")
ACCEPTED_PATH = os.path.join(HERE, "niqqud_accepted.json")
GN_OF = {"ms": ("m", "sg"), "fs": ("f", "sg"), "mp": ("m", "pl"), "fp": ("f", "pl")}
KEEP_PTS = set(range(0x05B0, 0x05BD)) | {0x05C1, 0x05C2, 0x05C7}   # niqqud points (+ dagesh), shin/sin dots, qamats-qatan
BEGADKEFET = set("בכפגדת")


# ---------------- niqqud helpers ----------------
def strip_niqqud(s):
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def canon(s):
    """NFC; drop cantillation/meteg (keep niqqud); drop the unstable word-initial dagesh-lene."""
    s = unicodedata.normalize("NFC", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn" or ord(c) in KEEP_PTS)
    cs = list(s)
    if cs and cs[0] in BEGADKEFET:        # only begadkefet take a context-dependent word-initial dagesh-lene
        for i in range(1, len(cs)):
            if 0x05D0 <= ord(cs[i]) <= 0x05EA:
                break
            if cs[i] == "ּ":             # U+05BC; shared with shuruk, so only safe to drop on a begadkefet base
                cs[i] = ""
    return "".join(cs)


def opt_voc(opt):
    """An option is the vocalized string (addmorph off) or [vocalized, [morph...]] (addmorph on)."""
    return opt[0] if isinstance(opt, list) else opt


def ktiv_haser(our):
    """Advisory flag: holam not sitting on a vav, or a qubuts — both signal defective (haser)
    spelling, where stripping our own form yields a more ambiguous skeleton => extra FP risk."""
    if "ֻ" in our:                       # qubuts (vs shuruk וּ)
        return True
    cs = list(our)
    for i, c in enumerate(cs):
        if c == "ֹ":                     # holam
            j = i - 1
            while j >= 0 and unicodedata.category(cs[j]) == "Mn":
                j -= 1
            if j >= 0 and cs[j] != "ו":
                return True
    return False


# ---------------- covering generation (every form once, in its correct role) ----------------
def build_targets():
    noun_by_gn, adj_by_gn, verb_by_gn = {}, {}, {}
    for e in LEX["nouns"]:
        noun_by_gn.setdefault((e["g"], e["n"]), []).append(e["w"])
    for e in LEX["adjectives"]:
        for k, gn in GN_OF.items():
            adj_by_gn.setdefault(gn, []).append(e["forms"][k]["w"])
    for e in LEX["verbs"]:
        for k, gn in GN_OF.items():
            verb_by_gn.setdefault(gn, []).append(e["forms"][k]["w"])

    def host(pool, gn, avoid=None):
        for w in pool.get(gn, []):
            if w != avoid:
                return w
        return None

    nouns, adjs, verbs = [], [], []
    for e in LEX["nouns"]:                                  # noun audited as subject + agreeing context
        gn, w = (e["g"], e["n"]), e["w"]
        sent = [w]
        a = host(adj_by_gn, gn, w)
        if a:
            sent.append(a)
        v = host(verb_by_gn, gn, w)
        if v:
            sent.append(v)
        nouns.append({"sent": sent, "ti": 0, "our": w, "cat": "noun", "role": f"subject {gn[0]}-{gn[1]}"})
    for e in LEX["adjectives"]:                             # [host-noun, ADJ, host-verb]
        for k, gn in GN_OF.items():
            w = e["forms"][k]["w"]
            sent, hn = [], host(noun_by_gn, gn, w)
            if hn:
                sent.append(hn)
            ti = len(sent)
            sent.append(w)
            hv = host(verb_by_gn, gn, w)
            if hv:
                sent.append(hv)
            adjs.append({"sent": sent, "ti": ti, "our": w, "cat": "adjective", "role": k})
    for e in LEX["verbs"]:                                  # [host-noun, VERB]
        for k, gn in GN_OF.items():
            w = e["forms"][k]["w"]
            sent, hn = [], host(noun_by_gn, gn, w)
            if hn:
                sent.append(hn)
            ti = len(sent)
            sent.append(w)
            verbs.append({"sent": sent, "ti": ti, "our": w, "cat": "verb", "role": k})
    return nouns, adjs, verbs


# ---------------- Nakdan client (cached, batched) ----------------
_cache = {}
if os.path.exists(CACHE_PATH):
    try:
        _cache = json.load(open(CACHE_PATH, encoding="utf-8"))
    except Exception:
        _cache = {}

ACCEPTED = set()
if os.path.exists(ACCEPTED_PATH):
    try:
        ACCEPTED = set(json.load(open(ACCEPTED_PATH, encoding="utf-8")))
    except Exception:
        ACCEPTED = set()


def save_cache():
    tmp = CACHE_PATH + ".tmp"
    json.dump(_cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, CACHE_PATH)            # atomic; a crash never truncates the cache


def nakdan(text):
    if text in _cache:
        return _cache[text]
    payload = json.dumps({"task": "nakdan", "data": text, "genre": "modern", "addmorph": False}).encode("utf-8")
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(API, data=payload, headers={"Content-Type": "application/json"})
            toks = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
            _cache[text] = toks
            return toks
        except Exception as e:            # 503s under load are common; back off and retry
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Nakdan API failed after retries: {last!r}")


def audit_batch(batch):
    """Return one verdict dict per target, or None if token alignment can't be trusted."""
    flat, tpos = [], []
    for t in batch:
        words = [strip_niqqud(x) for x in t["sent"]]
        tpos.append(len(flat) + t["ti"])
        flat.extend(words)
    toks = [tk for tk in nakdan(" . ".join(" ".join(strip_niqqud(x) for x in t["sent"]) for t in batch)) if not tk.get("sep")]
    if len(toks) != len(flat) or any(strip_niqqud(toks[i]["word"]) != flat[i] for i in range(len(flat))):
        return None                       # tokenization drifted -> caller falls back to singles
    out = []
    for t, p in zip(batch, tpos):
        raw = toks[p]["options"]
        sane = [o for o in raw if "|" not in opt_voc(o)] or raw   # prefer un-segmented readings (no clitic split phantoms)
        disp, seen = [], set()
        for o in sane:                                            # de-duplicate, keep order
            v = opt_voc(o).replace("|", "")
            if v not in seen:
                seen.add(v)
                disp.append(v)
        cmp = [canon(c) for c in disp]
        ours = canon(t["our"])
        tier = "ok" if (cmp and ours == cmp[0]) else ("in_options" if ours in cmp else "not_in_options")
        if t["our"] in ACCEPTED:           # reviewer already confirmed ours is correct
            tier = "ok"
        out.append({**t, "tier": tier, "top1": disp[0] if disp else "",
                    "cands": disp[:8], "ktiv": ktiv_haser(t["our"])})
    return out


def audit(targets, batch_sentences=110, batch_chars=3000):
    results, batch, chars = [], [], 0

    def flush():
        nonlocal batch, chars
        if not batch:
            return
        r = audit_batch(batch)
        if r is None:                     # realign: re-run each sentence on its own
            r = []
            for t in batch:
                s = audit_batch([t])
                r.append(s[0] if s else {**t, "tier": "skip", "top1": "", "cands": [], "ktiv": ktiv_haser(t["our"])})
        results.extend(r)
        save_cache()                      # persist incrementally so a later failure can't discard the run
        batch, chars = [], 0

    for t in targets:
        c = sum(len(x) for x in t["sent"]) + len(t["sent"])
        if batch and (len(batch) >= batch_sentences or chars + c > batch_chars):
            flush()
        batch.append(t)
        chars += c
        if len(results) and len(results) % 300 == 0:
            print(f"  ...audited {len(results)}/{len(targets)}", file=sys.stderr)
    flush()
    return results


# ---------------- HTML review app ----------------
HTML_TEMPLATE = r"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>בדיקת ניקוד — צלילון</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@500;700&family=Heebo:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#FBFAF6; --panel:#FFFFFF; --ink:#21242B; --muted:#74766F;
    --line:#E9E5DB; --accent:#3A3DCC; --accent-soft:#ECECFB;
    --redline:#D6204A; --strong:#C2410C; --review:#B5860B;
    --serif:"Frank Ruhl Libre","Times New Roman","David",serif;
    --sans:"Heebo",system-ui,-apple-system,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}
  header{position:sticky;top:0;z-index:5;background:rgba(251,250,246,.93);backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line);padding:14px 18px}
  .wrap{max-width:760px;margin:0 auto}
  .h-top{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
  h1{font-family:var(--serif);font-weight:700;font-size:24px;margin:0;letter-spacing:.01em}
  .dl{font-family:var(--sans);font-weight:700;font-size:14px;color:#fff;background:var(--accent);
    border:none;border-radius:10px;padding:9px 16px;cursor:pointer}
  .dl:active{transform:scale(.97)}
  .progress{height:6px;background:#EEEBE2;border-radius:99px;margin:12px 0 6px;overflow:hidden}
  .progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),#6E70E0);transition:width .3s}
  .progtxt{font-size:12.5px;color:var(--muted)}
  .chips{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
  .chip{font-family:var(--sans);font-size:13px;font-weight:500;color:var(--ink);background:#fff;
    border:1px solid var(--line);border-radius:99px;padding:6px 13px;cursor:pointer}
  .chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
  .note{font-size:12px;color:var(--muted);margin:10px 0 0}
  .note code{font-family:ui-monospace,Menlo,monospace;background:#F1EEE6;padding:1px 6px;border-radius:5px;direction:ltr;display:inline-block}

  main{max-width:760px;margin:0 auto;padding:18px 16px 140px}
  .empty{text-align:center;color:var(--muted);font-size:18px;margin-top:60px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;
    margin-bottom:14px;position:relative;overflow:hidden}
  .card::before{content:"";position:absolute;inset-inline-start:0;top:0;bottom:0;width:5px;background:var(--review)}
  .card.strong::before{background:var(--strong)}
  .card.done{opacity:.58}
  .meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-bottom:14px}
  .badge{font-weight:700;font-size:11px;border-radius:99px;padding:3px 9px}
  .b-strong{background:#FCE9DF;color:var(--strong)}
  .b-review{background:#FAF1D6;color:#8A6608}
  .b-ktiv{background:#EDEBF9;color:var(--accent)}
  .ctx{font-family:var(--serif);font-size:15px;color:#8c8e86}
  .pair{display:flex;gap:12px}
  .opt{flex:1;border:1.5px solid var(--line);border-radius:13px;padding:12px 10px 14px;text-align:center;
    cursor:pointer;background:#fff;transition:border-color .12s,background .12s}
  .opt:hover{border-color:#cfcabe}
  .opt .lab{font-family:var(--sans);font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--muted);margin-bottom:4px}
  .opt .voc{font-family:var(--serif);font-size:40px;line-height:1.65;direction:rtl;min-height:46px}
  .opt.sel{border-color:var(--accent);background:var(--accent-soft);box-shadow:inset 0 0 0 1px var(--accent)}
  .diff{color:var(--redline);text-decoration:underline;text-decoration-color:var(--redline);
    text-decoration-thickness:2px;text-underline-offset:4px}
  .cands{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:12px}
  .cands .lab{font-size:11.5px;color:var(--muted)}
  .cand{font-family:var(--serif);font-size:22px;background:#fff;border:1px solid var(--line);
    border-radius:9px;padding:3px 12px;cursor:pointer;direction:rtl}
  .cand:hover{border-color:var(--accent)}
  .cand.sel{border-color:var(--accent);background:var(--accent-soft)}
  .actions{display:flex;align-items:center;gap:8px;margin-top:14px;flex-wrap:wrap}
  .act{font-family:var(--sans);font-size:13px;font-weight:500;background:#fff;border:1px solid var(--line);
    border-radius:9px;padding:7px 13px;cursor:pointer;color:var(--ink)}
  .act.sel{background:var(--ink);color:#fff;border-color:var(--ink)}
  .chosen{font-size:13px;color:var(--accent);margin-inline-start:auto}
  .chosen b{font-family:var(--serif);font-size:18px}
  .other-wrap{display:flex;gap:8px;margin-top:10px}
  .other{font-family:var(--serif);font-size:24px;direction:rtl;flex:1;border:1.5px solid var(--accent);
    border-radius:9px;padding:6px 12px}
  .save-other{font-family:var(--sans);font-weight:700;font-size:13px;background:var(--accent);color:#fff;
    border:none;border-radius:9px;padding:0 16px;cursor:pointer}
  [hidden]{display:none!important}
</style>
</head>
<body>
<header><div class="wrap">
  <div class="h-top">
    <h1>בְּדִיקַת נִקּוּד</h1>
    <button id="dl" class="dl">⬇ הורדת הכרעות</button>
  </div>
  <div class="progress"><i id="prog"></i></div>
  <div class="progtxt" id="progtxt"></div>
  <div class="chips">
    <button class="chip on" data-f="strong">חשד חזק (<span id="n-strong"></span>)</button>
    <button class="chip" data-f="all">הכול (<span id="n-all"></span>)</button>
    <button class="chip" data-f="undecided">לא הוכרעו</button>
  </div>
  <p class="note">בכל כרטיס בחרו מה נכון — לחיצה על ‹שלנו›, ‹נקדן›, אפשרות אחרת, או ‹אחר…›. ההכרעות נשמרות בדפדפן.
  בסיום: הורדה, ואז <code>python3 tools/apply_niqqud_fixes.py &lt;file&gt;</code>. הניקוד האדום מסמן את ההבדל. אין כאן אימות — רק מיון לבדיקה אנושית.</p>
</div></header>

<main id="cards" class="wrap"></main>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  var D = JSON.parse(document.getElementById('data').textContent);
  var cases = D.cases;
  var byId = {}; cases.forEach(function(c){ byId[c.id] = c; });
  var LS = 'tslilon.niqqud.decisions.v2';
  var dec = {};
  try { dec = JSON.parse(localStorage.getItem(LS) || '{}'); } catch(e){ dec = {}; }
  Object.keys(dec).forEach(function(k){ if(!byId[k]) delete dec[k]; });   // drop stale decisions from older audits
  localStorage.setItem(LS, JSON.stringify(dec));

  var HEBL = /[א-ת]/;
  function clusters(w){ var o=[],i,ch; w=w||''; for(i=0;i<w.length;i++){ ch=w[i];
    if(HEBL.test(ch)) o.push({b:ch,m:''}); else if(o.length) o[o.length-1].m+=ch; else o.push({b:'',m:ch}); } return o; }
  function esc(s){ return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];}); }
  // diff a against b, aligning base letters by LCS so ktiv male/haser only underlines the inserted/removed mater
  function diffHTML(a,b){
    if(!a) return '—';
    var ca=clusters(a), cb=clusters(b), n=ca.length, m=cb.length, i, j;
    var dp=[]; for(i=0;i<=n;i++){ dp.push([]); for(j=0;j<=m;j++) dp[i][j]=0; }
    for(i=1;i<=n;i++) for(j=1;j<=m;j++)
      dp[i][j] = ca[i-1].b===cb[j-1].b ? dp[i-1][j-1]+1 : (dp[i-1][j]>=dp[i][j-1]?dp[i-1][j]:dp[i][j-1]);
    var matchB=[]; for(i=0;i<n;i++) matchB.push(-1);
    i=n; j=m;
    while(i>0&&j>0){ if(ca[i-1].b===cb[j-1].b){ matchB[i-1]=j-1; i--; j--; }
      else if(dp[i-1][j]>=dp[i][j-1]) i--; else j--; }
    var h='', k;
    for(k=0;k<n;k++){ var seg=esc(ca[k].b+ca[k].m), bj=matchB[k];
      var same = bj>=0 && cb[bj].m===ca[k].m;          // matched base + identical niqqud
      h += same ? seg : '<span class="diff">'+seg+'</span>'; }
    return h || esc(a);
  }

  function setDec(id, v){
    var d = dec[id];
    if(d && d.verdict===v.verdict && d.value===v.value) delete dec[id];   // toggle off
    else dec[id] = v;
    localStorage.setItem(LS, JSON.stringify(dec));
    render();
  }

  function card(c){
    var d = dec[c.id] || {};
    var el = document.createElement('div');
    el.className = 'card' + (c.tier==='not_in_options'?' strong':'') + (d.verdict?' done':'');
    var others = (c.cands||[]).filter(function(x){ return x!==c.top1 && x!==c.our; }).slice(0,4);
    var chips = others.map(function(x){
      return '<button class="cand'+(d.verdict==='other'&&d.value===x?' sel':'')+'" data-v="'+esc(x)+'">'+diffHTML(x,c.our)+'</button>'; }).join('');
    var chosenTxt = d.verdict==='ours' ? esc(c.our) : d.verdict==='nakdan' ? esc(c.top1)
                  : d.verdict==='skip' ? 'דילוג' : d.verdict==='other' ? esc(d.value||'') : '';
    el.innerHTML =
      '<div class="meta">'
      + '<span class="badge '+(c.tier==='not_in_options'?'b-strong':'b-review')+'">'+(c.tier==='not_in_options'?'חשד חזק':'לבדיקה')+'</span>'
      + '<span>'+esc(c.cat)+' · '+esc(c.role)+'</span>'
      + (c.ktiv?'<span class="badge b-ktiv">כתיב חסר?</span>':'')
      + '<span class="ctx">‹ '+esc(c.ctx)+' ›</span>'
      + '</div>'
      + '<div class="pair">'
      + '<div class="opt'+(d.verdict==='ours'?' sel':'')+'" data-pick="ours"><div class="lab">שֶׁלָּנוּ</div><div class="voc">'+diffHTML(c.our,c.top1)+'</div></div>'
      + '<div class="opt'+(d.verdict==='nakdan'?' sel':'')+'" data-pick="nakdan"><div class="lab">נַקְדָּן</div><div class="voc">'+diffHTML(c.top1,c.our)+'</div></div>'
      + '</div>'
      + (chips?'<div class="cands"><span class="lab">אפשרויות נוספות:</span>'+chips+'</div>':'')
      + '<div class="actions">'
      + '<button class="act" data-act="other">אחר…</button>'
      + '<button class="act'+(d.verdict==='skip'?' sel':'')+'" data-act="skip">דלג</button>'
      + (d.verdict?'<span class="chosen">נבחר: <b>'+chosenTxt+'</b></span>':'')
      + '</div>'
      + '<div class="other-wrap" hidden><input class="other" value="'+esc(c.our)+'"><button class="save-other">שמירה</button></div>';

    el.querySelector('[data-pick="ours"]').onclick = function(){ setDec(c.id,{verdict:'ours',value:null}); };
    el.querySelector('[data-pick="nakdan"]').onclick = function(){ if(c.top1) setDec(c.id,{verdict:'nakdan',value:c.top1}); };
    Array.prototype.forEach.call(el.querySelectorAll('.cand'), function(b){
      b.onclick = function(){ setDec(c.id,{verdict:'other',value:b.dataset.v}); }; });
    el.querySelector('[data-act="skip"]').onclick = function(){ setDec(c.id,{verdict:'skip',value:null}); };
    var ow = el.querySelector('.other-wrap');
    el.querySelector('[data-act="other"]').onclick = function(){ ow.hidden = !ow.hidden; if(!ow.hidden) ow.querySelector('.other').focus(); };
    el.querySelector('.save-other').onclick = function(){ var v=el.querySelector('.other').value.trim(); if(v) setDec(c.id,{verdict:'other',value:v}); };
    return el;
  }

  function counts(){ var f=0,a=0,s=0,k; for(k in dec){ var v=dec[k].verdict;
    if(v==='ours') a++; else if(v==='skip') s++; else if(v==='nakdan'||v==='other') f++; }
    return {fix:f, acc:a, skip:s, decided:f+a+s}; }

  function render(){
    var f = document.querySelector('.chip.on').dataset.f, main=document.getElementById('cards'), shown=0, i;
    main.innerHTML='';
    for(i=0;i<cases.length;i++){ var c=cases[i];
      if(f==='strong' && c.tier!=='not_in_options') continue;
      if(f==='undecided' && dec[c.id] && dec[c.id].verdict) continue;
      main.appendChild(card(c)); shown++; }
    if(!shown) main.innerHTML='<p class="empty">אֵין מִקְרִים כָּאן 🎉</p>';
    var c2=counts(), tot=cases.length;
    document.getElementById('prog').style.width=(tot?100*c2.decided/tot:0)+'%';
    document.getElementById('progtxt').textContent=c2.decided+'/'+tot+' הוכרעו · '+c2.fix+' תיקונים · '+c2.acc+' אושרו · '+c2.skip+' דילוגים';
  }

  function download(){
    var fixes=[], accepted=[], id;
    for(id in dec){ var v=dec[id], c=byId[id]; if(!c) continue;
      if(v.verdict==='ours') accepted.push(c.our);
      else if((v.verdict==='nakdan'||v.verdict==='other') && v.value && v.value!==c.our)
        fixes.push({old:c.our, new:v.value, cat:c.cat, role:c.role}); }
    var payload={fixes:fixes, accepted:accepted, reviewed:Object.keys(dec).length, generated:new Date().toISOString()};
    var blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});
    var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='niqqud_decisions.json';
    document.body.appendChild(a); a.click(); a.remove();
  }

  Array.prototype.forEach.call(document.querySelectorAll('.chip'), function(ch){
    ch.onclick=function(){ Array.prototype.forEach.call(document.querySelectorAll('.chip'), function(c){c.classList.remove('on');}); ch.classList.add('on'); render(); }; });
  document.getElementById('dl').onclick=download;
  document.getElementById('n-strong').textContent=D.stats.strong;
  document.getElementById('n-all').textContent=cases.length;
  render();
})();
</script>
</body>
</html>
"""


def write_html(results, path):
    by = {"not_in_options": [], "in_options": [], "ok": [], "skip": []}
    for r in results:
        by[r["tier"]].append(r)
    cases = []
    for r in by["not_in_options"] + by["in_options"]:    # strong first
        cases.append({"id": f"{r['cat']}|{r['role']}|{r['our']}", "our": r["our"], "top1": r["top1"],
                      "cands": r.get("cands", []), "cat": r["cat"], "role": r["role"],
                      "tier": r["tier"], "ktiv": r["ktiv"],
                      "ctx": " ".join(strip_niqqud(x) for x in r["sent"])})
    n, agree = len(results), len(by["ok"])
    data = json.dumps({"cases": cases,
                       "stats": {"total": n, "agree": agree,
                                 "strong": len(by["not_in_options"]), "review": len(by["in_options"])}},
                      ensure_ascii=False).replace("<", "\\u003c")
    open(path, "w", encoding="utf-8").write(HTML_TEMPLATE.replace("__DATA__", data))
    return n, agree, by


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="audit only ~N forms (spread across categories) for a quick check")
    ap.add_argument("--out", default=os.path.join(HERE, "niqqud_review.html"))
    args = ap.parse_args()

    nouns, adjs, verbs = build_targets()
    if args.sample:
        s = max(1, args.sample // 3)
        targets = nouns[:s] + adjs[:s] + verbs[:s]
    else:
        targets = nouns + adjs + verbs

    print(f"auditing {len(targets)} forms via Nakdan (context sentences)...", file=sys.stderr)
    try:
        results = audit(targets)
    finally:
        save_cache()                      # never lose collected API responses
    n, agree, by = write_html(results, args.out)

    print("=" * 60)
    print(f"NIQQUD AUDIT  {n} forms · {agree} agree ({100*agree//n if n else 0}%) · "
          f"{len(by['not_in_options'])} strong · {len(by['in_options'])} review · {len(by['skip'])} skipped")
    print(f"review page -> {args.out}")
    print("  open it in a browser, choose per case, Download, then:")
    print("  python3 tools/apply_niqqud_fixes.py <downloaded decisions.json>")


if __name__ == "__main__":
    main()
