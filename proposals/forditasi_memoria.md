# Fordítási memória és triage-döntési memória

> **Állapot (2026-11-22):**
>
> | Fázis | Állapot |
> |---|---|
> | 0. Forrás-igazítás addon | ✅ **kész** — `addons/align-source/` (`fe1744d`) |
> | 1. Konzisztencia-riport | ✅ **kész** — `subtr.py consistency`, `subtr/timing.py` (`fe1744d`) |
> | +  Párbeszéd-gondolatjel a resegmentben | ✅ **kész** — a tervben nem szerepelt, menet közben jött (`fe1744d`) |
> | 2. Triage-előszűrés, döntés-szakasz, napló | ⏳ terv |
> | 3. Rögzített sorok | ⏳ terv |
> | 4. Keresés-alapú referencia | ⏳ terv, csak mérés után |
>
> A megvalósítás részletei és a tervtől való eltérések: [Megvalósítás](#megvalósítás-0-és-1-fázis).
> Előzmény: a külső fordítások lektorálásánál (2026-11) sok kézi munka ment el
> olyan hibák javítására, amelyeket egy sorozatszintű memória megelőzött volna.
> Az első változatot egy független review vetette össze a kóddal. Ennek
> eredményeként kikerült az SQLite-adatbázis és az automatikus tiltólista, a
> sorrend pedig megfordult: előbb determinisztikus ellenőrzés, és csak mérés
> után következik a keresés-alapú referencia.

## A probléma

A pipeline ma minden fordítási blokkot és lektorált chunkot **önmagában** kezel.
A sorozat egészéről csak a `glossary.json`-t (szűrve: `subtr/glossary.py` →
`filter_for_source`) és a `TRANSLATION.local.md`-t ismeri. Ebből két, egymástól
független hiány következik.

### 1. Nincs fordítási memória

A jóváhagyott fordítások nem jutnak vissza a következő részekbe. Tipikus
következmények:

- **Visszatérő dalszövegek.** A főcím- és záródal minden részben kicsit más
  fordítást kap, utólag kézzel kell egységesíteni.
- **Képernyőn megjelenő szöveg** (táblák, névkártyák, helyszínek): ugyanaz a
  tábla részenként másképp szerepel.
- **Írásmód-ingadozás** a szójegyzékben nem szereplő neveknél (ugyanaz a pinyin
  név ékezettel és anélkül, vagy sh/s eltéréssel).
- **Ismétlődő fordulatok** (jelmondatok, eskük) részenként eltérnek.

A szójegyzék kifejezéseket tart, nem mondatokat, és minden bejegyzést kézzel
kell felvenni.

### 2. Nincs triage-döntési memória

A `decisions.json` (`subtr/tasks/apply_review_auto.py`) **csak az elfogadott**
javításokat tartalmazza. Az elvetett javaslat és az elvetés oka nem marad meg,
ezért a review-modell részről részre ugyanazokat a téves javaslatokat ismétli:

- szójegyzék-ütközés: az alap-szótár alakja ott, ahol a sorozat szójegyzéke
  felülírja (`Lord` = „nagyúr” ↔ a sorozatban „X úr”);
- a címkártya átformázása, amit a felhasználó már eldöntött;
- tegezés/magázás „javítása” egy rögzített regiszter-kivétel ellenére;
- a fordító szándékos, saját táblafelirat-sorainak törlése;
- no-op (a javaslat megegyezik az aktuális szöveggel).

Egy 10 részes lektorálásnál ez részenként kb. 3–10 elvetendő javaslat volt,
mindig ugyanazok.

## Célok és korlátok

1. Konzisztencia a sorozaton belül.
2. A meghozott triage-döntéseket ne kelljen újra meghozni.
3. A felhasználó munkamenete ne bonyolódjon. Windows, csak standard könyvtár,
   nem technikai felhasználó: minden állapot **ember által olvasható és kézzel
   javítható** fájlban legyen.
4. A repó nyilvános: feliratszöveg csak a sorozat-mappában lehet.

## Kiinduló tények a kódból

- **Mi a „kész” felirat?** Az `apply-auto` az `output/…hun.srt`-t írja, de a
  végleges szöveg a resegment (`.merge.srt`), a `postmerge.py`, a postclean és
  a kézi Subtitle Edit-javítás után a `Season 01/`-ben áll. A
  `subtr/tasks/bases.py` `_translated_pairs` függvénye már mindkét helyet nézi.
- **A cue-számok nem stabilak.** A `resegment reflow --split` 1..N-re
  újraszámoz (`write_renumber`), a merge és a `postmerge.py` összevon. Ezért a
  `bases check` is kihagyja azt a fájlt, ahol a sorszámhalmazok nem egyeznek.
  **Párosítani időbélyeg-átfedéssel kell**, nem sorszámmal.
- **Külső fordításnál** a forrás igazítását ma egy repón kívüli segédszkript
  végzi (`sandbox/tools/align_source.py`), amit a ZIP-es felhasználó nem kap
  meg. A kimenete n:1 (több forrássor egy magyar cue alatt), és helykitöltőt
  ír a forrás nélküli cue-khoz.
- **A felülírt alap-bejegyzések** nincsenek benne a `load_merged` eredményében
  (a `with_bases` eldobja őket). Ami kell, megvan:
  `subtr/tasks/bases.py` → `check()["overridden"]`.
- **Review részeredmény:** a `chunk_hashes` a forrással kiegészített chunk
  szövegét hash-eli, a fejléc-ujjlenyomat (`instruction`) pedig a
  `TRANSLATION.local.md`-t is tartalmazza. Bármi, ami a promptba kerül,
  érvényteleníti a félkész review-kat. Ezt tudatosan kell kezelni.
- **Claude-út a fordításnál:** a `_make_claude_translator` a per-blokk promptot
  parancssori argumentumként adja át (`-p`). Hosszabb referencia ott nem fér
  el biztonságosan (Windows parancssor-limit, idézés), csak fájlon keresztül.

## Javasolt megoldás

Adatbázis nincs. Minden futáskor újraszámolódik a meglévő fájlokból. Egy
sorozat kb. 15–20 ezer cue, ennek beolvasása (`_translated_pairs` +
`parse_by_index`) másodperc alatti. Pontos egyezéshez dict kell, közelítőhöz
`difflib`. Így nincs `memory add` lépés, nincs elavult állapot, nincs séma.

### 0. Előfeltétel: a forrás-igazítás addonná emelése — ✅ kész

Az `align_source.py` kerüljön be a repóba addonként (pl. `addons/align-source/`),
dokumentálva. Egyrészt a külső fordítások lektorálása enélkül nem
reprodukálható. Másrészt a konzisztencia-ellenőrzés ugyanezt az
időbélyeg-párosítást használja.

### 1. fázis: konzisztencia-riport (`subtr.py consistency`) — ✅ kész

A `bases check` mintájára épülő, csak riportáló parancs, LLM nélkül.

- **Bemenet:** a végleges fájlok (`Season 01/` elsőbbséggel, különben
  `output/`), párosítva a forrással **időbélyeg-átfedés** alapján.
- **Azonos forrássor, eltérő magyar:** ugyanaz a normalizált forrássor más
  részben másképp lett lefordítva. A riport kiírja a változatokat a
  gyakoriságukkal, és javasolja a leggyakoribbat.
  - Elsősorban képernyőszövegre (`[…]`) és dalra (`♪`/`♫`), ahol az egyezés
    valóban azonos szöveget jelent.
  - Párbeszédnél csak hosszabb sorokra (pl. 25+ karakter), mert a rövid
    mondatok („Igen.”) jogosan térnek el.
  - SDH-forrásnál a `[…]` beszélőcímke vagy hangjegyzet, nem tábla, ezért ott
    a tábla-ág kikapcsol.
- **Írásmód-változatok:** a magyar szövegben ugyanannak a tulajdonnévnek több
  alakja él. Nagybetűs szóalakok klaszterezése kis szerkesztési távolsággal,
  a ragok levágása után.
- **Normalizálás:** a `normalize_for_match` mellé HTML-tag, `♪`/`♫`, írásjel
  és kötőjel eltávolítása az összevetéshez.
- **Kimenet:** szöveges riport, plusz opcionálisan egy
  `decisions.json`-kompatibilis javaslatfájl. A meglévő `apply-auto`
  szárazfuttatással és jóváhagyással vezeti át.
- Rokon a v3 #1 ötletével (szójegyzék-ellenőrzés a `verify`-ban), érdemes a
  kettőt együtt tervezni.

### 2. fázis: triage-előszűrés és kézi döntés-szakasz — ⏳ terv

**2a. Determinisztikus előszűrés** (kb. 50 sor; a `review-triage` skill hívja,
vagy `subtr.py triage-prefilter <REVIEW.json>`):

- **no-op:** a javaslat whitespace-normalizálva megegyezik az aktuális
  szöveggel;
- **drift:** a riport `eredeti` mezője eltér az aktuális szövegtől;
- **szójegyzék-ütközés:** a javaslat egy olyan alap-szótári `hu` alakot hoz
  be, amelyet a sorozat ugyanarra az `en` kulcsra felülír (forrás:
  `bases.check()["overridden"]`).

A kimenet a találatok jelölése. A triage ezeket egy sorban, összesítve látja,
és felülbírálhatja őket.

**2b. „Lektori döntések” szakasz a `TRANSLATION.local.md`-ben**, kézzel írva.
Példák: „a címkártya alakja marad”, „a fordító saját táblafeliratai
maradnak”, „Lord + név = X úr”. A review és a triage ezt ma is megkapja, új
kód nem kell hozzá. A skill javasolhat új sort, de a felhasználó veszi fel.
Mivel a fájl a review-ujjlenyomat része, egy új sor a félkész review-kat
újraindítja. Ez elfogadható, mert ritkán változik.

**2c. Triage-napló: `output/<stem>.hun_triage.json`**, sima JSON-fájl.

- A `review-triage` skill a `decisions.json` mellé írja: minden találat,
  verdikttel (`accepted` / `rewritten` / `dropped`) és okkóddal.
- Az okkód **zárt lista**, és a skill validálja, mert LLM-ként írva
  sodródna. Kódok: `no_op`, `drift`, `glossary_conflict`, `decision_rule`,
  `register_exception`, `less_faithful`, `unclear_speaker`, `invalid_form`,
  `other`.
- Egyelőre csak a nyomon követhetőséget szolgálja. Ha később kiderül, hogy a
  kézi szakasz kevés, ebből lehet statisztikát vagy precedens-keresést
  építeni.

### 3. fázis: rögzített sorok — ⏳ terv

A legnagyobb haszon (dal, tábla) **retrieval nélkül** is elérhető.

- A sorozat `glossary.json`-jának `phrases` kategóriájában rögzített sorok:
  forrás → jóváhagyott magyar. A `filter_for_source` ezeket már ma is csak
  akkor engedi a promptba, ha a szövegben előfordulnak. Így a system promptba
  kerülnek, a cache-t alig érintik, és a review is kötelezőként kezeli őket.
- **Csak kézi megerősítéssel kerülnek be.** Az 1. fázis riportja javasolja
  őket („ez a dalsor 12 részben szerepel, 3 változatban”), a felhasználó
  hagyja jóvá. Így egy rossz első fordítás nem rögzül csendben 30 részre.
- Ha a végleges szöveg eltér a rögzített sortól, az 1. fázis riportja jelzi.
  A rendszer nem írja felül csendben.

### 4. fázis: keresés-alapú referencia, csak mérés után — ⏳ terv

Ha az 1–3. fázis után is marad számottevő inkonzisztencia a párbeszédben:

- **Fordítás:** blokkonként a korábbi részek hasonló forrássorai és a
  jóváhagyott fordításuk, **referenciaként** (nem kötelezőként).
  - A Claude-úton csak a blokk mellé írt fájlként (`<block>.tm.txt`), amit az
    agent `Read`-del olvas. A parancssori prompt nem bírja el.
  - A kikeresés a worker-pool indítása előtt, a főszálon történik.
  - Ismert korlát: párhuzamos fordításnál csak a már kész részekből merít,
    ezért a sorrendtől függ.
- **Review:** `[KORÁBBAN]` sor az érintett szekciók alatt. Fejléc-ujjlenyomat
  nem kell hozzá, mert a chunk-hash a kiegészített szöveget hash-eli, így
  csak az érintett chunk fut újra.
- A tárolásról (fájl vagy SQLite) csak ekkor kell dönteni. Vektoros keresés a
  mostani mérettel nem indokolt.

## Bevezetési sorrend

| Fázis | Tartalom | Haszon | Kockázat | Állapot |
|---|---|---|---|---|
| 0 | `align_source` addonná emelése | külső fordítás lektorálása reprodukálható | alacsony | ✅ kész |
| 1 | `consistency` riport | dal-, tábla- és írásmód-eltérés LLM nélkül | alacsony: csak riportál | ✅ kész |
| 2 | triage-előszűrés + kézi döntés-szakasz + napló | kevesebb ismétlődő kézi elvetés | alacsony: csak jelöl | ⏳ |
| 3 | rögzített sorok a `phrases`-ben, kézi jóváhagyással | konzisztencia már fordításkor | alacsony–közepes: rossz sor rögzülése, ezért kézi kapu | ⏳ |
| 4 | keresés-alapú referencia (csak mérés után) | párbeszéd-konzisztencia | közepes: prompt-méret, sorrend-függés | ⏳ |

## Megvalósítás (0. és 1. fázis)

Commit: `fe1744d` (2026-11-22), mind a 8 élő sorozat-mappába szinkronizálva.
Három kódreview-kör előzte meg (14, 10 és 9 találat, mind javítva).

**Elkészült:**

- `subtr/timing.py` — közös időbélyeg-párosítás: `parse_timed`, `overlap`,
  `overlap_map` (rendezett söprés), `assign`. Egy forrás-cue ahhoz a magyar
  cue-hoz kerül, amelyik a nagyobb részét lefedi; egyenlőségnél ahhoz, amelyik
  pontosabban egybeesik vele (így egy hosszú stáblista- vagy tábla-cue nem viszi
  el a párbeszéd forrássorát). A bemenet sorrendje tetszőleges.
- `addons/align-source/` — a sandbox-eszköz utódja, ugyanazzal a kimenettel,
  plusz: több rész és nyelv egyszerre, `.hun.merge.srt` bemenet, a kettévágott
  forrásmondat a második magyar cue-ba is bekerül, a fordító saját táblája
  „saját kiírás” marad.
- `subtr.py consistency` — riport a tábla-, dal- és párbeszéd-eltérésekről,
  a névírás-változatokról és a kötőjeles ragozásról; `--decisions` javaslatfájl
  (`output/<név>.hun_consistency.json`) a tábla- és dal-eltérésekre, `apply-auto`
  formátumban.
- Dokumentáció: `docs/05-review.md` (külső fordítás lektorálása),
  `docs/08-utomunka.md` (egységesség a részek között), `addons/align-source/README.md`.
- Tesztek: `tests/test_timing.py`, `tests/test_consistency.py`,
  `tests/test_align_source.py`, kiegészítve `tests/test_resegment.py`.

**Eltérések a tervtől:**

- **Kész felirat:** a `Season NN/` mappák (nem csak a `Season 01`), azon belül
  ami nincs, az `output/…hun.merge.srt`, végül az `output/…hun.srt`.
- **Szigorúbb párosítás:** egy előfordulás csak akkor számít, ha a forrás-cue
  legalább 75%-a ebbe a magyar cue-ba esik, és legfeljebb 25%-a lóg át egy azonos
  fajtájú (tábla / szöveg) másik cue-ba. A dal-cue kimarad, ha párbeszédsor,
  zárójel nélküli tábla vagy vegyes jelölésű sor is van benne. Enélkül a
  `--decisions` sorokat törölt vagy duplázott volna.
- **Táblánál** csak az egytáblás cue számít: több táblánál a fordító sorrendje
  eltérhet a forrásétól.
- **Írásmód-változatok:** szerkesztési távolság helyett „név-váz”: ékezet,
  kötőjel, szóköz és aposztróf nélkül, 5 karaktertől a pinyin sh/zh/ch = s/z/c.
  A szomszédos nagybetűs szavak egy névként számítanak (a „Li Si” nem keveredik
  a „Nagy Shi”-vel). A magyar ragozás (Szívet / Szívét, Hegyet / Hegyét) nem
  jelez. A kötőjeles ragozás (Fang-ot / Fangot) külön listában szerepel.
- **Normalizálás** a `consistency.py`-ban maradt, nem a `subtr/glossary.py`-ba
  került: csak itt kell.
- **Plusz, a tervben nem szerepelt:** a `resegment reflow` és `merge` a sor eleji
  párbeszéd-gondolatjel után szóközt tesz (`-Gyere!` → `- Gyere!`), a `report`
  `DASH` flaggel jelzi. A szóköz nélküli kötőjeles sort a resegment eddig nem
  ismerte fel párbeszédként, és két szereplő sorát egy mondatba tördelhette.
- **Valódi próba:** a `sandbox/` helyett két kész sorozat `Season 01` mappáján,
  csak olvasva. Mindkettőben talált valódi eltérést (táblák, betétdalok,
  névírás), ezeket a felhasználó jóváhagyásával egységesítettük.

## Érintett kód

- ✅ új: `addons/align-source/`, `subtr/timing.py`, `subtr/tasks/consistency.py`;
- ⏳ új: a prefilter a `subtr/tasks/` alatt, vagy a skill segédszkriptjeként;
- ✅ `subtr/cli.py`: a `consistency` alparancs (⏳ a prefilteré);
- ✅ `subtr/tasks/resegment.py`: párbeszéd-gondolatjel (a tervben nem szerepelt);
- ~~`subtr/glossary.py`: a megerősítő normalizálás~~ — a `consistency.py`-ban maradt;
- ⏳ `subtr/tasks/bases.py`: az `overridden` újrahasznosítása (2. fázis);
- `.claude/skills/review-triage/SKILL.md`: előszűrés, `hun_triage.json` zárt
  okkódokkal, „Lektori döntések” javaslata;
- `TRANSLATION.md` és a sablon: a „Lektori döntések” szakasz leírása;
- a 4. fázisban `subtr/tasks/translate.py` és `subtr/tasks/review.py`;
- ✅ `docs/`: a `consistency` parancs és az align-source (⏳ a döntés-szakasz).

## Tesztelés

- ✅ Egységtesztek: időbélyeg-párosítás (1:1, n:1, átszámozott merge, rendezetlen
  bemenet, stáblista), normalizálás, SDH, írásmód-klaszterezés, javaslatfájl,
  a három review összes esete regressziós tesztként.
- ✅ Szintetikus 3 részes minta, tudatosan elrontott dalsorral és tábla-írásmóddal.
- ✅ Valódi próba két kész sorozaton, csak olvasva (a `sandbox/` helyett).
- ⏳ Prefilter-tesztek (no-op, drift, felülírt alap-alak) — a 2. fázissal.

## Nyitott kérdések

1. Ki vegye fel a rögzített sorokat: a felhasználó kézzel, vagy egy
   `consistency --promote` parancs jóváhagyás után? (3. fázis)
2. A párbeszéd-egyezés minimális hossza (a 25 karakter csak kiinduló érték).
   Az első két valódi sorozaton a párbeszéd-ág jelzései többnyire jogos,
   jelenettől függő eltérések voltak — ez a hossz vagy a párbeszéd-ág
   alapértelmezése még hangolható.
3. Kell-e a 4. fázis egyáltalán? Ez az 1–3. fázis után egy valódi sorozaton
   mérhető.
