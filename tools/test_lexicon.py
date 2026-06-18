# -*- coding: utf-8 -*-
"""
test_lexicon.py — OFFLINE verification (NOT shipped). Phoneme model.

(1) DATA INTEGRITY: independently recompute each word's PHONEME position index
    from its vocalized form and compare to what build_lexicon.py baked in.
(2) CONSTRAINT: generate sentences for every (phoneme x position) cell and assert
    every word is >=3 words and actually carries the target SOUND at the chosen
    position (re-derived independently from the niqqud).

Run:  python3 tools/test_lexicon.py
"""
import json, os, random, sys, unicodedata

random.seed(42)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEX = json.load(open(os.path.join(ROOT, "lexicon.json"), encoding="utf-8"))

FOLD = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}
DAG, SHIN, SIN, HIRIQ, TSERE = "ּ", "ׁ", "ׂ", "ִ", "ֵ"
VOWELP = {chr(c) for c in range(0x05B0, 0x05BC)} | {chr(0x05C7)}
def isniq(c): return "֑" <= c <= "ׇ"
def heb(c): return "א" <= c <= "ת"
SIMPLE = {"ס": "S", "ת": "T", "ט": "T", "ק": "K", "ח": "X", "ג": "G", "ד": "D",
          "ז": "Z", "ל": "L", "מ": "M", "נ": "N", "צ": "TS", "ר": "R", "א": "GLOTTAL", "ע": "GLOTTAL"}
PHON = ["GLOTTAL", "B", "V", "G", "D", "H", "Z", "X", "T", "Y", "K", "L", "M", "N", "S", "P", "F", "TS", "R", "SH"]
POS = ["FIRST", "MIDDLE", "LAST"]
GN = {"ms": ("m", "sg"), "fs": ("f", "sg"), "mp": ("m", "pl"), "fp": ("f", "pl")}

PASS = [0]; FAILS = []
def check(c, m): (PASS.__setitem__(0, PASS[0] + 1) if c else FAILS.append(m))


def sound_of(base, m, is_first, is_last, prev):
    if base == "ב": return "B" if DAG in m else "V"
    if base == "כ": return "K" if DAG in m else "X"
    if base == "פ": return "P" if DAG in m else "F"
    if base == "ש": return "SH" if SHIN in m else ("S" if SIN in m else None)
    if base in SIMPLE: return SIMPLE[base]
    if base == "ה": return None if (is_last and DAG not in m) else "H"
    if base == "ו":
        if ("ֹ" in m) or ("ֺ" in m): return None
        if DAG in m: return None
        if VOWELP & set(m): return "V"
        return "V" if is_first else None
    if base == "י":
        if VOWELP & set(m): return "Y"
        if is_first: return "Y"
        if (HIRIQ in prev) or (TSERE in prev): return None
        return "Y"
    return None


def pidx(w):
    """Independent phoneme index {phoneme: sorted[positions]}."""
    ch = list(w); n = len(ch); idx = {}; i = 0; prev = ""
    while i < n:
        base = FOLD.get(ch[i], ch[i])
        if not heb(base): i += 1; continue
        j = i + 1; mk = ""
        while j < n and isniq(ch[j]): mk += ch[j]; j += 1
        s = sound_of(base, mk, i == 0, j >= n, prev)
        if s:
            pos = "FIRST" if i == 0 else ("LAST" if j >= n else "MIDDLE")
            idx.setdefault(s, set()).add(pos)
        prev = mk; i = j
    return {k: sorted(v) for k, v in idx.items()}


def eq(a, b):
    if sorted(a) != sorted(b): return False
    return all(sorted(a[k]) == sorted(b[k]) for k in a)


# ---- (1) integrity: stored idx == independent recompute ----
for e in LEX["nouns"]:
    check(eq(pidx(e["w"]), e["idx"]), f"noun idx mismatch: {e['w']}")
for kind in ("adjectives", "verbs"):
    for e in LEX[kind]:
        for k in GN:
            f = e["forms"][k]
            check(eq(pidx(f["w"]), f["idx"]), f"{kind} idx mismatch: {f['w']}")


# ---- engine (mirrors the in-page JS; matches on the stored phoneme idx) ----
# match iff the sound is present AND confined to the selected positions (every
# occurrence in ps) — a word with the sound also at an unselected slot is rejected.
def mpos(idx, ph, ps): return ph in idx and all(x in ps for x in idx[ph])
def gnf(nn): return nn["g"] + "-" + nn["n"]


