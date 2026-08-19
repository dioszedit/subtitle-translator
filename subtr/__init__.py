"""subtr — a subtitle-translator belső Python-csomagja.

Ez a csomag fogja majd össze a repo eddig gyökérszintű, önálló szkriptjeit
közös rétegekbe: config (beállítások, modell-feloldás), srt (feliratfájl
be/kiolvasás), blocks (fordítási blokk-felosztás), context (sorozat- és
fordítási szabályzat betöltése), glossary (jóváhagyott terminológia),
reports (review/verify riportok), quota (API-kvóta nyilvántartás), valamint
a providers/ (Gemini, Claude, Codex integrációk) és tasks/ (fordítás,
review, glossary-építés, register-kinyerés) alcsomagok.

A gyökérben maradó scriptek (pl. translate_with_gemini.py, verify_srt.py)
a refaktor után vékony wrapperek lesznek: a tényleges logika ide, a subtr
csomagba költözik, a napi parancssori használat felülete változatlan marad.
"""
