# SRT Felirat Fordító — Claude Code projekt

SRT felirat-fordítási keretrendszer LLM-alapú fordítással és stilisztikai review-val.
A workflow Claude Code-on alapul, a review opcionálisan Gemini API-val is fut.

**Alapértelmezett irány:** angolról magyarra (EN→HU). Technikailag más nyelvpárokra
is használható (a glossary konzisztencia miatt projektenként egy forrásnyelv ajánlott).

**Tipikus use-case:** sorozat-feliratok fordítása (pl. koreai és más ázsiai drámák),
ahol fontos a karakterek, megszólítások és kulturális kifejezések konzisztens
kezelése — de a keretrendszer bármilyen videó/film/sorozat-felirathoz használható.

## Mappaszerkezet

```
subtitle-translator/
├── CLAUDE.md                    ← Fordítási szabályok (a translate + review scriptek
│                                  system promptként átadják)
├── glossary.json                ← Fordítási szójegyzék (kézzel validált)
├── .env.example                 ← Gemini API kulcs sablonja (.env-be másold)
├── .gitignore                   ← Mit ne commit-oljunk
│
├── split_srt.py                 ← 1. SRT szétvágása blokkokra
├── translate_parallel.py        ← 2a. Párhuzamos fordítás Claude Code-dal
├── translate_with_gemini.py     ← 2b. Párhuzamos fordítás Gemini API-val (alternatíva)
├── merge_srt.py                 ← 3. Blokkok összefűzése
├── verify_srt.py                ← 4. Strukturális ellenőrzés
├── review_with_claude.py        ← 5a. Stilisztikai review Claude Code-dal
├── review_with_gemini.py        ← 5b. Stilisztikai review Gemini API-val (opcionális)
├── apply_review.py              ← 5c. Review-riportok összefésülése + interaktív alkalmazás
├── apply_review_auto.py         ← 5d. Ugyanaz kérdés nélkül, döntés-fájlból (agent / batch)
├── resegment_srt.py             ← 7. Sorhossz/CPS QA + újratördelés (lásd resegment_srt.md)
├── glossary_extract.py          ← Szójegyzék bővítése (fordítás előtt angol-only, vagy utólag párból)
├── glossary_categories.py       ← Közös konstans (CATEGORIES) — itt vedd fel új
│                                  glossary-kategóriát, mind az 5 script innen olvas
├── gemini_quota.py              ← Gemini napi kvóta helyi könyvelése — a két Gemini
│                                  script automatikusan használja, önállóan is lekérdezhető
│
├── srt-preclean-addon/          ← Opcionális 0. lépés: SDH-forrás előtisztítása
│                                  (saját README a részletekhez)
├── input/                       ← Ide tedd az angol SRT fájlokat
├── blocks/                      ← Auto-generált blokk-fájlok
├── output/                      ← Kész magyar fájlok + review riportok
│
├── proposals/                   ← Fejlesztési irányok, alternatívák, tervek
│                                  (saját README a részletekhez)
└── lepesek.txt                  ← Quick-reference parancslista
```

Az `input/`, `output/`, `blocks/` mappák tartalma nem kerül a git repóba —
projektenként / epizódonként más, és gyakran szerzői jogi védettség alá esik.

## Előfeltételek

- **Python 3.10+**
- **Claude Code CLI** (`claude` parancs) — a fordításhoz és a Claude review-hoz
- **Gemini API kulcs** (opcionális) — ha Gemini-vel fordítasz (`translate_with_gemini.py`) vagy Gemini-vel review-zol (`review_with_gemini.py`)
- **Git** (opcionális) — verziókezeléshez

## Telepítés

### Új gépen — clone GitHub-ról

```powershell
git clone https://github.com/dioszedit/subtitle-translator.git
cd subtitle-translator

# Gemini scriptek függőségei (translate_with_gemini.py és/vagy review_with_gemini.py)
pip install google-genai python-dotenv pydantic

# .env létrehozása a sablonból
copy .env.example .env
# Szerkeszd: GEMINI_API_KEY=...   (https://aistudio.google.com/apikey)
```