def candidates(ph, ps):
    nouns = [e for e in LEX["nouns"] if mpos(e["idx"], ph, ps)]
    adj = {}; verb = {}
    for e in LEX["adjectives"]:
        for k in GN:
            if mpos(e["forms"][k]["idx"], ph, ps):
                adj.setdefault("-".join(GN[k]), []).append(e["forms"][k]["w"])
    for e in LEX["verbs"]:
        for k in GN:
            if mpos(e["forms"][k]["idx"], ph, ps):
                verb.setdefault("-".join(GN[k]), []).append((e["forms"][k]["w"], e["trans"]))
    return nouns, adj, verb


def build_sentence(ph, ps):
    nouns, adj, verb = candidates(ph, ps)
    ns = nouns[:]; random.shuffle(ns)
    for subj in ns:
        gn = "-".join((subj["g"], subj["n"]))
        adjs = adj.get(gn, []); verbs = verb.get(gn, [])
        tverbs = [w for (w, tr) in verbs if tr]
        objs = [o["w"] for o in nouns if o["w"] != subj["w"]]
        for t in random.sample(["A", "C", "B", "D"], 4):
            if t == "A" and adjs and verbs: return [subj["w"], random.choice(adjs), random.choice(verbs)[0]]
            if t == "C" and adjs and tverbs and objs: return [subj["w"], random.choice(adjs), random.choice(tverbs), random.choice(objs)]
            if t == "B" and tverbs and objs: return [subj["w"], random.choice(tverbs), random.choice(objs)]
            if t == "D" and tverbs and objs:
                obj = random.choice(objs)
                oe = next(o for o in nouns if o["w"] == obj)
                oadj = [a for a in adj.get("-".join((oe["g"], oe["n"])), []) if a != obj]
                if oadj: return [subj["w"], random.choice(tverbs), obj, random.choice(oadj)]
    return None


def generate(ph, ps, n):
    out, seen, att = [], set(), 0
    while len(out) < n and att < max(800, n * 200):
        att += 1
        s = build_sentence(ph, ps)
        if not s: break
        if len(set(s)) != len(s): continue
        key = " ".join(s)
        if key in seen: continue
        seen.add(key); out.append(s)
    return out


# ---- (2) constraint across every cell ----
feasible, total = 0, 0
for ph in PHON:
    for P in POS:
        sents = generate(ph, [P], 10)
        if sents: feasible += 1
        for words in sents:
            total += 1
            check(len(words) >= 3, f"<3 words: {' '.join(words)}")
            for w in words:
                check(mpos(pidx(w), ph, [P]), f'word "{w}": /{ph}/ not confined to {P}')

# multi-position unions
for ph, ps in [("SH", ["FIRST", "LAST"]), ("X", ["FIRST", "MIDDLE", "LAST"])]:
    for words in generate(ph, ps, 8):
        for w in words:
            check(mpos(pidx(w), ph, ps), f'multi "{w}": /{ph}/ not confined to {ps}')


# ---- (3) DATA-CORRECTNESS HARNESS: niqqud well-formedness + consistency ----
# Structural INVARIANTS (a violation is always wrong, whatever word was meant) are
# hard-gated via check(): they protect the runtime — e.g. a dotless ש makes sound_of()
# return None, silently dropping the word out of highlighting/TTS/matching. They do NOT
# verify the chosen VOWEL is correct (that needs ground truth -> native review). Morphology
# HEURISTICS that are clean today but could false-positive on a future irregular form only
# WARN, so a regeneration is never wrongly blocked.
DAGESH, SHIN_DOT, SIN_DOT = "ּ", "ׁ", "ׂ"
HOLAMS = {"ֹ", "ֺ"}
MATRES = {"א", "ה", "ו", "י"}
NO_DAGESH = {"א", "ח", "ע", "ר"}            # gutturals + resh never take dagesh (final-ה mapiq is separate)
LETTERS = {chr(c) for c in range(0x05D0, 0x05EB)}
ALLOWED = LETTERS | {chr(c) for c in range(0x05B0, 0x05BD)} | {SHIN_DOT, SIN_DOT, "ׇ", "־", " "}
WARN = []


def parse_units(w):
    """[(base, marks)] per base char; orphan=True if any combining mark has no base before it."""
    ch = list(w); n = len(ch); i = 0; out = []; orphan = False
    while i < n:
        if isniq(ch[i]): orphan = True; i += 1; continue
        j = i + 1; mk = ""
        while j < n and isniq(ch[j]): mk += ch[j]; j += 1
        out.append((ch[i], mk)); i = j
    return out, orphan


