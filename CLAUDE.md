# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

צְלִילוֹן ("Tslilon" — roughly "little sound"); tagline מַשְׁמִיעִים צְלִילִים ("we make
sounds heard"). A Hebrew speech-therapy game for kids. The user picks a **sound** (phoneme)
+ position(s) (first/middle/last) + a count, and the game generates grammatical, ≥3-word
Hebrew sentences where **every word makes that sound at the chosen position**. RTL kids' UI,
fully niqqud-vocalized, with Web Speech TTS.

The focus is on the **sound**, not the letter. The mascot is an orange **speech-bubble**
creature (a sound, not a letter), and the win screen plays an animated jumping version
(`mascot_anim.webp`).

Deploys to **GitHub Pages** (`origin` = `naftali-g/tslilon`;
public site at `naftali-g.github.io/tslilon/`) as a static folder:
`index.html` + `lexicon.json` + the image assets at the repo root. Multi-file is fine —
single-file is *not* a requirement.

## Build & test commands

Tooling is all Python and lives in `tools/`. The two-step build is the core workflow:

```bash
python3 tools/merge_lexicon.py      # -> tools/words.py        (combine sources)
python3 tools/build_lexicon.py      # -> lexicon.json + index.html + tools/coverage.md
python3 tools/test_lexicon.py       # verify the shipped lexicon.json (exit 1 on failure)
python3 tools/make_assets.py        # rebuild logo.webp / favicon.png / mascot.webp from logo.png
python3 tools/make_mascot_anim.py   # rebuild mascot_anim.webp (looping win-screen bubble) from jumping_logo.mp4  [needs PyAV: pip install av]
python3 tools/make_og_image.py      # rebuild og-image.png (1200x630 social-share card) from logo.webp
python3 tools/analyze_sounds.py     # read-only phoneme coverage + matres/silent sanity report
```

After any lexicon change: run `merge_lexicon.py` → `build_lexicon.py` → `test_lexicon.py`.
Image assets are independent: re-run `make_assets.py` only if `logo.png` changes,
`make_mascot_anim.py` only if `jumping_logo.mp4` changes, and `make_og_image.py` only if the
logo/branding changes.

There is no dev server: open `index.html` directly (`file://`) — asset references are relative
so it works both locally and on Pages.

## Architecture

**Generated vs. authored.** Several files are build outputs (see `.gitignore`) — do **not**
hand-edit them: `tools/words.py`, `lexicon.json`, `tools/coverage.md`, and `index.html`
(generated from `tools/template.html`). Edit the *sources* and rebuild.

**Lexicon data flow** (`merge_lexicon.py`):
- `tools/words_seed.py` — hand-verified genders/numbers, frozen. Seed genders win on conflict.
- `tools/generated_lexicon*.json` — LLM-generated, niqqud-vocalized vocabulary (the bulk).
- `tools/words_extra.py` — hand-curated gap-fills (only fill gaps; generated entries win).
- → merged into `tools/words.py` (all forms vocalized).

**The phoneme model** is the heart of the system (`build_lexicon.py` `sound_of()` /
`phoneme_index()`). 20 phonemes drive matching/highlighting/feasibility. Each consonant's
sound is **derived from the niqqud** — dagesh and shin/sin dots decide it (בּ/ב→B/V, כּ/כ→K/X,
פּ/פ→P/F, שׁ/שׂ→SH/S). Homophones merge to one phoneme (ס+שׂ=S, ת+ט=T, כּ+ק=K, ח+כ=X, ב+ו=V,
א+ע=GLOTTAL). Matres lectionis / silent ו/י/ה are vowels and not targetable. The position
index is keyed by **phoneme, not letter**.

**Single source of truth.** `build_lexicon.py` owns the phoneme tables and the
(phoneme×position) feasibility matrix, and ships them in `lexicon.json` under `meta`. The
in-page JS reads them from `LEX.meta` — never hardcode phoneme/feasibility data in the
template. 54/60 cells are feasible; 6 are genuinely dead (B/P/H-last, V/F-first, Y-last) and
the picker disables them.

**Two engines that must agree.** `tools/test_lexicon.py` is the reference oracle: it
*independently* recomputes each word's phoneme index from the niqqud and asserts it matches
what `build_lexicon.py` baked in, then generates sentences for every cell and re-checks the
constraint. The sentence-generation engine inside `tools/template.html` (the shipped JS)
**mirrors** `test_lexicon.py`'s logic — keep the two in sync when changing generation rules.

**Sentence templates:** A/B are 3-word, C/D are 4-word; pre-stored inflected forms, no runtime
conjugation. Gender/number agreement is enforced.

## Hard constraints (decided with the user — don't re-litigate)

- **Python for all tooling.** The only JS is the game engine in `index.html`/`template.html`
  (browsers run only JS — not a violation of the preference).
- **Niqqud + genders are the release gate.** They're LLM-generated and LLM-verified = a strong
  draft only. Automated tests check *structure/agreement/constraint*, never niqqud correctness;
  native human review is required before release. The game displays and speaks the vocalized form.
- **Geresh loanwords are excluded** (ג׳/צ׳/ז׳ — foreign sounds outside the 20-phoneme model,
  and TTS can't voice them). Filtered in both `merge_lexicon.py` and `build_lexicon.py`.
- **TTS** is the Web Speech API (OS voices). macOS needs the Carmit Hebrew voice; the game is
  fully playable silent. No-voice detection must use `speechSynthesis.speaking/pending` — **not**
  `getVoices()` enumeration or the `onstart` event (both false-negative on Android Chrome).
  Letter tiles speak vocalized letter *names* (`NAMES` map in `template.html`) with baked-in
  voice quirks documented inline — read those comments before touching TTS.

- **SEO/social fields are plain (un-niqqud) Hebrew.** The game UI stays fully niqqud, but every
  machine-readable field — `<title>`, meta description, Open Graph/Twitter, the JSON-LD `@graph`
  (`WebApplication` + `WebSite` + `FAQPage`), the `sr-only` `<h1>`, and the collapsible
  `<details class="about">` explainer/FAQ — is un-vocalized, because Google tokenizes niqqud
  differently from how people actually type. The FAQ Q/A in that `<details>` must stay **byte-identical**
  to the `FAQPage` JSON-LD (mismatched FAQ schema is flagged as spam); it's hidden during the
  results/celebration flow via `body:has(#setup[hidden]) .about`. `sitemap.xml` + `og-image.png`
  ship at the repo root. **robots.txt can't live in this repo:** as a Pages *project* site
  (`/tslilon/`), crawlers only read robots.txt from the domain root, so it needs a separate
  `naftali-g.github.io` repo or a custom domain — otherwise default-allow applies (which is fine).

For the full record of design decisions, see the project memory note `letter-game-architecture`.
