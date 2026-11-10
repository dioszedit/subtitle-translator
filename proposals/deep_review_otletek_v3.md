# Nyitott fejlesztési ötletek (v3)

> Előzmény: [archive/deep_review_otletek_v2.md](archive/deep_review_otletek_v2.md).
> A v2-höz képest (2026-11):
> - **kikerült** a `subtr.py run` végigvivő parancs — a teljes menetet a gyakorlatban
>   az `epizod` skill viszi végig, a fájlokból felismerve, hol tart a pipeline;
> - **bekerültek** az alap-szótárak nyitva maradt tételei (a megvalósult terv:
>   [archive/alap_szotarak.md](archive/alap_szotarak.md));
> - **megvalósult** a review folytatása megszakadás után (részeredmény-fájl, korai
>   leállás kvótánál, hiányos riport) — a leírása a fő README-ben van;
> - a hivatkozások a mai kódhoz igazodnak (öt provider, alap-szótárak,
>   funkciónkénti provider / modell / effort a `subtr/defaults.env`-ből).

---

## 1. Szójegyzék-konzisztencia ellenőrzés a verify-ban

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

## 2. Költség-kimutatás epizódonként

A Gemini `usage_metadata` token-számaiból és a `claude -p --output-format
json` költség-mezőjéből epizódonkénti összesítés (`costs.log`). A
`subtr/quota.py` csak a Gemini API hívásszámát könyveli; token- vagy
költségmérés a kódban nincs. A gyűjtés természetes helye a `subtr/providers/`
adapterek. Az előfizetésből futó CLI-providereknél (Codex, Grok, Antigravity)
költség helyett hívásszám és futásidő mérhető. **Méret: S–M.**

## 3. Alap-szótárak — ami nyitva maradt

- **`ja-common`** (japán megszólítások, utótagok) és **`ko-sageuk`** (Joseon-udvar,
  rangok): az `index.json`-ban szerepelnek, fájljuk még nincs. Forrásanyag
  kell hozzájuk — bevált sorozat-szójegyzék vagy magyar fordítói forrás; a
  `ko-sageuk` vázához a kutatás már talált kiindulást (lásd az archivált terv
  *Kutatás* szakaszát).
- **Explicit „nem fordítandó” jelző** (`"keep": true`): ma az `en == hu` jelzi,
  hogy egy terminus változatlan marad. Csak akkor érdemes felvenni, ha a
  modellek ezt félreértik.

**Méret: tartalomfüggő (alaponként S), a jelző S.**

## 4. Desktop GUI — újratervezendő alapokon

A [archive/desktop_gui_v1.md](archive/desktop_gui_v1.md) a régi (törölt)
gyökér-scriptek subprocess-hívására épült. Ha a GUI-irány újra előkerül, az
alapja az importálható `subtr.tasks` API és a `subtr.cli` legyen — új
tervezési kör kell hozzá; a v1-ből a képernyőtervek és a projekt-állapot
koncepció újrahasznosítható. A beállítások képernyője ma már egyszerű: a
`subtr config` kimenete és a `.env` funkciónkénti sorai.

---

## Javasolt sorrend

1. **#1 szójegyzék-ellenőrzés** — ingyen minőség-kapu.
2. **#2 költség-kimutatás** — bármikor, független.
3. **#3 alap-szótárak** — amikor japán vagy sageuk sorozat jön.
4. **#4 GUI** — csak ha az igény tényleg felmerül.
