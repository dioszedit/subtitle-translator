# SRT előtisztító add-on (SDH → tiszta felirat)

Feliratfordító munkafolyamat **fordítás előtti** kiegészítője. A nyers
(jellemzően angol) feliratból eltávolítja a hang-/zene-/effekt- és
beszélő-jegyzeteket, hogy a végeredmény **tiszta, narráció-mentes** magyar
felirat legyen — a fordítási döntésekhez viszont a kontextust megtartja.

## Mikor érdemes használni?

**CSAK akkor, ha a forrásfelirat SDH/CC jellegű**, azaz tartalmaz
hangulat-/zene-/effekt- vagy beszélő-jegyzeteket. A legtöbb "sima" felirat
NEM tartalmaz ilyet — ott erre az add-onra nincs szükség, ki lehet hagyni.

Tipikus jelek, hogy SDH a forrás (ilyenkor kell az add-on):

```
[music playing]     [tense music]     [♪]     [horn blares]
[laughs]  [sighs]  [door creaks]  [footsteps]  (whispering)
♪ song lyrics here ♪
[Anna] Szia!        NARRÁTOR: Aznap éjjel…
STYLE  ::cue()      (WebVTT-artefaktumok)
```

Rövid ökölszabály: ha a feliratban `[szögletes]` vagy `(kerek)` zárójeles
hangleírások / nagybetűs `NÉV:` beszélőcímkék vannak → futtasd az add-ont.
Ha nincsenek → nincs rá szükség.

## Mit csinál pontosan?

1. Törli a **tisztán** hang-/zene-/effekt cue-sorokat (amelyek a `[...]` és
   `(...)` szegmensek eltávolítása után üresek), plusz a WebVTT-artefaktumokat
   (`STYLE`, `::cue()`, `NOTE`, `REGION`, `WEBVTT`). A kulcsszavak csak akkor
   számítanak artefaktumnak, ha **egyedül állnak a sorban** (kivéve a `::cue`
   prefixet) — a "NOTED.", "REGIONAL finals" vagy "NOTE THE DATE" jellegű
   valódi szöveg nem törlődik.
2. Ha egy felirat így teljesen üressé válik → az egész feliratot eldobja.
3. **Újraszámoz** 1..N-ig (a lyukak megszűnnek).
4. Az **időbélyegeket változatlanul** viszi tovább — semmit nem "generál".
5. Opcionálisan `N`-esével (alapból 150) **blokkfájlokra bontja** a fordításhoz.

> **SDH-forrásnál a projekt alapmenete NEM az előtisztítás**, hanem a fordítás
> utáni tisztítás (`postclean_srt.py`, `steps.txt` 6/b — lásd lent): a fordító
> zárójelben lefordítja a címkéket, így látja, ki beszél, és a pipeline végig
> 1:1-ben fut az eredeti forrással. Az előtisztítás opcionális: WebVTT-
> artefaktumoknál kell, vagy ha a fordítót nem akarod a jegyzetekkel terhelni.

A `--strip-labels` kapcsolóval ezenfelül:
- a sor eleji **beszélő-/névcímkék** (`[Anna] Szia!` → `Szia!`, `NÉV: …`) és
- a dialógus utáni **sor végi jegyzetek** (`Let me... [sighs]` → `Let me...`)
  is lekerülnek, hogy a fordítóhoz már ne jussanak el.

Mindkét módban: ha egy kétsoros párbeszédből a jegyzetsor törlése után csak egy
sor marad, a párbeszéd-kötőjel is lekerül (`-Hello...` / `-[line beeps]` → `Hello...`).

Amit **NEM** dob el:
- `--strip-labels` nélkül a **beszélő-/névcímkéket** dialógus-sorokban
  (`[Anna] Szia!`) — ezek adják a fordítási kontextust (ki beszél → nem,
  tegezés/magázás); a kész fordításból a `postclean_srt.py` veszi ki őket.
- A `--keep "MINTA"` mintát tartalmazó sorokat (pl. kétnyelvű cím-kártya).

## Hogyan illeszkedik a pipeline-ba

