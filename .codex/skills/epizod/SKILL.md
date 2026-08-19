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
| Verify | a `subtr.py verify` már lefutott a megfelelő forrással |
| Review | `_REVIEW_CLAUDE*`, `_REVIEW_GEMINI*` vagy `_REVIEW_CODEX*` riport létezik |
| Triage | ezt a felhasználó erősíti meg |
| Resegment | `*.reflow.srt` létezik, vagy külső szerkesztőben folytatják |

## Biztonságos végrehajtás

- Fordítás előtt ellenőrizd, hogy a `TRANSLATION.local.md` *Megszólítási regisztere* megvan-e és tartalmazza-e az előző epizód óta történt viszonyváltozásokat; hiány vagy elavulás esetén kérdezz rá. Utólag a tegezés/magázás csak kézzel egységesíthető. Kérésre a `py subtr.py register` felvázolhat egy első változatot az angol forrásból (opcionális, interaktív) — jóváhagyás nélkül ne futtasd.
- Új split csak `--clean`-nel törölhet régi blokkokat.
- Fordítóválasztáskor kérdezz rá, ha a felhasználó nem nevez meg providert: Claude (`py subtr.py translate --provider claude`), Gemini (`py subtr.py translate --provider gemini`) vagy Codex (`py subtr.py translate --provider codex`). A Codexet először `--agents 1`-gyel futtasd.
- A checkpoint miatt újrafuttatás csak a hiányzó blokkokat dolgozza fel. Egy konkrét blokk újrafordítását a `--block` kapcsolóval végezd.
- Merge-nél hiányzó blokk esetén ne használj `--force`-ot külön felhasználói kérés nélkül.
- Preclean után a `.clean.srt` legyen a `subtr.py verify` forrása.
- Nem angol forrásnál review-hoz kötelező a `--source` explicit megadása.
- A review-javaslatokat a `review-triage` skill szerint szűrd, és csak ezután futtasd a resegmentet.

A végén emlékeztesd a felhasználót a videóval való végső kézi ellenőrzésre.