ALL_FORMS = [e["w"] for e in LEX["nouns"]]
for _kind in ("adjectives", "verbs"):
    for _e in LEX[_kind]:
        ALL_FORMS += [_e["forms"][k]["w"] for k in GN]

_p0, _f0 = PASS[0], len(FAILS)
for w in ALL_FORMS:
    check(unicodedata.normalize("NFC", w) == w, f"not NFC-normalized: {w}")
    bad = sorted({c for c in w if c not in ALLOWED})
    check(not bad, f"illegal codepoint(s) {[hex(ord(c)) for c in bad]} in: {w}")
    units, orphan = parse_units(w)
    check(not orphan, f"combining mark with no base letter: {w}")
    letters = [(b, m) for (b, m) in units if heb(b)]
    for (b, m) in units:
        check(len([c for c in m if c in VOWELP]) <= 1, f"two vowel points on one '{b}' in: {w}")
        check(len(set(m)) == len(m), f"duplicate mark on '{b}' in: {w}")
        if not heb(b): continue
        if b == "ש":
            check((SHIN_DOT in m) != (SIN_DOT in m), f"ש needs exactly one shin/sin dot in: {w}")
        else:
            check(not (SHIN_DOT in m or SIN_DOT in m), f"shin/sin dot on '{b}' in: {w}")
        if b in NO_DAGESH:
            check(DAGESH not in m, f"illegal dagesh on '{b}' in: {w}")
    check(bool(pidx(w)), f"word yields no phonemes: {w}")
    # heuristic (WARN only): an interior consonant left with no vowel point
    for ix, (b, m) in enumerate(letters):
        if b in MATRES or ix == len(letters) - 1: continue          # matres + final letter need no vowel
        if any(c in VOWELP for c in m): continue                    # has a vowel / shva
        nb, nm = letters[ix + 1]
        if nb == "ו" and (HOLAMS & set(nm) or DAGESH in nm): continue   # vowel carried by holam-vav / shuruk
        if nb == "א": continue                                      # quiescent alef
        WARN.append(f"interior letter '{b}' unpointed in: {w}")
        break


# heuristic (WARN only): the 4 agreement forms look like a regular paradigm
def _strip(s): return "".join(c for c in s if not isniq(c))
def _fold(s): return "".join(FOLD[c] if c in FOLD else c for c in s)
for _kind in ("adjectives", "verbs"):
    for _e in LEX[_kind]:
        ms, fs, mp, fp = (_e["forms"][k]["w"] for k in ("ms", "fs", "mp", "fp"))
        tag = f"{_kind[:-1]} [{ms}/{fs}/{mp}/{fp}]"
        sfs, smp, sfp = _strip(fs), _strip(mp), _strip(fp)
        if not (sfs.endswith("ה") or sfs.endswith("ת")): WARN.append(f"fem-sg lacks ה/ת suffix: {tag}")
        if not smp.endswith("ים"): WARN.append(f"masc-pl lacks ים suffix: {tag}")
        if not sfp.endswith("ות"): WARN.append(f"fem-pl lacks ות suffix: {tag}")
        if len({_fold(_strip(x))[:2] for x in (ms, fs, mp, fp)}) != 1:
            WARN.append(f"4 forms don't share a 2-letter stem: {tag}")
STRUCT = PASS[0] - _p0 + len(FAILS) - _f0


print("=" * 60)
print("PHONEME LEXICON / ENGINE VERIFICATION")
print("=" * 60)
print(f"  feasible cells   : {feasible}/{len(PHON)*3}")
print(f"  sentences checked: {total}")
print(f"  assertions       : {PASS[0]} passed, {len(FAILS)} failed")
for m in FAILS[:20]: print("   -", m)
print(f"  data hygiene     : {STRUCT} structural checks on {len(ALL_FORMS)} forms, {len(WARN)} warnings")
for m in WARN[:20]: print("   ~", m)
print("\n  samples:")
for ph, P in [("K", "FIRST"), ("X", "MIDDLE"), ("S", "FIRST"), ("T", "LAST"), ("V", "MIDDLE")]:
    print(f"   /{ph}/ {P}:  " + "  |  ".join(" ".join(x) for x in generate(ph, [P], 3)))
sys.exit(1 if FAILS else 0)
