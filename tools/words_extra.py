# -*- coding: utf-8 -*-
"""
Hand-curated, vocalized gap-fill words, merged AFTER the generated lexicon
(generated entries win on key conflicts; these only fill empty cells).

Currently target the two cells the generator left thin once vocalized:
  ז-last  (need a present verb ending in ז)
  כ-last  (need a masc noun + adj ending in ך)
"""

EXTRA_NOUNS = [
    ("מֶלֶךְ", "m", "sg"),    # king        -> כ/ך last
    ("חֹשֶׁךְ", "m", "sg"),   # darkness    -> כ/ך last
    ("דֶּרֶךְ", "f", "sg"),   # way/road    -> כ/ך last
    ("שִׁיר", "m", "sg"),     # song (common everyday word)
]

EXTRA_ADJECTIVES = [
    ("אָרֹךְ", "אֲרֻכָּה", "אֲרֻכִּים", "אֲרֻכּוֹת"),   # long -> ms ends ך
]

EXTRA_VERBS = [
    ("אוֹחֵז", "אוֹחֶזֶת", "אוֹחֲזִים", "אוֹחֲזוֹת", True),   # holds -> ז last
]
