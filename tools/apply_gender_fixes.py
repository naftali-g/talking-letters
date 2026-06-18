# -*- coding: utf-8 -*-
"""apply_gender_fixes.py — consume gender_decisions.json from tools/gender_review.html and flip
noun genders directly in the source (generated_lexicon*.json), transactionally, then rebuild.

Decisions: {"fixes":[{"w":"<vocalized noun>","old":"m|f","new":"m|f"}, ...], "accepted":["<w>", ...]}
Each fix sets g=new on the noun entry whose vocalized form == w (entry-aware JSON patch — no text
replacement, no homograph broadcast). Accepted words (reviewer kept ours over Wiktionary) go to
tools/gender_accepted.json so the audit stops re-flagging them. All-or-nothing write + rebuild rollback.

Usage:  python3 tools/apply_gender_fixes.py <gender_decisions.json> [--no-build]
"""
import glob
import json
import os
import subprocess
import sys
from typing import NoReturn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apply_niqqud_fixes import dump_like   # reuse the format-matching serializer (minimal diff)

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = sorted(glob.glob(os.path.join(HERE, "generated_lexicon*.json")))
ACCEPTED = os.path.join(HERE, "gender_accepted.json")


def die(msg) -> NoReturn:
    print("ERROR:", msg)
    sys.exit(2)


def main():
    argv = sys.argv[1:]
    no_build = "--no-build" in argv
    argv = [a for a in argv if not a.startswith("--")]
    if not argv:
        die("usage: apply_gender_fixes.py <decisions.json> [--no-build]")
    dec = json.load(open(argv[0], encoding="utf-8"))
    accepted_in = [a for a in (dec.get("accepted", []) or []) if isinstance(a, str)]
    clean = []
    for f in (dec.get("fixes", []) or []):
        w, new = f.get("w"), f.get("new")
        if not isinstance(w, str) or new not in ("m", "f"):
            die(f"bad fix (need w:str, new in m/f): {f!r}")
        clean.append((w, new))
    print(f"applying {len(clean)} gender flip(s), {len(accepted_in)} kept-as-ours")

    snap = {p: open(p, encoding="utf-8").read() for p in GEN}
    obj = {p: json.loads(snap[p]) for p in GEN}
    applied, missing, changed = [], [], set()
    for w, new in clean:
        hit = 0
        for p in GEN:
            for e in obj[p].get("nouns", []):
                if e.get("w") == w and e.get("g") != new:
                    e["g"] = new
                    hit += 1
                    changed.add(p)
        if hit:
            applied.append(w)
            print(f"  ✓ {w} -> {new}")
        else:
            missing.append(w)
            print(f"  ⚠ {w} not found (or already {new}) — skipped")

    staged = {p: dump_like(snap[p], obj[p]) for p in changed}
    written = []
    try:
        for p, t in staged.items():
            if t == snap[p]:
                continue
            tmp = p + ".tmp"
            open(tmp, "w", encoding="utf-8").write(t)
            os.replace(tmp, p)
            written.append(p)
    except Exception as e:
        for p in written:
            open(p, "w", encoding="utf-8").write(snap[p])
        die(f"write failed — restored sources: {e!r}")

    acc_before = sorted(set(json.load(open(ACCEPTED, encoding="utf-8")))) if os.path.exists(ACCEPTED) else []
    acc = sorted(set(acc_before) | set(accepted_in))   # only "kept ours" need suppression; fixed words now agree
    json.dump(acc, open(ACCEPTED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if no_build:
        print(f"staged {len(written)} file(s); skipped rebuild (--no-build).")
        return
    print("rebuilding lexicon (merge_lexicon + build_lexicon)...")
    try:
        subprocess.run([sys.executable, os.path.join(HERE, "merge_lexicon.py")], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, os.path.join(HERE, "build_lexicon.py")], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        for p in written:
            open(p, "w", encoding="utf-8").write(snap[p])
        json.dump(acc_before, open(ACCEPTED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        die(f"rebuild failed — rolled back: {e!r}")
    print(f"done. {len(applied)} gender flip(s)"
          + (f", {len(missing)} skipped" if missing else "")
          + ". Re-run tools/audit_gender.py to confirm; tools/test_lexicon.py to gate.")


if __name__ == "__main__":
    main()
