# -*- coding: utf-8 -*-
"""audit_gender.py — OFFLINE noun-gender audit against Hebrew Wiktionary (NOT shipped, NOT a gate).

Cross-checks each noun's stored gender (m/f) against he.wiktionary.org's grammatical-analysis
template (מין). Wiktionary is community-curated but INDEPENDENT of our LLM-generated data, so a
disagreement is a high-signal suspect — this is the check that catches the נענע class (a noun
tagged masculine that is actually feminine). It does NOT certify; it builds a review page.

Scope & reliability (after a debugging pass):
  - SINGULAR nouns only. Plural->singular guessing collides with homographs (נמל "port" vs נמלה
    "ant") and is too noisy to trust; plurals are reported as skipped (their gender follows the
    singular lemma, which is checked when present).
  - Gender/POS labels are read in BOTH full and ABBREVIATED forms (נקבה/נ, זכר/ז, עצם/ע).
  - A page with senses of DIFFERENT gender (homograph, e.g. עיר city-f / foal-m) or a זו"נ both-
    gender label is reported AMBIGUOUS, never flagged.
Uses the legal MediaWiki API (content CC BY-SA 4.0), cached + rate-limited.

Run:  python3 tools/audit_gender.py
Writes tools/gender_review.html + tools/gender_disagreements.json (both gitignored).
Forms in tools/gender_accepted.json (reviewer confirmed ours) are no longer flagged.
"""
import glob
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
LEX = json.load(open(os.path.join(ROOT, "lexicon.json"), encoding="utf-8"))
API = "https://he.wiktionary.org/w/api.php"
UA = "letter-game-lexicon-audit/1.0 (offline research)"
CACHE = os.path.join(HERE, ".gender_cache.json")
ACCEPTED_PATH = os.path.join(HERE, "gender_accepted.json")
GENDER_HE = {"m": "זָכָר", "f": "נְקֵבָה"}


def sk(s):
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


GLOSS = {}
for p in glob.glob(os.path.join(HERE, "generated_lexicon*.json")):
    for e in json.load(open(p, encoding="utf-8")).get("nouns", []):
        GLOSS.setdefault(sk(e["w"]), e.get("gloss", ""))

cache = {}
if os.path.exists(CACHE):
    try:
        cache = json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
ACCEPTED = set()
if os.path.exists(ACCEPTED_PATH):
    try:
        ACCEPTED = set(json.load(open(ACCEPTED_PATH, encoding="utf-8")))
    except Exception:
        ACCEPTED = set()


def fetch(skels):
    todo = [s for s in skels if s and s not in cache]
    for i in range(0, len(todo), 50):
        chunk = todo[i:i + 50]
        q = urllib.parse.urlencode({"action": "query", "format": "json", "formatversion": "2", "maxlag": "5",
                                    "prop": "revisions", "rvprop": "content", "rvslots": "main", "titles": "|".join(chunk)})
        d = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(API + "?" + q, headers={"User-Agent": UA})
                d = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                time.sleep(int(e.headers.get("Retry-After") or 0) or (2 ** attempt) * 3)
            except Exception:
                time.sleep(3)
        if d is None:
            continue
        for pg in d.get("query", {}).get("pages", []):
            cache[pg["title"]] = None if pg.get("missing") else (pg["revisions"][0]["slots"]["main"]["content"] if pg.get("revisions") else "")
        time.sleep(1.2)


def _is_noun_pos(pos):
    pos = pos.replace("־", "-").strip()
    if "תואר" in pos:                              # adjective (שם תואר) — not a noun
        return False
    return pos == "ע" or pos == "שם" or "שם עצם" in pos or "שם-עצם" in pos


def _gender_of(v):
    v = v.replace('"', "").replace("'", "").strip()
    if "זונ" in v or ("זכר" in v and "נקבה" in v):  # זו"נ / "זכר ונקבה" -> both
        return "ambig"
    if "נקבה" in v or v.startswith("נ"):
        return "f"
    if "זכר" in v or v.startswith("ז"):
        return "m"
    return None


def wiki_gender(content):
    """Gender across NOUN senses: 'm' / 'f' / 'ambig' (mixed senses) / 'unknown'."""
    if not content:
        return "unknown"
    genders = set()
    for chunk in content.split("{{ניתוח דקדוקי")[1:]:
        head = chunk.split("}}")[0]
        pos = re.search(r"חלק דיבר\s*=\s*([^\n|}]*)", head)
        mim = re.search(r"מין\s*=\s*([^\n|}]*)", head)
        if not pos or not mim or not _is_noun_pos(pos.group(1)):
            continue
        r = _gender_of(mim.group(1))
        if r:
            genders.add(r)
    if not genders:
        return "unknown"
    if len(genders) > 1 or "ambig" in genders:
        return "ambig"
    return genders.pop()


