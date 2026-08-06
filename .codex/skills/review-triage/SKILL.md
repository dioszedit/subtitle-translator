---
name: review-triage
description: Review-javaslatok forrásalapú szűrése, decisions JSON összeállítása és biztonságos alkalmazása magyar SRT-re. Használd review-találatok átnézésére, javítására vagy automatikus átvezetésére.
---

# Review triage

Olvasd el a `TRANSLATION.md`-t és a `glossary.json`-t. A review-modellek javaslatai nem alkalmazhatók automatikusan: minden tételt az aktuális magyar SRT-hez és lehetőleg a forráshoz mérj.

## Bemenet és ellenőrzés

1. Keresd meg a megadott `hun.srt` melletti `_REVIEW_CLAUDE*`, `_REVIEW_GEMINI*` és `_REVIEW_CODEX*` `.json` riportokat. A JSON kanonikus; a `.txt` csak fallback.
2. Keresd meg a forrás SRT-t az `input/` mappában vagy kérd be. Forrás nélkül csak óvatos, nem automatikus triage végezhető.
3. A magyar SRT aktuális szövegét használd; a riport `eredeti` mezője elavulhatott.

## Döntési szabályok

- Ha a javaslat whitespace-normalizálva megegyezik a jelenlegi szöveggel: no-op, dobd el.
- Ha a riport `eredeti` mezője eltér az aktuálistól: kihagyás; valószínűleg már javított vagy elcsúszott.
- Glossary-val ellentétes, nem létező magyar szóalakú vagy a forrástól hűtlen javaslat: dobd el.
- Tegezés/magázás és stilisztika esetén kételykor dobd el.
- A jó, de pontatlan javaslatot írd át a végleges szövegre.
- Két provider azonos javaslata nagyobb bizalom, de nem helyettesíti a forrásellenőrzést.

## Alkalmazás

Készíts `<stem>_decisions.json` fájlt kizárólag elfogadott tételekkel:

```json
[{"sorszam": 12, "eredeti": "az aktuális magyar szöveg", "javaslat": "végleges magyar szöveg"}]
```

Előbb mindig futtasd:

```powershell
py apply_review_auto.py "<hun.srt>" "<decisions.json>" --dry-run
```

Mutasd meg az elfogadott, no-opként eldobott és hamisként eldobott tételek számát. Író futtatást csak felhasználói jóváhagyás után végezz. Eltérésnél ne használd az `--ignore-drift` kapcsolót; készíts új döntéslistát.