> **macOS / Linux megjegyzés:** a README parancsai Windows PowerShell-re vannak
> írva. Más platformon a következő helyettesítések kellenek:
>
> | Windows | macOS / Linux |
> |---------|---------------|
> | `python` | `python3` |
> | `pip` | `pip3` |
> | `py` (lepesek.txt-ben) | `python3` |
> | `copy` | `cp` |
> | `del` | `rm` |
> | `input\fájl.srt` (backslash) | `input/fájl.srt` (forward slash) |
>
> Pl. macOS-en:
> ```bash
> pip3 install google-genai python-dotenv pydantic
> cp .env.example .env
> python3 split_srt.py "input/Sorozat - S01E01.eng.srt"
> ```

### Új projekt indítása

1. A clone-olt mappát használhatod közvetlenül, vagy másolhatod egy új mappába
   sorozatonként (ha külön repóként akarsz több sorozatot vezetni).
2. Nyisd meg a `CLAUDE.md`-t, és az "Aktuális sorozat adatai" szakaszt
   töltsd ki a sorozat címével, szereplőivel, stb.
3. Tedd az angol SRT fájlt az `input/` mappába.

## Használat (PowerShell)

### Teljes folyamat (egy epizód)

```powershell
# 1. Szétvágás blokkokra (alapból 150 szekciónként)
python split_srt.py "input\Sorozat - S01E01.eng.srt"
# Újra-splitnél (pl. más --block-size) --clean törli a régi blokkokat —
# enélkül a script leáll, hogy a két generáció ne keveredjen a merge-nél

# 2a. Fordítás 3 párhuzamos agent-tel — Claude Code
python translate_parallel.py "blocks\Sorozat - S01E01.eng" --agents 3
# vagy 2b. Ugyanaz Gemini API-val (olcsóbb alternatíva, ugyanazokat a blokkokat dolgozza fel)
# python translate_with_gemini.py "blocks\Sorozat - S01E01.eng" --agents 3

# 3. Összefűzés egy fájlba
python merge_srt.py "blocks\Sorozat - S01E01.eng" "output\Sorozat - S01E01.hun.srt"

# 4. Strukturális ellenőrzés (sorszámok, időbélyegek, szekciószámok)
python verify_srt.py "input\Sorozat - S01E01.eng.srt" "output\Sorozat - S01E01.hun.srt"

# 5a. Stilisztikai review Claude Code-dal
python review_with_claude.py "output\Sorozat - S01E01.hun.srt"
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_CLAUDE.txt + .json

# 5b. Stilisztikai review Gemini-vel (opcionális, párhuzamos vélemény)
python review_with_gemini.py "output\Sorozat - S01E01.hun.srt"
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_GEMINI.txt + .json

# 5c. Review-javaslatok alkalmazása (a riportokat összefésüli, deduplikálja,
#     találatonként y/n/e/q kérdéssel viszi át a fájlba, .bak mentéssel)
python apply_review.py "output\Sorozat - S01E01.hun.srt"
# vagy 5d. Ugyanez kérdés nélkül, előre elkészített döntés-fájlból
# python apply_review_auto.py "output\Sorozat - S01E01.hun.srt" decisions.json

# 7. Szegmentálás — sorhossz-riport + automatikus tördelés (a review-javítások után)
python resegment_srt.py report "output\Sorozat - S01E01.hun.srt"
python resegment_srt.py reflow "output\Sorozat - S01E01.hun.srt" -o "output\Sorozat - S01E01.hun.reflow.srt"
```

A két review script **független** — futtathatod csak az egyiket, csak a másikat,
vagy mindkettőt. A találatokat az `apply_review.py` fésüli össze és viszi át
interaktívan; kézzel is javíthatsz a riportok alapján.

### Fordítás — opciók

A fordításhoz **két alternatíva** van: a `translate_parallel.py` (Claude Code-os)
és a `translate_with_gemini.py` (Gemini API-s). Mindkettő ugyanazon a
`blocks/` mappa-szerkezeten dolgozik (`split_srt.py` outputja) és ugyanúgy
checkpoint-ol — futtathatod ugyanazon a projekten akár felváltva is.

