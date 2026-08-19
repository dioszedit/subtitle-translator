# Deep review ötletek — hátralévő fejlesztési javaslatok (v1)

> Forrás: a 2026-07-13-i teljes projekt-átvilágítás (deep review).
> A review során talált ÖSSZES hiba javítva lett; az akkor elfogadott
> ötletek (EN/HU igazítás-ellenőrzés, JSON riportok, `apply_review.py`)
> beépültek. Az alábbi öt ötlet **nem lett beépítve** — fontolgatott
> opciók, amikre később vissza lehet térni.

---

## 1. Közös `srt_common.py` modul

**Mi ez:** a scriptekben többszörösen (helyenként triplán) másolt kód egy
közös modulba: strukturális SRT-parser, `count_sections`, `load_claude_md`,
`load_glossary`, `parse_srt_by_index` + `check_en_alignment` +
`attach_english` (a két review scriptben szó szerint azonos), a Gemini
retry-logika (`is_transient_error` + backoff, három scriptben azonos),
chunk-range kezelés.

**Miért:** a deep review során minden közös hibát 2-3 fájlban kellett
javítani. A jövőbeli javítás/fejlesztés egyszer landolna. Precedens már
van: a `glossary_categories.py` pontosan így működik (5 script importálja).

**Kockázat/megjegyzés:** a scriptek eddig szándékosan önállóak
(másolhatók egy mappába) — a közös modul ezt a hordozhatóságot gyengíti,
a `glossary_categories.py` miatt viszont már most is van belső függés.

**Becsült méret:** M (mechanikus refaktor + a tesztek átfuttatása)

---

## 2. Glossary-konzisztencia ellenőrzés a verify-ban

**Mi ez:** a `verify_srt.py` (vagy külön check) szekció-párba állítja az
angol forrást és a magyar kimenetet (a párosító kód a review scriptekben
már készen van), és jelzi azokat a szekciókat, ahol az angolban szerepel
egy glossary `en` terminus, de a magyarban NEM szerepel az előírt `hu`
fordítás.

**Miért:** determinisztikus, API-költség nélküli kikényszerítése a
„szójegyzéket MINDIG használd" szabálynak; elkapja a párhuzamos fordító
agentek közti eltéréseket (pl. az egyik blokkban „Fenséged", a másikban
„Felséged").

**Finomság:** ragozott alakok — a magyar `hu` érték szótöve alapján érdemes
keresni (pl. „Koronaherceg" → „Koronaherceg*"), különben sok a hamis
riasztás. Első körben elég a prefix-egyezés + figyelmeztetés-szint.

**Becsült méret:** S–M

---

## 3. Review resume / inkrementális riportírás

**Mi ez:** a review scriptek chunkonként azonnal fájlba írják a
találatokat (append vagy `.partial` sidecar + futás végi véglegesítés),
és újrafutáskor a már kész chunkokat kihagyják — ugyanúgy, ahogy a
fordítók fájl-alapú checkpointtal futnak.

**Miért:** ma egy megszakadt review (Ctrl-C, kvótahiba a 9. chunknál)
minden addigi találatot elveszít, a pótlás pedig kézi
`--start-chunk`/`--suffix` tánc + a riportok kézi összefésülése.
A felülírás-védelem (beépült) a legrosszabbat már kizárja, de a kényelmes
folytatás hiányzik.

**Vázlat:** a JSON riport (beépült) jó alap — chunkonként egy
`findings`-batch append; futás elején ha van `.partial`, a kész chunk-számok
kiolvasása és kihagyása; a `.txt` riport a végén generálódik a JSON-ból.

**Becsült méret:** S–M

---

## 4. Egyparancsos pipeline (`pipeline.py`)

**Mi ez:** egy orchestrator parancs, ami a teljes menetet végigviszi:
split → translate (claude|gemini) → merge → verify → review → (resegment
report), és kihagyja azokat a lépéseket, amelyek artefaktuma már létezik
és frissebb az inputjánál.

**Miért:** a lepesek.txt 7 lépése helyett egy parancs; kevesebb
fájlnév-elgépelés (a leggyakoribb kézi hibaforrás); a lépések közti
konvenciók (naming) egy helyen érvényesülnek.

**Vázlat:**
```
python pipeline.py "input\Sorozat - S01E01.eng.srt" --translator gemini
# lépésenkénti skip-logika: ha blocks/ létezik → split kihagyva, stb.
# --from merge / --until verify: rész-futtatás
```
A checkpoint-konvenció már most fájl-alapú, ezért a skip-logika olcsó.
Kapcsolódik: a desktop GUI proposal (desktop_gui_v1.md) ennek a grafikus
burkolata lenne — előbb a CLI-orchestrator, arra épülhet a GUI.

**Becsült méret:** M

---

## 5. Költség-kimutatás epizódonként

**Mi ez:** a Gemini válaszok `usage_metadata`-jából (token-számok) és a
`claude -p --output-format json` költség-mezőjéből futásonként összesített
kimutatás: epizódonként mennyibe került a fordítás + review, modellenként
bontva; append egy `costs.log`-ba (vagy .json-ba).

**Miért:** a modellválasztási döntések („Opus jó, de drága → Gemini")
ma érzésre mennek; számokkal alátámasztva optimalizálható a
minőség/költség arány sorozatonként.

**Becsült méret:** S–M

---

## Javasolt sorrend, ha sorra kerülnek

1. **#3 (review resume)** — a legtöbb bosszúságot spórolja meg napi
   használatban, kicsi munka.
2. **#2 (glossary-check)** — ingyen minőség-kapu.
3. **#4 (pipeline.py)** — kényelem + a GUI-terv előfeltétele.
4. **#1 (közös modul)** — akkor éri meg igazán, ha a #2–#4 amúgy is
   hozzányúl a közös kódokhoz.
5. **#5 (költség-log)** — bármikor, független a többitől.
