# Deep review ötletek — nyitott tételek (v2)

> Előzmény: [archive/deep_review_otletek_v1.md](archive/deep_review_otletek_v1.md)
> (a 2026-07-13-i deep review ötletei). A v1-ből azóta megvalósult:
> **#1 közös modul** → a teljes `subtr/` csomag-refaktor (2026-08-19,
> messze túl is ment az eredeti ötleten), és részben a **#4 egyparancsos
> pipeline** → a `subtr.py` CLI (a lépések egy parancs alparancsai, de az
> automatikus végigvivő orchestrator nem készült el). Az alábbi tételek
> maradtak nyitva, a mai (subtr-es) világra igazítva.

---

## 1. Review resume / inkrementális riportírás (v1 #3)

A `subtr.py review` chunkonként azonnal írja a találatokat (`.partial`
sidecar), és újrafutáskor a kész chunkokat kihagyja — ahogy a translate
fájl-alapú checkpointtal fut. Ma egy megszakadt review minden addigi
találatot elveszít, a pótlás kézi `--start-chunk`/`--suffix` tánc.
A megvalósítás helye: `subtr/tasks/review.py` közös chunk-ciklusa —
a refaktor után EGY helyen kell megírni, mindhárom provider örökli.
**Méret: S** (a refaktor előtt S–M volt).

## 2. Glossary-konzisztencia ellenőrzés a verify-ban (v1 #2)

A `subtr.py verify` (vagy külön check) jelezze, ha az angol forrásban
szerepel egy glossary `en` terminus, de a magyarban nem az előírt `hu`
fordítás áll. Determinisztikus, API-költség nélküli minőség-kapu; a
párosító kód (`subtr.tasks.review.check_source_alignment` + `subtr.srt`)
és a `subtr.glossary.load()` készen áll. Ragozott alakokra prefix-egyezés
+ figyelmeztetés-szint. **Méret: S.**

## 3. Auto-orchestrator: `subtr.py run` (v1 #4 maradéka)

Egy alparancs, ami a teljes menetet végigviszi (split → translate →
merge → verify → review), fájl-alapú skip-logikával (ha az artefaktum
létezik és frissebb az inputjánál, a lépés kimarad), `--from`/`--until`
rész-futtatással. A `subtr.tasks.*` main(argv) hívások miatt ez ma már
tiszta belső hívás-sorozat, nem subprocess-lánc. **Méret: S–M.**

## 4. Költség-kimutatás epizódonként (v1 #5)

A Gemini `usage_metadata` token-számaiból és a `claude -p --output-format
json` költség-mezőjéből epizódonkénti összesítés (`costs.log`).
A `subtr/quota.py` hívás-könyvelése részben fedi (kérésszám), a
token/költség-dimenzió hiányzik. A gyűjtés természetes helye a
`subtr/providers/` adapterek. **Méret: S–M.**

## 5. Desktop GUI — újratervezendő alapokon

A [archive/desktop_gui_v1.md](archive/desktop_gui_v1.md) a régi (törölt)
gyökér-scriptek subprocess-hívására épült. Ha a GUI-irány újra előkerül,
az alapja az importálható `subtr.tasks` API és a `subtr.cli` legyen —
egy v2 tervezési kör kell hozzá, a v1-ből a képernyőtervek és a
projekt-állapot koncepció újrahasznosítható.

---

## Javasolt sorrend

1. **#1 review resume** — napi bosszúság-spórolás, kis munka.
2. **#2 glossary-check** — ingyen minőség-kapu.
3. **#3 subtr run** — kényelem + egy jövőbeli GUI előfeltétele.
4. **#4 költség-log** — bármikor, független.
5. **#5 GUI** — csak a #3 után érdemes.
