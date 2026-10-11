# Alap-szótárak (műfaj × kultúra) — terv

Állapot: **1–2. fázis kész** — mechanizmus (`subtr/glossary.py` `with_bases()`) és
`tmdb-init`-javaslat (`glossaries/index.json`, `--base`). A 3–5. fázis hátravan.

## Cél

A sorozat-glossaryk jelentős része sorozatfüggetlen: megszólítások, udvari rangok,
hivatalok, művelési szintek, irodai beosztások. Ma minden új sorozat a nulláról
indul, és ugyanaz a terminus sorozatonként — sőt egy részen belül is — eltérően
fordul (mért eset: „Marquis” egy részen belül „márki” és „őrgróf” vegyesen,
üres glossary mellett).

Megoldás: újrahasznosítható **alap-szótárak** egy külön mappában, amelyeket a
sorozat `glossary.json`-ja hivatkozással választ ki, és a pipeline **futáskor
fésül össze** a sorozat saját bejegyzéseivel.

## Döntések (a felhasználóval egyeztetve)

- **Futáskori összefésülés**, nem induláskori bemásolás — az alap javítása minden
  sorozatba eljut (a szokásos kód-szinkronnal), a sorozat felülírhat, és
  látható marad, mi sorozatspecifikus.
- **Kultúra × műfaj** bontás, nem csak műfaj: a „historical” kínaiul és
  koreaiul mást jelent.

## Felépítés

### Fájlok

```
glossaries/
├── index.json          ← manifest: azonosító, cím, nyelv, leírás, javaslati szabályok
├── zh-common.json      ← kínai megszólítások, rokoni/társasági formák
├── zh-historical.json  ← udvari rangok, nemesi címek, hivatalok, intézmények
├── zh-xianxia.json     ← művelés, szekták, szintek, kincsek
├── zh-wuxia.json       ← jianghu, harcművészeti terminusok (később)
├── ko-common.json      ← koreai megszólítások (oppa, unni, sunbae…)
├── ko-modern.json      ← irodai beosztások, chaebol, iskola
└── ko-sageuk.json      ← Joseon-kori rangok (később)
```

Séma = a `glossary.json` sémája (ugyanaz az öt kategória), plusz `meta`:
`{"id", "title", "lang", "description", "version"}`. A `context` mező itt
általános („kínai udvari nemesi cím; sorozatban felülírható”), sorozatnév
nélkül — a repo nyilvános.

### Hivatkozás a sorozatból

```json
{"meta": {"series": "…", "bases": ["zh-common", "zh-historical"]}, "honorifics": [...], ...}
```

Hiányzó `bases` = mai viselkedés (visszafelé kompatibilis). Ismeretlen
azonosító → figyelmeztetés, nem hiba.

### Összefésülés (`subtr/glossary.py`)

- `load()` a projekt-glossaryt és a `meta.bases` alapjait együtt adja vissza;
  minden bejegyzés belső `_source` jelölést kap (`project` / `base:<id>`).
- **Elsőbbség:** projekt > később felsorolt alap > korábbi alap, az `en` kulcs
  (kisbetűs, normalizált) szerint. Ütközésnél a gyengébb kiesik; a futás
  összegzősora jelzi a darabszámot.
- **Szűrés:** ma az `IDENTITY_CATEGORIES` (honorifics, place_names,
  character_names) mindig teljes egészében a promptba kerül. Ez az alapokra
  NEM érvényes: az alap-bejegyzések minden kategóriában csak akkor kerülnek be,
  ha a szövegben előfordulnak — különben egy 100+ megszólításos alap minden
  hívást felfújna. A projekt saját azonosítói változatlanul mindig bekerülnek.
- A promptba kerülő sorformátum változatlan (`"en" = "hu" (context)`).

### Érintett pontok

