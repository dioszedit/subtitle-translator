---
name: epizod
description: Egy feliratepizód fordítási folyamatának állapotfelismerése és biztonságos folytatása. Használd, amikor a felhasználó epizód fordítását, folytatását vagy a következő pipeline-lépést kéri.
---

# Epizód pipeline

Az utasítások forrása a `lepesek.txt`; a fordítási szabályzat a `TRANSLATION.md`. Először fájlokból állapítsd meg az állapotot, és még futtatás előtt mondd meg röviden a következő lépést.

| Lépés | Kész, ha |
|---|---|
| Preclean | `input/<X>.eng.clean.srt` létezik; innentől ezt használd forrásnak |
| Split | `blocks/<X>.eng/` és benne inputblokkok léteznek |
| Fordítás | minden inputblokkhoz van `_HUN.srt` |
| Merge | `output/<X>.hun.srt` létezik |
| Verify | a `verify_srt.py` már lefutott a megfelelő forrással |
| Review | `_REVIEW_CLAUDE*`, `_REVIEW_GEMINI*` vagy `_REVIEW_CODEX*` riport létezik |
| Triage | ezt a felhasználó erősíti meg |
| Resegment | `*.reflow.srt` létezik, vagy külső szerkesztőben folytatják |

## Biztonságos végrehajtás

- Új split csak `--clean`-nel törölhet régi blokkokat.
- Fordítóválasztáskor kérdezz rá, ha a felhasználó nem nevez meg providert: Claude (`translate_parallel.py`), Gemini (`translate_with_gemini.py`) vagy Codex (`translate_with_codex.py`). A Codexet először `--agents 1`-gyel futtasd.
- A checkpoint miatt újrafuttatás csak a hiányzó blokkokat dolgozza fel. Egy konkrét blokk újrafordítását a `--block` kapcsolóval végezd.
- Merge-nél hiányzó blokk esetén ne használj `--force`-ot külön felhasználói kérés nélkül.
- Preclean után a `.clean.srt` legyen a `verify_srt.py` forrása.
- Nem angol forrásnál review-hoz kötelező a `--source` explicit megadása.
- A review-javaslatokat a `review-triage` skill szerint szűrd, és csak ezután futtasd a resegmentet.

A végén emlékeztesd a felhasználót a videóval való végső kézi ellenőrzésre.
