"""subtr — a subtitle-translator belső Python-csomagja.

Ez a csomag fogja össze a fordítási pipeline-t közös rétegekbe: config (beállítások, modell-feloldás), srt (feliratfájl
be/kiolvasás), blocks (fordítási blokk-felosztás), context (sorozat- és
fordítási szabályzat betöltése), glossary (jóváhagyott terminológia),
reports (review/verify riportok), quota (API-kvóta nyilvántartás), valamint
a providers/ (Gemini, Claude, Codex integrációk) és tasks/ (fordítás,
review, glossary-építés, register-kinyerés) alcsomagok.

A parancssori belépési pont a gyökér `subtr.py` (vagy a telepített `subtr`
parancs / `python -m subtr`): mindegyik a subtr.cli:main-t hívja.
"""