| Hely | Változás |
|---|---|
| `subtr/config.py` | `GLOSSARIES_DIR = "glossaries"` (CWD-relatív, mint a `GLOSSARY_PATH`) |
| `subtr/glossary.py` | `load_bases()`, összefésülés, `_source`, alap-szűrés |
| `subtr/tasks/translate.py`, `review.py` | csak az összegzősor bővül (`projekt N + alap M (zh-common, …)`) |
| `subtr/tasks/glossary_extract.py` | az alapok terminusai is „meglévőnek” számítanak (nem javasolja újra), a prompt látja őket; **mentéskor csak a projekt-bejegyzések íródnak vissza** — az alap soha nem kerül a sorozat fájljába |
| `addons/tmdb-init/init_local.py` | alap-javaslat az ország + TMDB-műfaj/kulcsszó alapján (`index.json` szabályai), `--base` felülírás, beírás a `meta.bases`-be; `--glossary-only` már futó sorozatnál |
| `.claude/…/review-triage` (+ `.agents`, `.codex`, `.grok`) | „a glossary” = projekt + alapok |
| README, `steps.txt` 0/a | új szakasz: alapok, választás, felülírás |
| kód-szinkron | a `glossaries/` mappa is átmegy a sorozat-mappákba |

### Javaslati szabályok (`index.json`)

Példa: `{"id": "zh-historical", "country": ["CN","TW","HK"], "any_keyword":
["costume drama","historical","imperial court","palace"]}`. A `tmdb-init`
kiírja a javaslatot és az indoklást; a végső szó a felhasználóé (`--base`).

## Tartalom: honnan töltjük fel

1. **Meglévő sorozat-glossaryk** (a korábban fordított sorozatokéi): egy xianxia
   sorozat (123 megszólítás / 410 terminus), több kínai történelmi és modern,
   valamint koreai modern dráma. Kigyűjtjük a sorozatfüggetlen bejegyzéseket;
   ahol két sorozat eltérően fordít, megjelöljük, és a felhasználó dönt.
2. **Külső források** — lásd *Kutatás* (csak referencia; adatot csak
   kompatibilis licencnél veszünk át).
3. Minden tervezet **a felhasználó átnézése után** kerül a repóba.

Első kör: `zh-common`, `zh-historical`, `zh-xianxia`, `ko-common`, `ko-modern`.

## Ütemezés

1. **Mechanizmus** — összefésülés, szűrés, glossary_extract-tudatosság,
   összegzősor, tesztek (elsőbbség, alap-szűrés, hiányzó alapfájl, a kinyerő
   nem ír vissza alapot), dokumentáció. Üres példa-alappal tesztelhető.
2. **tmdb-init** — `index.json`, javaslat, `--base`.
3. **Tartalom** — tervezetek a meglévő glossarykból, átnézés, commit.
4. **Átállás** — a futó sorozatok `meta.bases`-e; jelentés a sorozat-glossary
   azon bejegyzéseiről, amelyek szó szerint egyeznek az alappal (törlésük
   opcionális, külön jóváhagyással).
5. **Később** — `subtr.py glossary promote "<en>" --to <alap>`: sorozatból
   alapba emelés egy paranccsal; `zh-wuxia`, `ko-sageuk`.

## Kockázatok

- **Egy rossz alap-bejegyzés minden sorozatot ront** → csak több sorozaton
  bevált terminus kerül az alapba; a projekt mindig felülírhat.
- **Kontextusfüggő terminusok** (pl. „Prince” = herceg / királyfi) → az alapba
  csak egyértelmű alapértelmezés; a többi `context` megjegyzéssel vagy sehogy.
- **Nyilvános repo** → csak általános terminus, sorozatnév és jogvédett szöveg
  nélkül.

## Kutatás (2026-10)

**Fő megállapítás:** szabad licencű, géppel olvasható zh/ko → magyar termbázis
nincs. A tartalmat magunknak kell összeállítanunk, saját (MIT) licenc alatt; a
terminus-megfeleltetések tényadatok, a forrás a `context` mezőben jelölhető.