def main():
    sing = [(sk(e["w"]), e["w"], e["g"]) for e in LEX["nouns"] if e["n"] == "sg"]
    n_plural = sum(1 for e in LEX["nouns"] if e["n"] != "sg")
    fetch(sorted({skel for skel, _, _ in sing}))
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)

    disagree, counts = [], {"agree": 0, "disagree": 0, "ambig": 0, "notfound": 0, "accepted": 0}
    for skel, w, g in sing:
        if w in ACCEPTED:
            counts["accepted"] += 1
            continue
        wg = wiki_gender(cache.get(skel))
        if wg in ("m", "f"):
            if wg == g:
                counts["agree"] += 1
            else:
                counts["disagree"] += 1
                disagree.append({"id": w, "w": w, "ours": g, "wiki": wg, "gloss": GLOSS.get(skel, "")})
        elif wg == "ambig":
            counts["ambig"] += 1
        else:
            counts["notfound"] += 1

    disagree.sort(key=lambda d: d["w"])
    json.dump(disagree, open(os.path.join(HERE, "gender_disagreements.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    write_html(disagree, counts)

    print("=" * 60)
    print(f"GENDER AUDIT  {len(sing)} singular nouns · agree {counts['agree']} · DISAGREE {counts['disagree']} · "
          f"ambiguous {counts['ambig']} · not-found {counts['notfound']} · accepted {counts['accepted']}  ({n_plural} plural skipped)")
    for d in disagree:
        print(f"  ⚠ {d['w']:12} ours={d['ours']}  wiktionary={d['wiki']}   {d['gloss']}")
    print("review page -> tools/gender_review.html")
    print("  choose per case, Download, then: python3 tools/apply_gender_fixes.py <decisions.json>")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>בדיקת מין (זכר/נקבה) — אותיות מדברות</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Frank+Ruhl+Libre:wght@500;700&family=Heebo:wght@400;500;700&display=swap" rel="stylesheet">
<style>
  :root{--paper:#FBFAF6;--panel:#FFFFFF;--ink:#21242B;--muted:#74766F;--line:#E9E5DB;
    --accent:#3A3DCC;--accent-soft:#ECECFB;--strong:#C2410C;
    --serif:"Frank Ruhl Libre","Times New Roman","David",serif;--sans:"Heebo",system-ui,sans-serif;}
  *{box-sizing:border-box} html,body{margin:0}
  body{background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}
  header{position:sticky;top:0;z-index:5;background:rgba(251,250,246,.93);backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:14px 18px}
  .wrap{max-width:720px;margin:0 auto}
  .h-top{display:flex;align-items:baseline;justify-content:space-between;gap:12px}
  h1{font-family:var(--serif);font-weight:700;font-size:24px;margin:0}
  .dl{font-family:var(--sans);font-weight:700;font-size:14px;color:#fff;background:var(--accent);border:none;border-radius:10px;padding:9px 16px;cursor:pointer}
  .dl:active{transform:scale(.97)}
  .progress{height:6px;background:#EEEBE2;border-radius:99px;margin:12px 0 6px;overflow:hidden}
  .progress i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--accent),#6E70E0);transition:width .3s}
  .progtxt{font-size:12.5px;color:var(--muted)}
  .note{font-size:12px;color:var(--muted);margin:10px 0 0}
  .note code{font-family:ui-monospace,Menlo,monospace;background:#F1EEE6;padding:1px 6px;border-radius:5px;direction:ltr;display:inline-block}
  main{max-width:720px;margin:0 auto;padding:18px 16px 140px}
  .empty{text-align:center;color:var(--muted);font-size:18px;margin-top:60px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin-bottom:14px;position:relative;overflow:hidden}
  .card::before{content:"";position:absolute;inset-inline-start:0;top:0;bottom:0;width:5px;background:var(--strong)}
  .card.done{opacity:.58}
  .top{display:flex;align-items:baseline;gap:12px;margin-bottom:14px;flex-wrap:wrap}
  .word{font-family:var(--serif);font-size:34px;direction:rtl}
  .gloss{color:var(--muted);font-size:14px}
  .pair{display:flex;gap:12px}
  .opt{flex:1;border:1.5px solid var(--line);border-radius:13px;padding:12px 10px;text-align:center;cursor:pointer;background:#fff;transition:border-color .12s,background .12s}
  .opt:hover{border-color:#cfcabe}
  .opt .lab{font-family:var(--sans);font-size:11px;font-weight:700;letter-spacing:.06em;color:var(--muted);margin-bottom:4px}
  .opt .g{font-family:var(--serif);font-size:26px}
  .opt.sel{border-color:var(--accent);background:var(--accent-soft);box-shadow:inset 0 0 0 1px var(--accent)}
  .actions{display:flex;align-items:center;gap:8px;margin-top:12px}
  .act{font-family:var(--sans);font-size:13px;font-weight:500;background:#fff;border:1px solid var(--line);border-radius:9px;padding:7px 13px;cursor:pointer;color:var(--ink)}
  .act.sel{background:var(--ink);color:#fff;border-color:var(--ink)}
  .chosen{font-size:13px;color:var(--accent);margin-inline-start:auto}
  [hidden]{display:none!important}
</style>
</head>
<body>
<header><div class="wrap">
  <div class="h-top"><h1>בְּדִיקַת מִין</h1><button id="dl" class="dl">⬇ הורדת הכרעות</button></div>
  <div class="progress"><i id="prog"></i></div>
  <div class="progtxt" id="progtxt"></div>
  <p class="note">לכל שם־עצם: מה המין הנכון — ‹שלנו› או ‹ויקימילון›? המקור הוא ויקימילון (עצמאי מהנתונים שלנו) ולכן חילוקי דעה הם חשד —
  אבל ויקימילון אינו תמיד צודק, אז זו בדיקה אנושית. ההכרעות נשמרות בדפדפן. בסיום: הורדה, ואז
  <code>python3 tools/apply_gender_fixes.py &lt;file&gt;</code>.</p>
</div></header>
<main id="cards" class="wrap"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  var D=JSON.parse(document.getElementById('data').textContent), cases=D.cases;
  var byId={}; cases.forEach(function(c){byId[c.id]=c;});
  var LS='talkingletters.gender.decisions.v1', dec={};
  try{dec=JSON.parse(localStorage.getItem(LS)||'{}');}catch(e){dec={};}
  Object.keys(dec).forEach(function(k){if(!byId[k])delete dec[k];});
  localStorage.setItem(LS,JSON.stringify(dec));
  var GLAB={m:'זָכָר',f:'נְקֵבָה'};
  function esc(s){return (s||'').replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function setDec(id,v){var d=dec[id];
    if(d&&d.verdict===v.verdict)delete dec[id]; else dec[id]=v;
    localStorage.setItem(LS,JSON.stringify(dec)); render();}
  function card(c){
    var d=dec[c.id]||{}, el=document.createElement('div');
    el.className='card'+(d.verdict?' done':'');
    el.innerHTML='<div class="top"><span class="word">'+esc(c.w)+'</span><span class="gloss">'+esc(c.gloss)+'</span></div>'
      +'<div class="pair">'
      +'<div class="opt'+(d.verdict==='ours'?' sel':'')+'" data-pick="ours"><div class="lab">שֶׁלָּנוּ</div><div class="g">'+GLAB[c.ours]+'</div></div>'
      +'<div class="opt'+(d.verdict==='wiki'?' sel':'')+'" data-pick="wiki"><div class="lab">וִיקִימִילוֹן</div><div class="g">'+GLAB[c.wiki]+'</div></div>'
      +'</div>'
      +'<div class="actions"><button class="act'+(d.verdict==='skip'?' sel':'')+'" data-act="skip">דלג</button>'
      +(d.verdict?'<span class="chosen">נבחר: '+(d.verdict==='skip'?'דילוג':d.verdict==='ours'?GLAB[c.ours]+' (שלנו)':GLAB[c.wiki]+' (ויקימילון)')+'</span>':'')
      +'</div>';
    el.querySelector('[data-pick="ours"]').onclick=function(){setDec(c.id,{verdict:'ours'});};
    el.querySelector('[data-pick="wiki"]').onclick=function(){setDec(c.id,{verdict:'wiki'});};
    el.querySelector('[data-act="skip"]').onclick=function(){setDec(c.id,{verdict:'skip'});};
    return el;
  }
  function render(){
    var main=document.getElementById('cards'); main.innerHTML='';
    if(!cases.length){main.innerHTML='<p class="empty">אֵין חִלּוּקֵי דֵּעוֹת 🎉</p>';}
    else cases.forEach(function(c){main.appendChild(card(c));});
    var dn=Object.keys(dec).length, tot=cases.length;
    document.getElementById('prog').style.width=(tot?100*dn/tot:0)+'%';
    document.getElementById('progtxt').textContent=dn+'/'+tot+' הוכרעו';
  }
  function download(){
    var fixes=[], accepted=[], id;
    for(id in dec){var v=dec[id], c=byId[id]; if(!c)continue;
      if(v.verdict==='wiki')fixes.push({w:c.w, old:c.ours, new:c.wiki});
      else if(v.verdict==='ours')accepted.push(c.w);}
    var blob=new Blob([JSON.stringify({fixes:fixes,accepted:accepted,generated:new Date().toISOString()},null,2)],{type:'application/json'});
    var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='gender_decisions.json';
    document.body.appendChild(a); a.click(); a.remove();
  }
  document.getElementById('dl').onclick=download;
  render();
})();
</script>
</body>
</html>
"""


def write_html(disagree, counts):
    cases = [{"id": d["id"], "w": d["w"], "ours": d["ours"], "wiki": d["wiki"], "gloss": d["gloss"]} for d in disagree]
    data = json.dumps({"cases": cases, "counts": counts}, ensure_ascii=False).replace("<", "\\u003c")
    open(os.path.join(HERE, "gender_review.html"), "w", encoding="utf-8").write(HTML_TEMPLATE.replace("__DATA__", data))


if __name__ == "__main__":
    main()