```
0. ELŐTISZTÍTÁS (ez az add-on):
     python addons/srt-preclean/preclean_srt.py "input/Sorozat - S01E01.eng.srt"
   -> input/Sorozat - S01E01.eng.clean.srt
   -> input/blocks/Sorozat - S01E01.eng/..._block_001_....srt   (a forrás mappája alá!)

1–3. FORDÍTÁS + ÖSSZEFŰZÉS a szokásos parancsokkal, a preclean blokkmappájával:
     python subtr.py translate "input/blocks/Sorozat - S01E01.eng" --provider claude
     python subtr.py merge "input/blocks/Sorozat - S01E01.eng" "output/Sorozat - S01E01.hun.srt"
   (Vagy: --blocks-dir blocks kapcsolóval eleve a gyökér blocks/ alá kéred a
   blokkokat; vagy a .clean.srt-t splitteled a subtr.py split-tel — ekkor nem
   angol forrásnál add meg a --source-lang-ot, mert a ".clean" tag elfedi a
   fájlnév nyelvkódját.)

4. ELLENŐRZÉS — a .clean.srt ELLEN (az add-on törölt és újraszámozott, az
   eredeti .eng.srt-hez képest hamis hibákat kapnál):
     python subtr.py verify "input/Sorozat - S01E01.eng.clean.srt" "output/Sorozat - S01E01.hun.srt"
   vagy az add-on saját ellenőrzője:
     python addons/srt-preclean/verify_preclean.py "input/….eng.clean.srt" "output/….hun.srt"
   - Egyezik-e a feliratszám, az időbélyeg 1:1, folytonos-e a sorszám.
     A megmaradt zárójeles sorokat FIGYELMEZTETÉSKÉNT listázza (a lefordított
     [megjegyzések] és a címkártya jogosak — azok nem hibák).
```

A fordításnál a megtartott beszélőcímkék (`[Anna]`, `NARRÁTOR:`) csak
kontextus: a `TRANSLATION.md` szerint a kész magyar szövegből kikerülnek.

> Miért blokkokban? Így egy hosszú felirat kezelhető, ellenőrizhető darabokban
> fordítható, és egy elrontott blokk újrafordítható a többi érintése nélkül.
> Ha nem kell blokkokra bontás, használd a `--no-blocks` kapcsolót — akkor csak
> a `.clean.srt` készül el, és azt fordítod egyben.

## `preclean_srt.py` — kapcsolók

| Kapcsoló | Jelentés |
|---|---|
| `srt_file` | A nyers forrás SRT (kötelező, első argumentum) |
| `--block-size N` | Feliratok blokkonként (alapból **150**) |
| `--no-blocks` | Ne bontson blokkokra, csak `.clean.srt`-t készítsen |
| `--strip-labels` | A sor eleji beszélő-/névcímkéket (`[Név]`, `(Név)`, `NÉV:`) is törölje. A kettőspontos forma csak **csupa nagybetűvel** számít címkének — a "Listen:", "Remember this:" jellegű mondatkezdet érintetlen marad. |
| `--keep "MINTA"` | Soha ne törölje az ezt (regex) tartalmazó sort. Többször megadható. |
| `--outdir DIR` | Hova kerüljön a `.clean.srt` (alapból a forrás mappája) |
| `--blocks-dir DIR` | A blokkok gyökérmappája (alapból `<outdir>/blocks`) |

### Példák

```bash
# Alap: tisztítás + 150-es blokkok, kimenet a forrás mellé
python preclean_srt.py "Sorozat - S01E05.eng.srt"

# Csak tiszta SRT, blokkok nélkül
python preclean_srt.py "Sorozat - S01E05.eng.srt" --no-blocks

# Kétnyelvű cím-kártya megtartása (ne törölje cue-ként)
python preclean_srt.py "input.eng.srt" --keep "DOCTOR ON THE EDGE"

# A beszélőcímkéket eleve dobjuk (ha nincs szükség kontextusra)
python preclean_srt.py "input.eng.srt" --strip-labels

# Külön kimeneti mappa
python preclean_srt.py "input.eng.srt" --outdir out --blocks-dir out/blocks
```

## `verify_preclean.py` — ellenőrzés fordítás után

```bash
python verify_preclean.py "input.eng.clean.srt" "kesz.hun.srt"
python verify_preclean.py "input.eng.clean.srt" "kesz.hun.srt" --keep "DOCTOR ON THE EDGE"
```

