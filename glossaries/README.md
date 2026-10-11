# Alap-szótárak (műfaj × kultúra)

Újrahasznosítható szójegyzékek, amelyeket a sorozat `glossary.json`-ja a
`meta.bases` listában választ ki; a pipeline **futáskor** fésüli össze őket a
sorozat saját bejegyzéseivel (fordítás, review, glossary-kinyerés).

```json
{"meta": {"series": "…", "bases": ["zh-common", "zh-historical"]}, "honorifics": [], …}
```

## Szabályok

- **Séma:** ugyanaz, mint a `glossary.json`-é (`honorifics`, `place_names`,
  `character_names`, `special_terms`, `phrases`; bejegyzésenként `en`, `hu`,
  `context`), plusz `meta`: `id`, `title`, `lang`, `description`, `version`.
- **Fájlnév = azonosító:** `<nyelv>-<műfaj>.json`, csak kisbetű, szám, kötőjel
  (pl. `zh-historical`, `ko-modern`).
- **Elsőbbség:** a sorozat saját bejegyzése > később felsorolt alap > korábbi
  alap, az `en` alak szerint. Ha egy sorozatban mást kell használni, elég a
  sorozat `glossary.json`-jába felvenni — az alapot nem kell módosítani.
- **Promptba csak előfordulás esetén** kerül egy alap-bejegyzés, minden
  kategóriában (a sorozat saját nevei és megszólításai továbbra is mindig).
- A `subtr.py glossary` az alap terminusait nem javasolja újra, és a sorozat
  fájljába soha nem írja vissza őket.
- Hiányzó vagy hibás alapfájl → figyelmeztetés, a futás folytatódik.

## Mi kerülhet ide

- Csak **sorozatfüggetlen**, több sorozaton bevált terminus: udvari rangok,
  hivatalok, megszólítások, művelési szintek, irodai beosztások.
- Sorozatnév, szereplőnév, jogvédett szöveg **nem** — a repo nyilvános.
- A `context` általános: mire vonatkozik, és ha van, a forrás
  („hu.wikipedia: Kínai császár”), illetve hogy sorozatban felülírható.

A tervezés háttere: `proposals/alap_szotarak.md`.