| Forrás | Mire jó | Licenc → felhasználás |
|---|---|---|
| hu.wikipedia: *Címek és megszólítások a Csoszon-dinasztiában*, *Csoszon* | `ko-sageuk` váza: királyi család, ágyasrangok, eunuchok, a hat minisztérium | CC BY-SA → csak referencia (a cikk magyar népszerű átírást használ; nálunk a nevek RR-alakban maradnak) |
| hu.wikipedia: *Kínai császár*, *Mindennapi élet Kínában a Ming-dinasztia idején*, *Őrgróf* | `zh-historical`: hárem, udvar, minisztériumok, Cenzori Hivatal; a 侯 „általában a márkival azonosítják” | CC BY-SA → referencia |
| Csongor–Ferenczy: *A kínai nevek és szavak magyar átírása* (1993) | hogy a modell ne keverje a magyaros átírást a pinyinnel | © → referencia |
| Wuxiaworld General Glossary, Hucker: *Dictionary of Official Titles in Imperial China* | az angol forrásalakok azonosítása (xianxia, hivatali címek) | © → csak referencia, scrapelni tilos |
| en.wikipedia (Qing-rangok, Chinese nobility, Joseon styles…) | a szokásos angol alakok | CC BY-SA → referencia |
| **Wikidata** | kínai címek/intézmények, néhol magyar címkével | **CC0 → átvehető** (gyenge magyar lefedettség) |
| CC-CEDICT | zh → en szótár | CC BY-SA → nem keverhető az MIT-repóba |
| MyDramaList | — | ToS tiltja → kihagyva |

Magyar fansub-stílusútmutatót, magyar wuxia/xianxia-kiadást és a koreai
megszólítások (oppa, unni, sunbae) magyar feliratbeli kezelésére vonatkozó
elsődleges forrást nem találtunk — ezekben a saját sorozat-glossaryink a
legjobb forrás.

### Mély kutatás: magyar fordítói hagyomány (2026-10)

Egyik forrás sem nyílt licencű — **egyedi terminuspárokat** (tényeket) veszünk
át, szöveget/táblázatot nem.

| Forrás | Haszon |
|---|---|
| Csongor Barnabás fordításai: *Vízparti történet* (Európa 1977), *Nyugati utazás* I. (1980), *Klasszikus kínai költők* jegyzetei — Terebess Online | wuxia (jianghu) és udvari terminusok; daoista/halhatatlansági alapszavak |
| *A tigris intelme. Koreai elbeszélések* (MEK-05090, Osváth Gábor és mások) | sageuk: jangban, kiszeng, királyi inspektor |
| Terebess: *A palota ékköve* epizódleírásai | a magyar tévés sugárzás (M1, 2008) szóhasználata |
| hu.wikipedia: *Vu-hszia*, *Ming-dinasztia*, *Csoszon*, *A palota ékköve* | műfajnevek, minisztériumok, koreai udvar |
| *The Untamed – A démoni kultiváció nagymestere* (magyar kiadás, 2020–) | egyetlen magyar xianxia-kiadás: „kultiváció”, „kultivátor” |
| LanGeek „Film Genres” és rokon szólisták | gépi minőségű magyar oszlop (pl. thriller = „akciófilm”), nincs wuxia/xianxia/sageuk; „All Rights Reserved” → legfeljebb ellenőrzésre |
| „Filmműfajok és kritika” C1-es lecke | **nem található** |

Forrásban talált, a tervezetekhez felhasználható alakok (válogatás):