Ellenőrzi: azonos feliratszám, időbélyeg 1:1, folytonos sorszám. A zárójeles
sorokat figyelmeztetésként listázza (a lefordított [megjegyzések] és a
címkártya jogosak, nem számítanak hibának — a címkártya-cue-t, ahol minden sor
teljes egészében zárójeles, automatikusan kihagyja). Kilépési kód 0 = rendben,
1 = hiba (CI/szkript-barát). *Korábbi neve `verify_srt.py` volt — átnevezve,
hogy ne ütközzön a projekt gyökerében lévő másik ellenőrzéssel (ma: `py subtr.py verify`).*

## Fordítás utáni tisztítás: `postclean_srt.py` (SDH-forrás alapmenete)

A kész magyar feliratból törli a lefordított beszélőcímkéket és hangjegyzeteket
(`[Anna] Igen.` → `Igen.`, `Hadd... [sóhajt]` → `Hadd...`). Minden `[...]` és
`(...)` szegmenst töröl, kivéve a sorozatcím-kártyát — ezt a `TRANSLATION.local.md`
`Title` / `Hungarian title` mezőiből (a zárójeles natív címmel együtt) és a
`glossary.json` `meta.series`-éből ismeri fel; egyéb megtartandó sor: `--keep MINTA`.
A csak jegyzetből álló feliratot eldobja, a magára maradt párbeszéd-kötőjelet
leveszi, és **újraszámoz** (az időbélyegek változatlanok).

```
python addons/srt-preclean/postclean_srt.py "output/Sorozat - S01E01.hun.srt" --dry-run   # előnézet
python addons/srt-preclean/postclean_srt.py "output/Sorozat - S01E01.hun.srt"
  -> output/Sorozat - S01E01.hun.clean.srt
```

- **A bemenetet nem írja felül.** Az `output/…hun.srt` 1:1-es (címkés) példány
  marad, a review / triage / glossary később is futtatható rajta; a `.hun.clean.srt`
  a végleges, ezt viszed tovább (resegment, majd a `Season 01/`-be másolás).
- **Mikor:** a review-javítások átvezetése (triage) és a glossary (6.) UTÁN, a
  resegment (7.) ELŐTT. A tisztított fájl cue-száma kisebb, ezért a verify
  az eredeti forrás ellen azon eltérést jelezne — az ellenőrzés az 1:1-es példányon fut.
- **Csak SDH-forrásnál!** Nem SDH forrásnál a `[...]` képi szöveg (helyszín, hír,
  SMS), azt meg kell tartani. Védelem: ha a fájlban alig van beszélőcímke vagy
  sor végi jegyzet (5-nél kevesebb, vagy a feliratok 2 %-ánál kevesebb), a szkript
  nem ír semmit; felülbírálás: `--force`.
- A kerek zárójeles szegmenseket külön kilistázza: a fordítónak ezeket is szögletes
  zárójelbe kell tennie, de ha egy valódi zárójeles megjegyzés becsúszott, itt látod.

## Megjegyzések, finomhangolás

- **Kódolás:** a beolvasás `utf-8-sig` (BOM-toleráns), a kiírás `utf-8`.
- **Dalszövegek:** a `♪ ... ♪` közti valódi szöveget MEGTARTJA (csak a tisztán
  `♪`-ből álló sorokat dobja). A dalszöveget a fordításnál fordítsd le.
- **Blokk-védelem:** újrafuttatáskor a forrás-blokkokat regenerálja, de a
  lefordított, 2–3 betűs nyelvi végződésű fájlokat (`_HUN.srt`, `_DE.srt`, …)
  SOHA nem törli — a kész munkád biztonságban van.
- **Testreszabás:** ha egy sorozatban visszatérő, nem szabványos cue-forma van,
  a `preclean_srt.py` tetején az `ARTIFACT_RE` és a `LEADING_LABEL_RE`
  bővíthető.

## Fájlok

```
addons/srt-preclean/
├── preclean_srt.py   # fordítás előtti tisztító + blokkokra bontó
├── verify_preclean.py # fordítás utáni ellenőrző
├── postclean_srt.py  # fordítás utáni SDH-tisztító (beszélőcímkék, hangjegyzetek)
└── README.md         # ez a leírás
```