#### Claude Code fordító (`translate_parallel.py`)
```powershell
# Egyedi blokk méret szétvágáshoz
python split_srt.py "input\eng.srt" --block-size 100

# Claude modell-választás (default: sonnet)
python translate_parallel.py "blocks\eng" --model haiku    # olcsóbb
python translate_parallel.py "blocks\eng" --model opus     # alaposabb

# Csak egy konkrét blokk újrafordítása
python translate_parallel.py "blocks\eng" --agents 1 --block 003

# Sikertelen blokkok újrafordítása — egyszerűen futtasd újra
python translate_parallel.py "blocks\eng" --agents 3
# A script automatikusan csak a hiányzó blokkokat fordítja (checkpoint).

# Hibás blokk törlése és újrafordítása
del "blocks\eng\eng_block_003_0301-0450_HUN.srt"
python translate_parallel.py "blocks\eng" --agents 1
```

#### Gemini API fordító (`translate_with_gemini.py`) — alternatíva
```powershell
# Default modell: gemini-3.1-flash-lite (gyors, olcsó)
python translate_with_gemini.py "blocks\eng" --agents 3

# Tetszőleges Gemini modell --model flag-gel
python translate_with_gemini.py "blocks\eng" --model gemini-3.1-flash
python translate_with_gemini.py "blocks\eng" --model gemini-3.1-pro-preview

# Csak egy konkrét blokk újrafordítása (auto zero-pad: 3 → 003)
python translate_with_gemini.py "blocks\eng" --agents 1 --block 3

# Checkpoint és újraindítás ugyanúgy működik mint a Claude verziónál.
```

A két fordító ugyanazt a `CLAUDE.md` + `glossary.json` kontextust adja át a
modellnek system promptként, így a fordítások konzisztensek maradnak akkor is,
ha váltogatod őket. A Gemini fordító **strukturált JSON kimenetet** ad
(Pydantic séma), és a sorszám + időbélyeg Python oldalon garantáltan
változatlan marad — a modell csak a szöveget kapja és csak szöveget ad vissza.

