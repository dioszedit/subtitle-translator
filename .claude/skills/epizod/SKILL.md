---
name: epizod
description: Egy epizód fordítási folyamatának végigvitele vagy folytatása — a fájlokból felismeri, hol tart a pipeline (split → translate → merge → verify → review → triage), és onnan viszi tovább a lepesek.txt szerint. Akkor használd, ha a felhasználó egy epizód fordítását kéri, vagy azt kérdezi, hol tart / mi a következő lépés.
argument-hint: <epizód input SRT vagy név, pl. "Sorozat - S01E01">
---

# Epizód-pipeline — állapotfelismerés és végigvitel

A pipeline minden lépése fájl-alapú checkpointtal dolgozik, ezért a "hol
tartok?" kérdés a fájlrendszerből megválaszolható — SOHA ne futtass újra kész
lépést. A parancsok kanonikus forrása a **lepesek.txt** (Windows: `py` launcher,
backslash útvonalak) — a pontos kapcsolókat onnan vedd, ne fejből.

## 1. Állapot-felismerés

Az epizód azonosítójából (pl. `Sorozat - S01E01`) sorban ellenőrizd:

| Lépés | Kész, ha… |
|---|---|
| 0. preclean (opcionális) | `input/<X>.eng.clean.srt` létezik — akkor INNENTŐL ez a forrás |
| 1. split | `blocks/<X>.eng/` létezik és vannak benne blokkok |
| 2. translate | MINDEN `<X>_block_NNN_*.srt`-hez van `*_HUN.srt` párja |
| 3. merge | `output/<X>.hun.srt` létezik |
| 4. verify | le kell futtatni (olcsó, mindig futtatható) |
| 5. review | `output/<X>.hun_REVIEW_CLAUDE*` vagy `_REVIEW_GEMINI*` létezik |
| 5c/5d. triage | a review-javítások átvezetve (ezt a felhasználótól kérdezd, fájlból nem látszik) |
| 7. resegment | `*.reflow.srt` létezik, vagy a felhasználó Subtitle Editben folytatja |

Írd ki tömören, mi kész és mi a következő lépés, MIELŐTT bármit futtatnál.

## 2. Lépések futtatása — a csapdákkal együtt

- **Split**: ha a `blocks/<X>.eng/` már létezik és újra-split kell (más
  `--block-size`), CSAK `--clean`-nel — enélkül a script szándékosan leáll.
- **Regiszter-ellenőrzés (translate ELŐTT)**: nézd meg, van-e `Megszólítási
  regiszter` a `TRANSLATION.local.md`-ben, és tartalmazza-e az előző epizód óta
  történt viszonyváltozásokat (tegeződésre váltás, előléptetés, új szereplő). Ha
  hiányzik vagy elavultnak tűnik, kérdezz rá a felhasználónál, MIELŐTT fordítasz —
  a blokkok párhuzamosan fordulnak, utólag a formát csak kézzel lehet egységesíteni.
  Egy téves regiszter-sor rosszabb, mint a hiányzó: magabiztosan rossz formát
  kényszerít, míg hiány esetén a fordító a kikerülő megfogalmazást választja.
  Ha a felhasználó kéri, a `py subtr.py register` felvázolhat egy első változatot
  az angol forrásból (opcionális, interaktív; több epizód pontosabb) — de a
  jóváhagyás mindig a felhasználóé, ne futtasd rákérdezés nélkül.
- **Translate**: kérdezd meg (ha nem mondta), melyik fordítóval:
  `py subtr.py translate --provider claude` vagy `--provider gemini` (olcsóbb).
  Gemini-nél a parancs indulásakor kvóta-preflight fut — ha azt írja, a modell
  kimerült vagy nem fér bele, javasolj modellváltást (`--model`) vagy Claude-ot;
  állást a `py subtr.py quota` mutat. Újrafuttatás biztonságos: csak a hiányzó
  blokkokat fordítja.
- **Merge**: hiányzó blokknál a parancs leáll és listáz — ilyenkor a translate-et
  kell újrafuttatni; `--force`-ot csak a felhasználó kifejezett kérésére.
- **Verify**: ha volt preclean, az összevetés a `.clean.srt` ELLEN fut, nem az
  eredeti `.eng.srt` ellen (az addon újraszámoz, hamis hibákat jelezne).
- **Review**: a review három providere független, futhat az egyik vagy több is.
  NEM ANGOL forrásnál a `--source "<forrás srt>"` kézi megadása kötelező
  (az automatikus keresés csak `.eng.srt`-t talál meg).
- **Review-javítások átvezetése**: add át a **review-triage** skillnek
  (`/review-triage "<output/X.hun.srt>"`) — ott van a szűrési eljárás.
- **Resegment**: CSAK a review-javítások átvezetése UTÁN (`--split` újraszámoz,
  utána a riportok sorszámai elavulnak).

## 3. Lezárás

A pipeline vége után emlékeztesd a felhasználót az utómunkára (README "Utómunka"
szakasz): Subtitle Edit (CPS/időzítés) + végső kézi lektorálás a videóval.
