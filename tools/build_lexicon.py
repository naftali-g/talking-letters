# -*- coding: utf-8 -*-
"""
build_lexicon.py — OFFLINE build tool for משחק האותיות (NOT shipped in the game).

Pipeline:
  1. read the human-edited seed (words.py)
  2. strip niqqud, fold final letters, compute the FIRST/MIDDLE/LAST position index
  3. validate entries (length >= 3, 4 forms on adj/verbs, gender present)
  4. build the per-(letter, position) coverage matrix and flag dead cells
  5. generate demo sentences to prove the data yields grammatical 3-4 word output
  6. emit ../lexicon.json (minified, ready to inline) + ./coverage.md

Run:  python3 tools/build_lexicon.py
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import words as W  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

NIQQUD = re.compile(r"[֑-ׇ]")          # Hebrew points / cantillation
HEB_LETTER = re.compile(r"[א-ת]")      # base + final Hebrew consonants
FINALS = {"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"}
LETTERS = list("אבגדהוזחטיכלמנסעפצקרשת")          # 22 base letters (final forms folded)
BASE_SET = set(LETTERS)
MIN_LEN = 2   # 1-letter words are degenerate (first==last); 2-letter words are fine
              # (distinct first/last, just never a MIDDLE) and recover קר/חם/דג/עץ ...
POSITIONS = ["FIRST", "MIDDLE", "LAST"]
# (gender, number) <-> adjective/verb form key
GN_OF_KEY = {"ms": ("m", "sg"), "fs": ("f", "sg"), "mp": ("m", "pl"), "fp": ("f", "pl")}
KEY_OF_GN = {v: k for k, v in GN_OF_KEY.items()}

WARNINGS = []


def strip_niqqud(s):
    return NIQQUD.sub("", s)


def fold(ch):
    return FINALS.get(ch, ch)


def pos_index(form):
    """Return {base_letter: [positions...]} for an unvocalized surface form."""
    s = strip_niqqud(form)
    chars = list(s)
    n = len(chars)
    idx = {}
    for i, ch in enumerate(chars):
        base = fold(ch)
        if base not in BASE_SET:
            continue
        if i == 0:
            pos = "FIRST"
        elif i == n - 1:
            pos = "LAST"
        else:
            pos = "MIDDLE"
        idx.setdefault(base, [])
        if pos not in idx[base]:
            idx[base].append(pos)
    return idx, n


def stripped_len(form):
    return len(HEB_LETTER.findall(strip_niqqud(form)))


# ---------------------------------------------------------------------------
# 1-3. build + validate entries
# ---------------------------------------------------------------------------
def build():
    nouns, adjectives, verbs = [], [], []

    for (w, g, num) in W.NOUNS:
        if stripped_len(w) < MIN_LEN:
            WARNINGS.append(f"NOUN dropped (len<{MIN_LEN}): {w}")
            continue
        if g not in ("m", "f") or num not in ("sg", "pl"):
            WARNINGS.append(f"NOUN bad tags: {w} g={g} n={num}")
            continue
        idx, _ = pos_index(w)
        nouns.append({"w": w, "s": strip_niqqud(w), "g": g, "n": num, "idx": idx})

    for forms in W.ADJECTIVES:
        if len(forms) != 4 or any(not f for f in forms):
            WARNINGS.append(f"ADJ needs 4 non-empty forms: {forms}")
            continue
        ms, fs, mp, fp = forms
        if min(stripped_len(f) for f in forms) < MIN_LEN:
            WARNINGS.append(f"ADJ has a <{MIN_LEN}-letter form (dropped): {forms}")
            continue
        entry = {"lemma": ms, "forms": {}}
        for key, form in zip(("ms", "fs", "mp", "fp"), forms):
            idx, _ = pos_index(form)
            entry["forms"][key] = {"w": form, "s": strip_niqqud(form), "idx": idx}
        adjectives.append(entry)

    for row in W.VERBS:
        if len(row) != 5:
            WARNINGS.append(f"VERB needs (ms,fs,mp,fp,trans): {row}")
            continue
        ms, fs, mp, fp, trans = row
        forms = (ms, fs, mp, fp)
        if any(not f for f in forms):
            WARNINGS.append(f"VERB empty form: {row}")
            continue
        if min(stripped_len(f) for f in forms) < MIN_LEN:
            WARNINGS.append(f"VERB form too short: {row}")
            continue
        entry = {"lemma": ms, "trans": bool(trans), "forms": {}}
        for key, form in zip(("ms", "fs", "mp", "fp"), forms):
            idx, _ = pos_index(form)
            entry["forms"][key] = {"w": form, "s": strip_niqqud(form), "idx": idx}
        verbs.append(entry)

    return {"nouns": nouns, "adjectives": adjectives, "verbs": verbs}


# ---------------------------------------------------------------------------
# helpers for matching & coverage
# ---------------------------------------------------------------------------
def matches(idx, letter, positions):
    p = idx.get(letter)
    return bool(p) and any(x in positions for x in p)


def coverage(lex):
    """For each (letter, position): counts + which 3-word templates are feasible."""
    matrix = {}
    for L in LETTERS:
        for P in POSITIONS:
            ps = [P]
            noun_gn = {gn: 0 for gn in GN_OF_KEY.values()}
            n_total = 0
            for e in lex["nouns"]:
                if matches(e["idx"], L, ps):
                    noun_gn[(e["g"], e["n"])] += 1
                    n_total += 1
            adj_gn = {gn: 0 for gn in GN_OF_KEY.values()}
            for e in lex["adjectives"]:
                for key, gn in GN_OF_KEY.items():
                    if matches(e["forms"][key]["idx"], L, ps):
                        adj_gn[gn] += 1
            verb_gn = {gn: 0 for gn in GN_OF_KEY.values()}
            verb_tr_gn = {gn: 0 for gn in GN_OF_KEY.values()}
            for e in lex["verbs"]:
                for key, gn in GN_OF_KEY.items():
                    if matches(e["forms"][key]["idx"], L, ps):
                        verb_gn[gn] += 1
                        if e["trans"]:
                            verb_tr_gn[gn] += 1
            # template A (N + Adj + V): some (g,n) with all three present
            a_ok = any(noun_gn[gn] and adj_gn[gn] and verb_gn[gn] for gn in GN_OF_KEY.values())
            # template B (N + transV + Obj): subject(g,n) + trans verb(g,n) + another matching noun
            b_ok = (n_total >= 2) and any(noun_gn[gn] and verb_tr_gn[gn] for gn in GN_OF_KEY.values())
            matrix[(L, P)] = {
                "n": n_total,
                "a": sum(adj_gn.values()),
                "v": sum(verb_gn.values()),
                "A": a_ok, "B": b_ok, "ok": a_ok or b_ok,
            }
    return matrix


# ---------------------------------------------------------------------------
# 5. demo generator (a faithful preview of the Phase-2 engine)
# ---------------------------------------------------------------------------
def gen_samples(lex, letter, position, limit=6):
    ps = [position]
    nouns = [e for e in lex["nouns"] if matches(e["idx"], letter, ps)]
    out, seen = [], set()

    def adj_form(gn):
        key = KEY_OF_GN[gn]
        return [e["forms"][key]["w"] for e in lex["adjectives"]
                if matches(e["forms"][key]["idx"], letter, ps)]

    def verb_form(gn, trans_only=False):
        key = KEY_OF_GN[gn]
        return [e["forms"][key]["w"] for e in lex["verbs"]
                if (not trans_only or e["trans"]) and matches(e["forms"][key]["idx"], letter, ps)]

    def add(words, tmpl):
        s = " ".join(words)
        if s not in seen and len(set(words)) == len(words):
            seen.add(s)
            out.append((s, tmpl))

    for subj in nouns:
        gn = (subj["g"], subj["n"])
        adjs = adj_form(gn)
        verbs = verb_form(gn)
        tverbs = verb_form(gn, trans_only=True)
        objs = [o["w"] for o in nouns if o["w"] != subj["w"]]
        # A: N + Adj + V
        if adjs and verbs:
            add([subj["w"], adjs[0], verbs[0]], "A·3w")
        # C: N + Adj + transV + Obj
        if adjs and tverbs and objs:
            add([subj["w"], adjs[0], tverbs[0], objs[0]], "C·4w")
        # B: N + transV + Obj
        if tverbs and objs:
            add([subj["w"], tverbs[0], objs[0]], "B·3w")
        # D: N + transV + Obj + Adj(agree w/ obj)
        if tverbs and objs:
            obj_entry = next(o for o in nouns if o["w"] == objs[0])
            oadj = adj_form((obj_entry["g"], obj_entry["n"]))
            oadj = [a for a in oadj if a not in (objs[0],)]
            if oadj:
                add([subj["w"], tverbs[0], objs[0], oadj[0]], "D·4w")
        if len(out) >= limit:
            break
    return out[:limit]


# ---------------------------------------------------------------------------
# reporting / output
# ---------------------------------------------------------------------------
def surface_form_count(lex):
    return (len(lex["nouns"])
            + 4 * len(lex["adjectives"])
            + 4 * len(lex["verbs"]))


def write_coverage_md(matrix, lex):
    lines = []
    lines.append("# Coverage matrix — seed lexicon\n")
    lines.append(f"_Auto-generated by build_lexicon.py. "
                 f"{len(lex['nouns'])} nouns · {len(lex['adjectives'])} adjectives · "
                 f"{len(lex['verbs'])} verbs._\n")
    feasible = sum(1 for v in matrix.values() if v["ok"])
    lines.append(f"**Feasible cells (≥1 grammatical 3-word sentence): "
                 f"{feasible}/{len(matrix)}**\n")
    lines.append("Cell = `✓/✗  Nn Aa Vv` (nouns / adjective-forms / verb-forms matching).\n")
    lines.append("| אות | תחילה (FIRST) | אמצע (MIDDLE) | סוף (LAST) |")
    lines.append("|---|---|---|---|")
    for L in LETTERS:
        row = [f"`{L}`"]
        for P in POSITIONS:
            c = matrix[(L, P)]
            mark = "✓" if c["ok"] else "✗"
            row.append(f"{mark} {c['n']}n {c['a']}a {c['v']}v")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    dead = [f"{L}/{P}" for (L, P), v in matrix.items() if not v["ok"]]
    if dead:
        lines.append("## Dead cells (need more words before they can ship)\n")
        lines.append(", ".join(dead) + "\n")
    with open(os.path.join(HERE, "coverage.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    lex = build()

    out_path = os.path.join(ROOT, "lexicon.json")
    minified = json.dumps(lex, ensure_ascii=False, separators=(",", ":"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(minified)
    size_kb = os.path.getsize(out_path) / 1024

    # Build the single-file game: inject the lexicon into the template -> index.html
    index_kb = None
    tmpl_path = os.path.join(HERE, "template.html")
    if os.path.exists(tmpl_path):
        with open(tmpl_path, encoding="utf-8") as f:
            tmpl = f.read()
        if "__LEXICON_JSON__" not in tmpl:
            WARNINGS.append("template.html has no __LEXICON_JSON__ placeholder")
        html = tmpl.replace("__LEXICON_JSON__", minified)
        index_path = os.path.join(ROOT, "index.html")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)
        index_kb = os.path.getsize(index_path) / 1024

    matrix = coverage(lex)
    write_coverage_md(matrix, lex)

    feasible = sum(1 for v in matrix.values() if v["ok"])
    print("=" * 64)
    print("BUILD: lexicon.json")
    print("=" * 64)
    print(f"  nouns={len(lex['nouns'])}  adjectives={len(lex['adjectives'])}  "
          f"verbs={len(lex['verbs'])}")
    print(f"  surface forms = {surface_form_count(lex)}")
    print(f"  lexicon.json  = {size_kb:.1f} KB minified")
    if index_kb is not None:
        print(f"  index.html    = {index_kb:.1f} KB  (single-file game, lexicon embedded)")
    print(f"  coverage      = {feasible}/{len(matrix)} (letter×position) cells feasible")
    if WARNINGS:
        print(f"\n  WARNINGS ({len(WARNINGS)}):")
        for w in WARNINGS:
            print("   -", w)

    print("\n" + "=" * 64)
    print("COVERAGE MATRIX  (✓/✗  n=nouns a=adj-forms v=verb-forms)")
    print("=" * 64)
    print(f"  {'':3} {'FIRST':>14} {'MIDDLE':>14} {'LAST':>14}")
    for L in LETTERS:
        cells = []
        for P in POSITIONS:
            c = matrix[(L, P)]
            cells.append(f"{'OK ' if c['ok'] else '-- '}{c['n']}n{c['a']}a{c['v']}v")
        print(f"  {L:3} {cells[0]:>14} {cells[1]:>14} {cells[2]:>14}")

    print("\n" + "=" * 64)
    print("DEMO SENTENCES  (proves the data yields grammatical output)")
    print("=" * 64)
    demos = [("ש", "FIRST"), ("ב", "FIRST"), ("מ", "FIRST"), ("ק", "FIRST"),
             ("ת", "FIRST"), ("ח", "FIRST"), ("ל", "MIDDLE"), ("ר", "LAST")]
    for (L, P) in demos:
        print(f"\n  אות '{L}' · {P}:")
        samples = gen_samples(lex, L, P, limit=5)
        if not samples:
            print("    (no sentences — dead cell)")
        for s, tmpl in samples:
            print(f"    [{tmpl}]  {s}")

    print()


if __name__ == "__main__":
    main()