> **Párhuzamosság (`--agents`):** a Gemini API nem tiltja a párhuzamos hívást,
> csak RPM (requests/min) korlátok vonatkoznak rá. Free tier-en ~30 RPM a default
> modellnél; `--agents 10` fölött 429 rate limit hibákra számíthatsz, amiket a
> retry logika kezel, de pazarol API-időt. A script `--agents > 10` esetén
> figyelmeztetést is ad. Részletek:
> [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) ·
> [saját tier-limitek (AI Studio)](https://aistudio.google.com/rate-limit).

### Review — opciók

#### Claude review (`review_with_claude.py`)
```powershell
# Default modell: sonnet (default chunk-size: 100)
python review_with_claude.py "output\hun.srt"

# Modell-választás: haiku (olcsóbb), sonnet (default), opus (alaposabb)
python review_with_claude.py "output\hun.srt" --model haiku
python review_with_claude.py "output\hun.srt" --model opus

# Egyedi chunk méret
python review_with_claude.py "output\hun.srt" --chunk-size 150

# Csak egy chunk-tartomány lefuttatása (pl. megszakítás utáni pótlás)
python review_with_claude.py "output\hun.srt" --start-chunk 9 --suffix _part2
python review_with_claude.py "output\hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

# Angol forrás kézi megadása / kikapcsolása
python review_with_claude.py "output\hun.srt" --english "input\eng.srt"
python review_with_claude.py "output\hun.srt" --no-english
```

Mindkét review script automatikusan megkeresi az **angol forrás SRT-t**
(a `.hun.srt` névből `.eng.srt`-t keres az `input/` mappában, ill. a hun fájl
mellett), és minden szekció mellé odaadja a modellnek az angol eredetit is
`[EN]` sorként. Így a lektor a forráshoz tudja mérni a magyart — jelentősen
kevesebb a téves találat, és a félrefordításokat is elkapja, nem csak a
stílushibákat.

A párosítás előtt **igazítás-ellenőrzés** fut (cue-számok + időbélyeg-
szúrópróba): ha a két fájl elcsúszott egymáshoz képest (pl. a magyar
`resegment --split` után újraszámozódott), a script figyelmeztet és kihagyja
a párosítást — elcsúszott angol sorok tömeges hamis találatot adnának.
Explicit `--english` megadással felülbírálható.

Mindkét review a szöveges riport mellé **JSON riportot** is ír
(`_REVIEW_*.json`) — ezt dolgozza fel az `apply_review.py`.

#### Review-javaslatok alkalmazása (`apply_review.py`)
```powershell
# A hun.srt melletti összes riport összefésülése + interaktív alkalmazás
python apply_review.py "output\hun.srt"

# Csak megadott riportok, ill. csak listázás módosítás nélkül
python apply_review.py "output\hun.srt" "output\hun_REVIEW_GEMINI.json"
python apply_review.py "output\hun.srt" --dry-run
```

A script a Claude- és Gemini-riportokat szekciószám szerint összefésüli, az
azonos javaslatokat deduplikálja (jelölve, hogy mindkét lektor egyetért), az
eltérőeket variánsként kínálja fel. Találatonként kérdez: `y` = alkalmaz,
`1..9` = adott variáns, `e` = kézi szerkesztés, `n` = kihagy, `q` = kilépés
mentéssel. Az első módosítás előtt `.bak` mentést készít az eredetiről.

#### Nem interaktív alkalmazás (`apply_review_auto.py`)

Az `apply_review.py` minden találatnál kérdez — sok részt átnézve ez több száz
konzol-kérdés. Ha a döntéseket **előre** meghozod (magad, vagy egy agenttel,
aki a javaslatokat az angol eredetihez méri), ez a testvér-script kérdés nélkül
vezeti át őket:

```powershell
python apply_review_auto.py "output\hun.srt" decisions.json
python apply_review_auto.py "output\hun.srt" decisions.json --dry-run
```

A `decisions.json` egy egyszerű lista — szekciószám és a végleges szöveg:

```json
[
  {"sorszam": 12, "eredeti": "A régi szöveg", "javaslat": "Az új magyar szöveg"},
  {"sorszam": 40, "javaslat": "Első sor\nMásodik sor"}
]
```

A sorszám + időbélyeg itt is érintetlen marad, az első íráskor `.bak` mentés
készül, a fájlban nem létező szekciókat kihagyja és jelzi. Ami már egyezik a
javaslattal, azt nem írja újra — a script idempotens.

> **Az `eredeti` mező opcionális, de ajánlott.** Ha megadod, a script
> ellenőrzi, hogy tényleg az áll-e a fájlban — vagyis hogy a döntés-fájl
> ehhez a fájl-állapothoz készült-e —, és eltérés esetén **kihagyja** az adott
> bejegyzést. Erre azért van szükség, mert a sorszámok nem örökérvényűek: a
> `resegment_srt.py --split` újraszámozza a cue-kat, és onnantól egy korábban
> készült döntés-fájl más szekciókra mutat. Ha sok bejegyzés tér el egyszerre,
> a script külön jelzi, hogy valószínűleg ez történt. Az összehasonlítás
> whitespace-független, és a `--ignore-drift` felülbírálja.
>
> A review riportok (`_REVIEW_*.json`) amúgy is tartalmaznak `eredeti` mezőt,
> úgyhogy a döntés-fájl összeállításakor érdemes átmásolni.

> **Miért éri meg előre szűrni:** a review-modellek javaslatainak jelentős
> része téves. 10 részen mérve a `gemini-3.1-flash-lite` találatainak ~13%-a
> szó szerint azonos volt az eredetivel (no-op), és ezen felül is sokat el kell
> dobni (nem létező szóalakok, hamis tegezés/magázás-riasztások). Érdemes tehát
> a javaslatokat egyesével az **angol eredetihez** mérni, és csak a jóváhagyott
> (esetleg átírt) szöveget beírni a döntés-fájlba.

#### Gemini review (`review_with_gemini.py`)
```powershell
# Default modell: gemini-3.1-flash-lite (gyors, olcsó)
python review_with_gemini.py "output\hun.srt"

# Tetszőleges modell-azonosító --model flag-gel
python review_with_gemini.py "output\hun.srt" --model gemini-3.1-flash
python review_with_gemini.py "output\hun.srt" --model gemini-2.5-flash
python review_with_gemini.py "output\hun.srt" --model gemini-3.1-pro-preview
# Modell-lista: https://ai.google.dev/gemini-api/docs/models

# Csak egy chunk-tartomány lefuttatása (pl. kvótahiba utáni pótlás)
python review_with_gemini.py "output\hun.srt" --start-chunk 9 --suffix _part2
python review_with_gemini.py "output\hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

# Angol forrás kézi megadása / kikapcsolása
python review_with_gemini.py "output\hun.srt" --english "input\eng.srt"
python review_with_gemini.py "output\hun.srt" --no-english
```

A Gemini review **strukturált JSON kimenetet** ad (Pydantic séma), ami stabilabb
mint a szabad szöveg, és automatikusan retry-ol rate limit (429) vagy 5xx hiba esetén.
Az angol forrás párosítása itt is működik (lásd fent a Claude review-nál).

> ⚠️ **A Gemini modellek listája időről időre változik.** Új modellek jelennek
> meg, preview verziók stabilizálódnak (és a `-preview` suffix lekerül), régi
> verziók nyugdíjba mennek. A README-ben szereplő modell-példák ezért
> elavulhatnak. Mielőtt egy konkrét `--model <név>` argumentumot használsz,
> ellenőrizd az aktuálisan elérhető modelleket:
> **https://ai.google.dev/gemini-api/docs/models**
>
> Ha egy nem létező modell-azonosítót adsz át, a script API hibával fog
> visszatérni — ilyenkor a fenti oldalon nézd meg a helyes nevet.

### Gemini kvóta — mennyi hívás van még ma? (`gemini_quota.py`)

A Gemini API **nem adja vissza a maradék napi kvótát**: a Service Usage API
API-kulccsal 403-at ad, a válaszfejlécekben nincs `ratelimit-*`, a `models.get()`
csak token-limiteket ismer. A napi limitbe így csak akkor futnál bele, amikor
már megtörtént (429) — a `gemini_quota.py` ezért **helyben könyveli** a
hívásokat, és a futás előtt megmondja, belefér-e a tervezett munka.

Csak Python stdlib, nincs telepítendő függőség.

```powershell
python gemini_quota.py                  # mai fogyás modellenként
python gemini_quota.py --days 7         # utolsó 7 nap
python gemini_quota.py --projects       # projektmappa szerinti bontás is
python gemini_quota.py --model gemini-3.1-flash-lite   # csak egy modell
python gemini_quota.py --where          # hol van a napló
python gemini_quota.py --reset          # mai számlálók nullázása
python gemini_quota.py --forget-limit gemini-3.6-flash # megtanult limit elfelejtése
```

A `translate_with_gemini.py` és a `review_with_gemini.py` **automatikusan**
használja: indulás előtt kiírja a várható fogyást, és minden sikeres hívást
elkönyvel. Ha a modul hiányzik, a scriptek változatlanul futnak tovább — a
kvótakövetés kényelmi funkció, nem állíthatja meg a fordítást.

**A napló gépszintű, nem projektszintű** — ez a leggyakoribb félreértés:

```
~\.gemini_quota\usage.json          (felülírható: GEMINI_QUOTA_FILE env-változó)
```

A napi kvóta az **API kulcshoz** tartozik, nem a munkakönyvtárhoz. Ha egy gépen
több felirat-projekt fut ugyanazzal a kulccsal, mind ugyanabból a napi keretből
fogyaszt — ezért közös a napló, és a kulcs **ujjlenyomata** szerint van bontva
(maga a kulcs soha nem kerül a fájlba). A `--projects` megmutatja, melyik
mappából mennyi fogyott.

> ⚠️ **A nap nem helyi éjfélkor vált.** A Google ingyenes napi kvótája
> csendes-óceáni idő (PT) szerint nullázódik. A script PT szerint könyvel, és
> kiírja, hány óra van hátra a nullázásig.

**A limitek öntanulók — de csak a napi limit.** A Gemini többféle 429-et ad, és
csak az egyik jelenti azt, hogy elfogyott a napi keret:

| `quotaId` | Mit jelent | Mit csinál a könyvelés |
|---|---|---|
| `...PerDay...` | napi kérés-limit | megtanulja a pontos limitet, a napot kimerültnek jelöli |
| `...PerMinute...` | percenkénti rate limit | figyelmen kívül hagyja — a retry-logika átvészeli |
| `...Tokens...` | token-alapú limit | figyelmen kívül hagyja — nem kérésszám |

Ez a megkülönböztetés lényeges: magas `--agents` értéknél a percenkénti 429
rutinszerű, és ha azt napi limitnek vennénk, egy múló hiba rossz értéket égetne
be, és a nap hátralévő részére hamisan „kimerült"-nek jelölné a modellt.

A megtanult limitek **tartósak** (nem évülnek a napi számlálókkal), ezért a
`python gemini_quota.py` kiírja őket — ha valamelyik hibásnak tűnik, a
`--forget-limit <modell>` törli, és a következő valódi napi 429-nél újratanul.
Amíg nincs mért adat, becslést használ, és ezt `(becs)` jelöléssel jelzi.

> **A számláló alsó becslés, a maradék ezért felső korlát.** A naplóba csak
> azok a hívások kerülnek, amelyek ezeken a scripteken keresztül mentek ki
> **és** sikeresen vissza is tértek. Kimarad tehát: az API kulcs használata
> máshol (AI Studio webUI, curl, másik eszköz — ez a legnagyobb forrás), az
> 5xx-szel elhalt hívás, ami a szerveren már fogyaszthatott, és a válasz előtt
> megszakított futás. A 429-cel elutasított kérés viszont helyesen marad ki:
> az nem fogyaszt kvótát.
>
> A kiírások ezért „legalább ennyit használtál" / „legfeljebb ennyi maradt"
> formában fogalmaznak. Ha a könyvelés túl sokat mutat (pl. félresikerült
> teszt), a `--reset` nullázza a mai számlálókat; ha kevesebbet a valóságnál,
> azt az első napi 429 korrigálja — onnantól a maradék nullára vált.

### Szójegyzék bővítése

A `glossary_extract.py` két módban működik — a magyar argumentum dönti el, melyikben:

```powershell
# (A) Fordítás ELŐTTI mód — CSAK az angol fájl (a magyar argumentum elhagyva).
#     Az agent a CLAUDE.md szabályai alapján JAVASLATOT tesz a magyar fordításra,
#     te jóváhagyod, és a párhuzamos fordítás már egységes nevekkel/címekkel indul.
python glossary_extract.py "input\eng.srt"

# (B) Fordítás UTÁNI mód — angol-magyar pár. A "hu" a kész feliratban
#     ténylegesen használt fordítás (a meglévő viselkedés).
python glossary_extract.py "input\eng.srt" "output\hun.srt"

# Egyéni glossary útvonal (mindkét módban)
python glossary_extract.py "input\eng.srt" --glossary my_glossary.json
```

Mindkét mód interaktív: a javasolt kifejezéseket egyesével hagyod jóvá
(`y` = elfogad, `n` = elutasít, `e` = szerkeszt, `q` = kilép).

A `glossary.json`-t **mind a négy modellt hívó script** (a két fordító és a
két review) automatikusan betölti és átadja a modellnek, hogy a fordítások
konzisztensek maradjanak.

## Kontextus-átadás — fontos!

Mind a két fordító, mind a két review script átadja a **CLAUDE.md**-t és a
**glossary.json**-t system promptként a modellnek:

| Script | Mechanizmus |
|--------|-------------|
| `translate_parallel.py` | `--append-system-prompt-file` (Claude Code) |
| `translate_with_gemini.py` | `system_instruction` (Gemini API) |
| `review_with_claude.py` | `--append-system-prompt-file` (Claude Code) |
| `review_with_gemini.py` | `system_instruction` (Gemini API) |

**Következmény:** ha bővíted a CLAUDE.md-t (új szabály) vagy a glossary-t,
a változás a következő futáskor automatikusan érvényesül — a translate-nél
és a review-nál is. Külön beállítás nem kell.

## Tippek

- **Agent szám:** 3 az ajánlott. 5-nél fölött API rate limit jöhet, üres válasszal.
- **Blokk méret:** 150 az alapértelmezett. Ha sok a hiba, csökkentsd 100-ra.
- **CLAUDE.md:** Minél részletesebb az "Aktuális sorozat adatai" rész, annál jobb
  a fordítás minősége (karakter-háttér, formalitás-szintek, kontextus).
- **Checkpoint:** mindkét fordító fájl-alapú checkpointtal fut (újraindításkor
  csak a hiányzó blokkokat fordítja; a szekció-eltéréses blokk outputja
  törlődik, így az is újramegy), mindkét review pedig `--start-chunk` /
  `--end-chunk` / `--suffix` kapcsolókkal folytatható. A `merge_srt.py`
  `--force` kapcsolóval hiányzó blokkok mellett is összefűz (a hiányt listázza).
- **Fordító finomhangolás:** `translate_parallel.py --timeout <mp>` (default
  900), `--max-turns <n>` (default 20, futó-galopp elleni plafon),
  `--no-cleanup` (régi sys-prompt fájlok megtartása); `glossary_extract.py
  --timeout <mp>` (default 300).
- **Két review összevetése:** ugyanazon a fájlon futtasd mindkét review-t —
  a két modell más-más típusú hibákat talál (Claude inkább kontextus,
  Gemini inkább morfológia / ikes igék).
- **Review modell-választás — tapasztalati javaslat:** kezdetben Claude
  Opus-szal (`review_with_claude.py`) review-oztam, ami minőségileg jó,
  de drága. Később átálltam a Gemini API-ra (`review_with_gemini.py`,
  jelenlegi default: `gemini-3.1-flash-lite`), és nem bántam meg —
  töredék költséggel hasonló minőséget ad a felirat-review feladathoz.
  Ha most kezdesz, érdemes Gemini-vel próbálkozni elsőként.
- **Gemini napi limit:** ingyenes szinten a `-lite` modellek bőkezűek, a
  nem-lite modellek viszont tapasztalat szerint napi ~20 kérésnél elfogynak —
  **modellenként külön**, ezért modellváltással aznap tovább lehet dolgozni.
  (Nagyságrend: egy ~400 szekciós rész review-ja 4-5 kérés.) Hogy hol tartasz:
  `python gemini_quota.py`. Ha egy hosszú futás közben fogyna el, a review
  `--start-chunk` / `--end-chunk` / `--suffix` kapcsolókkal folytatható.
- **Prompt cache:** a `translate_parallel.py` a system promptot tartalom-hash
  alapján fájlba menti, így a párhuzamos agent-ek és az ismételt futások is
  cache-hit-tel indulhatnak — drasztikus költségcsökkenés.

## Utómunka — a review után

A review riport (`_REVIEW_CLAUDE.txt` / `_REVIEW_GEMINI.txt`) csak **jelzi**
a hibákat — a javítást neked kell elvégezni. A teljes folyamat innen még
négy lépés:

### 1. Review-hibák javítása

A riportban listázott hibákat háromféleképpen javíthatod:

- **Interaktívan** (`apply_review.py`): a script összefésüli a riportokat és
  találatonként megkérdezi, alkalmazza-e. A legegyszerűbb út, de sok részen
  több száz kérdés.
- **Döntés-fájllal** (`apply_review_auto.py`): a javaslatokat előre átnézed —
  magad, vagy egy agenttel, aki mindegyiket az angol eredetihez méri —, és a
  jóváhagyott szövegeket egy `decisions.json`-ben adod át. Kérdés nélkül fut le.
  Ez az ajánlott út, ha több részt viszel át egyszerre; a szűrés miért fontos,
  arról lásd fent a script szakaszát.
- **Manuálisan**: szövegszerkesztőben (VSCode, Notepad++, Subtitle Edit,
  stb.) sorszám szerint megkeresed és javítod.

> **Sorrend:** a review-javításokat a szegmentálás (2. lépés) **előtt** vidd át.
> A `resegment --split` újraszámozhatja a cue-kat, és onnantól a riportok
> sorszámai már nem a régi szekciókra mutatnak. Az `apply_review_auto.py` ezt
> észreveszi, ha a döntés-fájlban megadod az `eredeti` mezőt.

### 2. Automatikus szegmentálás — `resegment_srt.py`

A **sorhossz** (max karakter/sor) technikai rendezését a `resegment_srt.py`
determinisztikusan automatizálja — így jóval kevesebb kézi munka marad a
Subtitle Edit-nek. Csak Python stdlib, nincs telepítendő függőség.

```powershell
# QA-riport (csak olvasás): mely cue-k sértik a plafont (CPS / sorhossz / rés)
python resegment_srt.py report "output\Sorozat - S01E01.hun.srt"

# Sorhossz-tisztítás (időzítést NEM változtat) -> új fájl
python resegment_srt.py reflow "output\Sorozat - S01E01.hun.srt" -o "output\Sorozat - S01E01.hun.reflow.srt"

# Ha kell: a 2 sorba nem férő cue-k idő-arányos bontása (cue-számot változtat)
python resegment_srt.py reflow "output\Sorozat - S01E01.hun.srt" --split -o "...reflow.srt"
```

A `reflow` kiegyensúlyozott ≤2 sorra tördel, mondat-/tagmondat-határon; a
`szám+időbélyeg` sorokat **bitre változatlanul** hagyja, a `<i>` és `- `
párbeszéd-jelöléseket megőrzi; **idempotens**. Részletes leírás (töréspont-
logika, plafonok, más nyelvhez igazítás): **`resegment_srt.md`**.

### 3. Technikai javítás Subtitle Edit-tel

A sorhosszt a 2. lépés már rendezte — itt főleg az **olvasási sebesség (CPS)**
és az időzítés marad. Ezt a [Subtitle Edit](https://www.nikse.dk/subtitleedit)
(ingyenes, Windows + Mac) intézi:

- **CPS (Characters Per Second)** — túl gyors feliratok jelzése
- **Min/max megjelenési idő** ellenőrzés
- **Átfedések** detektálása
- **Sortörés-optimalizálás** (max sor-hossz)
- **Helyesírás-ellenőrzés** magyar nyelvre

Tools → "Fix common errors" / "Apply min duration" / stb. funkciókkal
automatikusan vagy félautomatikusan rendezhető.

### 4. Végső kézi lektorálás

A fordító és a review modellek sosem tökéletesek, és az automatikus
javítás után is érdemes egyszer **végigolvasni** a kész feliratot —
ideálisan a videóval szinkronban, lejátszás közben. Ekkor jönnek elő
azok a finomságok (kontextus-érzékeny tegezés/magázás, karakterek
beszédstílusa, dialógus-ritmus), amiket egyik LLM sem fog megbízhatóan.

Ez a négy utómunka-lépés teszi teljessé a folyamatot — nélkülük a fordítás
nyelvileg jó lehet, de a néző-élmény nem lesz az.

## Hivatkozott dokumentumok

- `CLAUDE.md` — fordítási szabályok, sorozat-kontextus sablon
- `lepesek.txt` — gyors parancs-cheatsheet
- `resegment_srt.md` — a szegmentáló eszköz (`resegment_srt.py`) részletes leírása
- `proposals/` — fejlesztési irányok, alternatívák, tervezési dokumentumok
  (lásd: [`proposals/README.md`](proposals/README.md))
