# -*- coding: utf-8 -*-
"""
test_lexicon.py — OFFLINE verification (NOT shipped).

Reference oracle for the generation logic. The browser engine in index.html is a
faithful JS mirror of the algorithm below; this Python version is the source of
truth we test against. Two things are verified:

  (1) DATA INTEGRITY: independently recompute every word's position index from its
      surface string and compare to what build_lexicon.py baked into lexicon.json.
  (2) CONSTRAINT: generate sentences for all 66 (letter x position) cells and assert
      every word is >=3-word-grammatical-shape and actually carries the target letter
      at the chosen position (with final-form folding).

Run:  python3 tools/test_lexicon.py
"""

import json
import os
import random
import re
import sys

random.seed(42)  # deterministic / reproducible

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEX = json.load(open(os.path.join(ROOT, "lexicon.json"), encoding="utf-8"))

NIQQUD = re.compile(r"[֑-ׇ]")
FOLD = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}
BASE = set("אבגדהוזחטיכלמנסעפצקרשת")
LETTERS = list("אבגדהוזחטיכלמנסעפצקרשת")
POS = ["FIRST", "MIDDLE", "LAST"]
GN = {"ms": "m-sg", "fs": "f-sg", "mp": "m-pl", "fp": "f-pl"}

PASS = [0]
FAILS = []


def check(cond, msg):
    if cond:
        PASS[0] += 1
    else:
        FAILS.append(msg)


# ---------- (1) independent position-index recompute ----------
def idx_of(form):
    s = NIQQUD.sub("", form)
    n = len(s)
    idx = {}
    for i, ch in enumerate(s):
        base = FOLD.get(ch, ch)
        if base not in BASE:
            continue
        pos = "FIRST" if i == 0 else ("LAST" if i == n - 1 else "MIDDLE")
        idx.setdefault(base, [])
        if pos not in idx[base]:
            idx[base].append(pos)
    return idx


def eq_idx(a, b):
    if sorted(a) != sorted(b):
        return False
    return all(sorted(a[k]) == sorted(b[k]) for k in a)


for e in LEX["nouns"]:
    check(eq_idx(idx_of(e["w"]), e["idx"]), f"noun idx mismatch: {e['w']}")
    check(e.get("s") == NIQQUD.sub("", e["w"]), f"noun s mismatch: {e['w']}")
for kind in ("adjectives", "verbs"):
    for e in LEX[kind]:
        for k in GN:
            f = e["forms"][k]
            check(eq_idx(idx_of(f["w"]), f["idx"]), f"{kind} idx mismatch: {f['w']}")
            check(f.get("s") == NIQQUD.sub("", f["w"]), f"{kind} s mismatch: {f['w']}")


# ---------- engine (reference; mirrored by the JS in index.html) ----------
def match_pos(idx, L, ps):
    p = idx.get(L)
    return bool(p) and any(x in ps for x in p)


def gn_of(noun):
    return noun["g"] + "-" + noun["n"]


def candidates_for(L, ps):
    nouns = [e for e in LEX["nouns"] if match_pos(e["idx"], L, ps)]
    adj_by_gn, verb_by_gn = {}, {}
    for e in LEX["adjectives"]:
        for k, gn in GN.items():
            if match_pos(e["forms"][k]["idx"], L, ps):
                adj_by_gn.setdefault(gn, []).append(e["forms"][k]["w"])
    for e in LEX["verbs"]:
        for k, gn in GN.items():
            if match_pos(e["forms"][k]["idx"], L, ps):
                verb_by_gn.setdefault(gn, []).append((e["forms"][k]["w"], e["trans"]))
    return {"nouns": nouns, "adj": adj_by_gn, "verb": verb_by_gn}


def try_template(t, c, subj):
    gn = gn_of(subj)
    adjs = c["adj"].get(gn, [])
    verbs = c["verb"].get(gn, [])
    tverbs = [w for (w, tr) in verbs if tr]
    objs = [o for o in c["nouns"] if o["w"] != subj["w"]]
    if t == "A" and adjs and verbs:
        return [subj["w"], random.choice(adjs), random.choice(verbs)[0]]
    if t == "C" and adjs and tverbs and objs:
        return [subj["w"], random.choice(adjs), random.choice(tverbs), random.choice(objs)["w"]]
    if t == "B" and tverbs and objs:
        return [subj["w"], random.choice(tverbs), random.choice(objs)["w"]]
    if t == "D" and tverbs and objs:
        obj = random.choice(objs)
        oadj = [a for a in c["adj"].get(gn_of(obj), []) if a != obj["w"]]
        if oadj:
            return [subj["w"], random.choice(tverbs), obj["w"], random.choice(oadj)]
    return None


def build_sentence(c):
    nouns = c["nouns"][:]
    random.shuffle(nouns)
    for subj in nouns:                         # try every subject (the bug fix)
        tmpls = ["A", "C", "B", "D"]
        random.shuffle(tmpls)
        for t in tmpls:
            s = try_template(t, c, subj)
            if s:
                return s
    return None


def generate(L, ps, n):
    c = candidates_for(L, ps)
    if not c["nouns"]:
        return []
    out, seen, attempts = [], set(), 0
    cap = max(800, n * 200)
    while len(out) < n and attempts < cap:
        attempts += 1
        s = build_sentence(c)
        if not s:
            break
        if len(set(s)) != len(s):
            continue
        key = " ".join(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------- (2) constraint across every cell ----------
feasible, total = 0, 0
for L in LETTERS:
    for P in POS:
        sents = generate(L, [P], 10)
        if sents:
            feasible += 1
        for words in sents:
            total += 1
            check(len(words) >= 3, f"<3 words: {' '.join(words)}")
            for w in words:
                check(match_pos(idx_of(w), L, [P]), f'word "{w}" lacks {L}@{P}')

# multi-position unions must never violate
for L, ps in [("ש", ["FIRST", "LAST"]), ("מ", ["FIRST", "MIDDLE", "LAST"])]:
    for words in generate(L, ps, 10):
        for w in words:
            check(match_pos(idx_of(w), L, ps), f'multi "{w}" not {L}@{ps}')

print("=" * 60)
print("LEXICON / ENGINE VERIFICATION")
print("=" * 60)
print(f"  feasible cells   : {feasible}/66")
print(f"  sentences checked: {total}")
print(f"  assertions       : {PASS[0]} passed, {len(FAILS)} failed")
if FAILS:
    print("\n  FAILURES:")
    for m in FAILS[:20]:
        print("   -", m)

print("\n  sample sentences:")
for L, P in [("ש", "FIRST"), ("ב", "FIRST"), ("ל", "MIDDLE"), ("ר", "LAST"), ("מ", "LAST")]:
    s = "  |  ".join(" ".join(x) for x in generate(L, [P], 3))
    print(f"   {L}/{P}:  {s}")

sys.exit(1 if FAILS else 0)
