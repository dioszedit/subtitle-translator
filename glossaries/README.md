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

## Javaslat új sorozatnál (`index.json`)

Az `index.json` sorolja fel az alapokat és a `tmdb-init` javaslati szabályait
(`countries` ISO-kódok, `any_keywords` / `none_keywords` a TMDB-műfajokra és
-kulcsszavakra, részszó-egyezéssel). A sorrend számít: a közös réteg előbb, a
műfaji utána. Új alapfájl felvételekor az indexbe is be kell írni.

## Parancsok

- `py subtr.py bases list` — az alapok, darabszámmal, és a sorozat választása.
- `py subtr.py bases check` — a sorozat és az alapok ütközései, a kész
  fordításokkal összevetve (futó sorozathoz alap kapcsolása előtt).
- `py subtr.py bases promote "<en>" --to <id> --from <sorozat>/glossary.json` —
  sorozatból alapba emelés; a **repo gyökeréből** futtasd (a sorozat-mappák
  `glossaries/`-a csak másolat, a szinkron felülírja). `--context` új,
  általános megjegyzés, `--keep` a sorozatban is marad, `--dry-run` előnézet.

## Mi kerülhet ide

- Csak **sorozatfüggetlen**, több sorozaton bevált terminus: udvari rangok,
  hivatalok, megszólítások, művelési szintek, irodai beosztások.
- A `character_names` kategóriába **csak mitológiai és vallási alak** kerülhet
  (Jade Emperor, Buddha, Guanyin — lásd `zh-myth`), szereplőnév soha; ahol
  nincs ilyen, a kulcs el is hagyható.
- Hétköznapi jelentésben is gyakori angol szó ne kerüljön be (won, trial,
  stage, Director…): a promptba szűrés szóhatárral és — egyszavas nagybetűs
  címnél — kis/nagybetű-érzékenyen illeszt, de a köznévi jelentést nem tudja
  kiszűrni. Új bejegyzés előtt futtass `bases check`-et a kész részeken.
- Sorozatnév, szereplőnév, jogvédett szöveg **nem** — a repo nyilvános.
- A `context` általános: mire vonatkozik, és ha van, a forrás
  („hu.wikipedia: Kínai császár”), illetve hogy sorozatban felülírható.

A tervezés háttere: `proposals/alap_szotarak.md`.