| EN | HU | Forrás |
|---|---|---|
| Emperor / Son of Heaven | császár / Ég Fia | Vízparti történet, hu.wiki |
| Empress / Empress Dowager | császárné / anyacsászárné | hu.wiki *Kínai császár* |
| Noble Consort / Concubine | nemes hitves / ágyas | hu.wiki; Vízparti történet |
| Crown Prince / Prince / Princess | trónörökös / herceg / hercegnő | hu.wiki; Vízparti történet |
| Eunuch / Chamberlain | eunuch / udvarnagy | Vízparti történet |
| Censorate | Cenzori Hivatal | hu.wiki Ming |
| County magistrate / Prefect / Governor | körzeti elöljáró / prefektusi bíró / kormányzó | hu.wiki Ming; Vízparti történet |
| Imperial Guard | császári gárda / palotatestőrség | Vízparti történet |
| jianghu / hero (好漢) / sworn brother | a folyók és tavak népe / vitéz / esküdt testvér | Vízparti történet |
| immortal / disciple / elixir / Jade Emperor | halhatatlan / tanítvány / életelixír / Jáde Császár | Nyugati utazás |
| dantian / the Dao | cinóber mező / a Tan | Nyugati utazás |
| cultivation / cultivator | kultiváció / kultivátor | *The Untamed* (HU) |
| Jeonha / Daegam | őfelsége / őméltósága | Terebess *Palota ékköve*; hu.wiki Csoszon |
| Sanggung / Nain / Naesi | udvarhölgy / udvarhölgy-növendék / eunuch | Terebess; hu.wiki Csoszon |
| Daegun / Gongju | nagyherceg / hercegnő | hu.wiki Csoszon |
| yangban / kisaeng | jangban / kiszeng | *A tigris intelme* |

**Eltérő alakok — a tervezet átnézésekor döntendő:**

- 丞相 (Chancellor / Prime Minister): **kancellár** (Vízparti történet, hu.wiki Ming, *A tigris intelme*) vagy **főminiszter** (hu.wiki Ming, Terebess, hu.wiki Csoszon)
- Empress: császárné vagy császárnő
- Queen Dowager: özvegy királyné, anyakirálynő vagy felséges asszony
- Daegun: nagyherceg vagy főherceg
- Prince: herceg vagy (koreai kontextusban) királyfi
- Marquis (侯): a Csongor-jegyzet „főnemes”, a hu.wiki „márki”; Duke / Count kínai kontextusban magyar forrásban nem szerepel

**Forrásban nem található** (ezeket a saját sorozat-glossaryinkból kell
rögzíteni): qi, neigong, qinggong, Foundation Establishment, Golden Core,
Nascent Soul, sect, elder, martial uncle, shixiong; Ming-kori háremrangok,
Grand Secretary, Hanlin; Team Leader, Director, Chairman, chaebol; az
oppa / unni / hyung / sunbae bevett magyar megfelelője (a gyakorlat: koreai
alak marad).

**Átírás:** a régebbi magyar fordítások magyaros átírást használnak (Szun
Vu-kung, Csin Jong); a pipeline a nevekben a felirat latin átírását (pinyin,
RR) tartja meg — az alap-szótárak `hu` mezője is ezt követi, a magyaros alak
legfeljebb a `context`-be kerül.

Ebből következő pontosítások a tervben:

- **Egységes alakot nekünk kell választani** ott, ahol a források eltérnek —
  pl. a hat minisztérium neve a két hu.wiki-cikkben más („Szertartásügyek M.” /
  „Szertartásügyi M.”), a „Prime Minister / Chancellor” (丞相) magyar alakjára
  nincs forrás („kancellár” kézenfekvő, de igazolatlan). Ezek a tervezet
  átnézésekor döntendő tételek.
- A **„Marquis” = „márki”** választást a hu.wiki is alátámasztja (a 侯-t
  általában a márkival azonosítják) — ez lesz a `zh-historical` alapértelmezése.
- **Kultivációs terminusokra** magyar forrás nincs → a `zh-xianxia` alapja egy korábban
  fordított xianxia sorozat glossaryja.
- Bevált gyakorlat az LLM-termekinjektálásban: csak a szegmensben előforduló
  terminusok kerüljenek be (nálunk ez az alap-szűrés), és a „nem fordítandó”
  terminusok legyenek külön jelölve. Nálunk ma az `en == hu` jelzi ezt
  (sorozatcímek); egy explicit jelző (`"keep": true`) később felvehető, ha a
  modellek félreértik.
