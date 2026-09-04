---
name: review-triage
description: Review-javaslatok forrásalapú szűrése, decisions JSON összeállítása és biztonságos alkalmazása magyar SRT-re. Használd review-találatok átnézésére, javítására vagy automatikus átvezetésére.
---

# Review triage

Olvasd el a `TRANSLATION.md`-t, a `TRANSLATION.local.md`-t (ebben van a *Megszólítási regiszter*: ki kit tegez vagy magáz) és a `glossary.json`-t. A review-modellek javaslatai nem alkalmazhatók automatikusan: minden tételt az aktuális magyar SRT-hez és lehetőleg a forráshoz mérj.

## Bemenet és ellenőrzés

1. Keresd meg a megadott `hun.srt` melletti `_REVIEW_CLAUDE*`, `_REVIEW_GEMINI*`, `_REVIEW_CODEX*` és `_REVIEW_GROK*` `.json` riportokat. A JSON kanonikus; a `.txt` csak fallback.
2. Keresd meg a forrás SRT-t az `input/` mappában vagy kérd be. Forrás nélkül csak óvatos, nem automatikus triage végezhető.
3. A magyar SRT aktuális szövegét használd; a riport `eredeti` mezője elavulhatott.

## Döntési szabályok

- Ha a javaslat whitespace-normalizálva megegyezik a jelenlegi szöveggel: no-op, dobd el.
- Ha a riport `eredeti` mezője eltér az aktuálistól: kihagyás; valószínűleg már javított vagy elcsúszott.
- Glossary-val ellentétes, nem létező magyar szóalakú vagy a forrástól hűtlen javaslat: dobd el.
- Tegezés/magázás: ha a *Megszólítási regiszter* alátámasztja a találatot, fogadd el; ha a `hiba` mező nem nevez meg regiszter-sort, forrás-jelet vagy ütköző sorszámot, dobd el. Egyéb esetben — és stilisztikánál — kételykor dobd el.
- A `hiba` hivatkozását is ellenőrizd, ne csak a javaslatot: ha regiszter-sorra vagy glossary-bejegyzésre hivatkozik, de az ott nincs úgy, dobd el. A regiszter `kivétel:` sorával ütköző találat is elesik — a jelölt kilépés szándékos.
- **Regiszter-találat = sweep-trigger, nem egysoros javítás.** A lektorok egy rendszerszintű regiszterhibának csak a töredékét jelzik, és a félig átállított jelenet rosszabb, mint bármelyik véglet. Elfogadott regiszter-találat után nézd végig az adott karakterpár összes sorát a jelenetben; a riporton kívül felvett tételeket az összegzésben külön jelöld, hogy a felhasználó vétózhasson.
- Regiszter-ügyben előbb tisztázd, **ki beszél kihez** — a leggyakoribb néma hiba a téves beszélő-hozzárendelés, mert az eredménye konzisztensnek látszik. Ha a videó visz eredeti nyelvű feliratsávot (`addons/mkv-subs`), annak beszélőcímkéi és formalitás-alakjai egy lépésben eldöntik mindkettőt.
- A jó, de pontatlan javaslatot írd át a végleges szövegre.
- Két provider azonos javaslata nagyobb bizalom, de nem helyettesíti a forrásellenőrzést.

## Alkalmazás

Készíts `<stem>_decisions.json` fájlt kizárólag elfogadott tételekkel:

```json
[{"sorszam": 12, "eredeti": "az aktuális magyar szöveg", "javaslat": "végleges magyar szöveg"}]
```

Előbb mindig futtasd:

```powershell
py subtr.py apply-auto "<hun.srt>" "<decisions.json>" --dry-run
```

Mutasd meg az elfogadott, no-opként eldobott és hamisként eldobott tételek számát. Író futtatást csak felhasználói jóváhagyás után végezz. Eltérésnél ne használd az `--ignore-drift` kapcsolót; készíts új döntéslistát.
