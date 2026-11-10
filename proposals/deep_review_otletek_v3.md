# Nyitott fejlesztési ötletek (v3)

> Előzmény: [archive/deep_review_otletek_v2.md](archive/deep_review_otletek_v2.md).
> A v2-höz képest (2026-11):
> - **kikerült** a `subtr.py run` végigvivő parancs — a teljes menetet a gyakorlatban
>   az `epizod` skill viszi végig, a fájlokból felismerve, hol tart a pipeline;
> - **bekerültek** az alap-szótárak nyitva maradt tételei (a megvalósult terv:
>   [archive/alap_szotarak.md](archive/alap_szotarak.md));
> - a hivatkozások a mai kódhoz igazodnak (öt provider, alap-szótárak,
>   funkciónkénti provider / modell / effort a `subtr/defaults.env`-ből).

---

## 1. Review folytatása megszakadás után

A `subtr.py review` chunkonként azonnal írja a találatokat (`.partial`
sidecar), és újrafutáskor a kész chunkokat kihagyja — ahogy a translate
fájl-alapú checkpointtal fut. Ma egy megszakadt review minden addigi
találatot elveszít, a pótlás kézi `--start-chunk` / `--end-chunk` / `--suffix`
művelet. A megvalósítás helye a `subtr/tasks/review.py` közös chunk-ciklusa:
egy helyen kell megírni, mind az öt provider örökli. Az Antigravity-ágon egy
rész review-ja 20 perc körül is lehet, ott a legnagyobb a nyereség.
**Méret: S.**

## 2. Szójegyzék-konzisztencia ellenőrzés a verify-ban

A `subtr.py verify` (vagy külön check) jelezze, ha a forrásban szerepel egy
szójegyzék-terminus (`en`), de a magyarban nem az előírt `hu` fordítás áll.
Determinisztikus, hívásköltség nélküli minőség-kapu. A `verify` ma csak ismert
hibamintákat keres (`scan_warn_patterns`), a szójegyzéket nem veti össze a
fordítással.

Ami készen áll hozzá: a forrás–fordítás párosítás
(`subtr.tasks.review.check_source_alignment`, `subtr.srt`), az alap-szótárakkal
összefésült szójegyzék (`subtr.glossary.load_merged`) és a szóhatáros
előfordulás-szűrés (`subtr.glossary.filter_for_source`). Ragozott magyar
alakokra prefix-egyezés, figyelmeztetés-szinten. A review-mérés szerint a
lektor-modellek éppen a szójegyzék- és regiszter-sértésekben térnek el
leginkább — ezek egy részét ez a kapu ingyen megfogná. **Méret: S.**

## 3. Költség-kimutatás epizódonként

A Gemini `usage_metadata` token-számaiból és a `claude -p --output-format
json` költség-mezőjéből epizódonkénti összesítés (`costs.log`). A
`subtr/quota.py` csak a Gemini API hívásszámát könyveli; token- vagy
költségmérés a kódban nincs. A gyűjtés természetes helye a `subtr/providers/`
adapterek. Az előfizetésből futó CLI-providereknél (Codex, Grok, Antigravity)
költség helyett hívásszám és futásidő mérhető. **Méret: S–M.**

## 4. Alap-szótárak — ami nyitva maradt

- **`ja-common`** (japán megszólítások, utótagok) és **`ko-sageuk`** (Joseon-udvar,
  rangok): az `index.json`-ban szerepelnek, fájljuk még nincs. Forrásanyag
  kell hozzájuk — bevált sorozat-szójegyzék vagy magyar fordítói forrás; a
  `ko-sageuk` vázához a kutatás már talált kiindulást (lásd az archivált terv
  *Kutatás* szakaszát).
- **Explicit „nem fordítandó” jelző** (`"keep": true`): ma az `en == hu` jelzi,
  hogy egy terminus változatlan marad. Csak akkor érdemes felvenni, ha a
  modellek ezt félreértik.

**Méret: tartalomfüggő (alaponként S), a jelző S.**

## 5. Desktop GUI — újratervezendő alapokon

A [archive/desktop_gui_v1.md](archive/desktop_gui_v1.md) a régi (törölt)
gyökér-scriptek subprocess-hívására épült. Ha a GUI-irány újra előkerül, az
alapja az importálható `subtr.tasks` API és a `subtr.cli` legyen — új
tervezési kör kell hozzá; a v1-ből a képernyőtervek és a projekt-állapot
koncepció újrahasznosítható. A beállítások képernyője ma már egyszerű: a
`subtr config` kimenete és a `.env` funkciónkénti sorai.

---

## Javasolt sorrend

1. **#1 review folytatása** — napi bosszúság-spórolás, kis munka.
2. **#2 szójegyzék-ellenőrzés** — ingyen minőség-kapu.
3. **#3 költség-kimutatás** — bármikor, független.
4. **#4 alap-szótárak** — amikor japán vagy sageuk sorozat jön.
5. **#5 GUI** — csak ha az igény tényleg felmerül.
