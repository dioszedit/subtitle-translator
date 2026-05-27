"""Glossary kategória-lista — közös konstans több script között.

A `glossary.json` fix kategóriái, fix sorrendben. Új kategória esetén
ITT add hozzá egy helyen — minden olvasó script innen importál:
  - translate_parallel.py
  - review_with_claude.py
  - review_with_gemini.py
  - glossary_extract.py
"""

CATEGORIES = [
    "honorifics",
    "place_names",
    "character_names",
    "special_terms",
    "phrases",
]
