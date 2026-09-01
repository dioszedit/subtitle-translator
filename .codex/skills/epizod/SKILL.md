---
name: epizod
description: Egy feliratepizód fordítási folyamatának állapotfelismerése és biztonságos folytatása. Használd, amikor a felhasználó epizód fordítását, folytatását vagy a következő pipeline-lépést kéri.
---

# Epizód pipeline

Az utasítások forrása a `steps.txt`; a fordítási szabályzat a `TRANSLATION.md`. Először fájlokból állapítsd meg az állapotot, és még futtatás előtt mondd meg röviden a következő lépést.

| Lépés | Kész, ha |
|---|---|
| Preclean | `input/<X>.<lang>.clean.srt` létezik; innentől ezt használd forrásnak (a blokkok `input/blocks/<X>.<lang>/` alatt is lehetnek) |
| Split | `blocks/<X>.<lang>/` és benne inputblokkok léteznek (`<lang>` = a forrás nyelvkódja: `eng`, `ger`, …) |
| Fordítás | minden inputblokkhoz van `_HUN.srt` |
| Merge | `output/<X>.hun.srt` létezik |
| Verify | a `subtr.py verify` már lefutott a megfelelő forrással |
| Review | `_REVIEW_CLAUDE*`, `_REVIEW_GEMINI*`, `_REVIEW_CODEX*` vagy `_REVIEW_GROK*` riport létezik |
| Triage | ezt a felhasználó erősíti meg |
| Resegment | `*.reflow.srt` létezik, vagy külső szerkesztőben folytatják |

## Biztonságos végrehajtás

- Fordítás előtt ellenőrizd, hogy a `TRANSLATION.local.md` *Megszólítási regisztere* megvan-e és tartalmazza-e az előző epizód óta történt viszonyváltozásokat; hiány vagy elavulás esetén kérdezz rá. Utólag a tegezés/magázás csak kézzel egységesíthető. Kérésre a `py subtr.py register` felvázolhat egy első változatot az angol forrásból (opcionális, interaktív) — jóváhagyás nélkül ne futtasd.
- Új split csak `--clean`-nel törölhet régi blokkokat.
- Fordítóválasztáskor kérdezz rá, ha a felhasználó nem nevez meg providert: Claude (`py subtr.py translate --provider claude`), Gemini (`py subtr.py translate --provider gemini`), Codex (`py subtr.py translate --provider codex`) vagy Grok (`py subtr.py translate --provider grok`). A Codexet és a Grokot először `--agents 1`-gyel futtasd. A Grok default modellje fordításnál `grok-4.5`, review-nál `grok-4.6`.
- A checkpoint miatt újrafuttatás csak a hiányzó blokkokat dolgozza fel. Egy konkrét blokk újrafordítását a `--block` kapcsolóval végezd.
- Merge-nél hiányzó blokk esetén ne használj `--force`-ot külön felhasználói kérés nélkül.
- Preclean után a `.clean.srt` legyen a `subtr.py verify` forrása.
- A forrásnyelvet a fájlnév `.kód` tagjából minden lépés felismeri; `--source-lang` csak akkor kell, ha a név nem árulkodik (pl. a `.clean.srt` splittelésekor). A review a forrás SRT-t magától megtalálja; `--source` csak nem konvenció szerinti fájlnévnél kell.
- A review-javaslatokat a `review-triage` skill szerint szűrd, és csak ezután futtasd a resegmentet.

A végén emlékeztesd a felhasználót a videóval való végső kézi ellenőrzésre.
