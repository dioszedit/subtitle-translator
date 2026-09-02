# SRT Felirat Fordító — Claude, Gemini, Codex és Grok

SRT felirat-fordítási keretrendszer LLM-alapú fordítással és stilisztikai review-val.
A workflow Claude Code-, Gemini API-, Codex CLI- és Grok CLI-providerrel futtatható.

**Irány:** forrásnyelvből magyarra. A **célnyelv fixen magyar** — a fordító és a
review promptok magyar nyelvre vannak megírva, ez nem paraméter. A **forrásnyelv
alapból angol**, de bármelyik támogatott nyelv lehet: a fájlnév `.kód` tagjából
(`.eng`, `.ger`, `.kor`, …) minden lépés automatikusan felismeri, és a promptok
ehhez igazodnak — részletek a *Forrásnyelv* szakaszban.

**Tipikus use-case:** sorozat-feliratok fordítása (pl. koreai és más ázsiai drámák),
ahol fontos a karakterek, megszólítások és kulturális kifejezések konzisztens
kezelése — de a keretrendszer bármilyen videó/film/sorozat-felirathoz használható.

> **AI-asszisztált projekt, MIT licenc.** A kód túlnyomó része Claude Code-dal
> (részben Codex CLI-vel) készült, emberi irányítás és tesztelés mellett; bárki
> szabadon használhatja. Részletek: [*Hogyan készült*](#hogyan-készült--ai-asszisztált-fejlesztés)
> és [*Licenc*](#licenc).

## Mappaszerkezet

```
subtitle-translator/
├── TRANSLATION.md               ← Közös fordítási szabályok és sorozat-kontekstus
├── CLAUDE.md                    ← Claude Code belépési pont a közös szabályzathoz
├── AGENTS.md                    ← Codex projektutasítások
├── glossary.json                ← Fordítási szójegyzék (kézzel validált)
├── .env.example                 ← .env sablon: Gemini API kulcs, modell-defaultok, default provider
├── .gitignore                   ← Mit ne commit-oljunk
│
├── subtr.py                     ← Egyparancsos CLI — minden lépés ezen keresztül fut
│                                  (split, glossary, register, translate, merge,
│                                  verify, review, apply, apply-auto, resegment, quota)
│
├── subtr/                       ← A tényleges fordítás- és review-logika
│   ├── config.py                ← .env betöltése, modell- és forrásnyelv-feloldás, API-kulcsok
│   ├── srt.py                   ← SRT parser
│   ├── blocks.py                ← Blokk-alapú szegmentálás
│   ├── context.py               ← TRANSLATION.md + glossary.json beolvasása
│   ├── glossary.py              ← glossary.json kezelés
│   ├── reports.py               ← Review riportok szerializálása
│   ├── quota.py                 ← Gemini kvóta-számlálás
│   ├── providers/               ← Provider adapterek
│   │   ├── gemini.py            ← Gemini API + retry + kvótakezelés
│   │   ├── claude_cli.py        ← Claude Code wrapper
│   │   ├── codex_cli.py         ← Codex CLI wrapper
│   │   └── grok_cli.py          ← Grok CLI wrapper
│   └── tasks/                   ← Egy fájl = egy subtr parancs
│       ├── split.py             ← split: SRT → blokkok
│       ├── translate.py         ← translate: közös fordítási prompt és feldolgozás
│       ├── merge.py             ← merge: blokkok → egy SRT
│       ├── verify.py            ← verify: strukturális ellenőrzés
│       ├── review.py            ← review: közös review-prompt és feldolgozás
│       ├── apply_review.py      ← apply: riportok összefésülése, interaktív átvezetés
│       ├── apply_review_auto.py ← apply-auto: átvezetés döntés-fájlból
│       ├── resegment.py         ← resegment: sorhossz-riport / újratördelés
│       ├── glossary_extract.py  ← glossary: szójegyzék bővítés
│       └── register_extract.py  ← register: regiszter kinyerés
│
├── addons/                      ← Opcionális segédscriptek (saját READMÉ-kkel)
│   ├── mdl-init/                ← 0/a: új sorozat — TRANSLATION.local.md + glossary-címek MyDramaList-linkből
│   ├── srt-preclean/            ← 0/b: SDH-forrás előtisztítása
│   └── vtt2srt/                 ← 0/d: meglévő .vtt felirat átvétele (WebVTT → SRT)

├── input/                       ← Ide tedd a forrásnyelvi SRT fájlokat
├── blocks/                      ← Auto-generált blokk-fájlok
├── output/                      ← Kész magyar fájlok + review riportok
│
├── proposals/                   ← Fejlesztési irányok, alternatívák, tervek
│                                  (saját README a részletekhez)
└── steps.txt                  ← Quick-reference parancslista
```

A **`subtr.py`** a repo gyökeréből fut, és minden alparancsa a `subtr/` csomag
logikáját használja. Ez egy tudatos refaktor-döntés: korábban a glossary-betöltő
logika 6 különálló scriptben élt egyszerre, és a másolatok szétcsúsztak. Most a
valódi logika egyetlen helyen van (`subtr/`), az alparancsok csak vékony
kapcsolódási pontok, és az update-ek mindegyikre azonnal érvényesek.

Az `input/`, `output/`, `blocks/` mappák tartalma nem kerül a git repóba —
projektenként / epizódonként más, és gyakran szerzői jogi védettség alá esik.

## Előfeltételek

- **Python 3.10+**
- **Claude Code CLI** (`claude` parancs, opcionális) — a Claude providerhez
- **Gemini API kulcs** (opcionális) — ha Gemini-vel fordítasz vagy review-zol (`subtr.py translate --provider gemini` / `subtr.py review --provider gemini`)
- **Codex CLI** (`codex` parancs, opcionális) — a Codex providerhez. Bejelentkezett CLI-t használ; külön Python-csomag nem kell.
- **Grok CLI** (`grok` parancs, opcionális) — a Grok providerhez. Bejelentkezett CLI (`grok login`) vagy `XAI_API_KEY`; külön Python-csomag nem kell.
- **Git** (opcionális) — verziókezeléshez

## Telepítés

### Új gépen — clone GitHub-ról

```powershell
git clone https://github.com/dioszedit/subtitle-translator.git
cd subtitle-translator

# Gemini-provideres parancsok függőségei (translate --provider gemini és/vagy review --provider gemini)
pip install google-genai python-dotenv pydantic

# .env létrehozása a sablonból
copy .env.example .env
# Szerkeszd: GEMINI_API_KEY=...   (https://aistudio.google.com/apikey)
```

> Opcionális: `pip install -e .` után a parancs `subtr <parancs> ...` alakban is
> hívható (meg `python -m subtr`-ként) — a README a `python subtr.py` formát
> használja, mert az telepítés nélkül is működik.

> **macOS / Linux megjegyzés:** a README parancsai Windows PowerShell-re vannak
> írva. Más platformon a következő helyettesítések kellenek:
>
> | Windows | macOS / Linux |
> |---------|---------------|
> | `python` | `python3` |
> | `pip` | `pip3` |
> | `py` (steps.txt-ben) | `python3` |
> | `copy` | `cp` |
> | `del` | `rm` |
> | `input\fájl.srt` (backslash) | `input/fájl.srt` (forward slash) |
>
> Pl. macOS-en:
> ```bash
> pip3 install google-genai python-dotenv pydantic
> cp .env.example .env
> python3 subtr.py split "input/Sorozat - S01E01.eng.srt"
> ```

### Új projekt indítása

1. A clone-olt mappát használhatod közvetlenül, vagy másolhatod egy új mappába
   sorozatonként (ha külön repóként akarsz több sorozatot vezetni).
2. Hozd létre a gitignore-os `TRANSLATION.local.md` fájlt. Ha a sorozat fent
   van a MyDramaList-en, ezt megcsinálja helyetted az `mdl-init` add-on
   (részletek: [`addons/mdl-init/README.md`](addons/mdl-init/README.md)):

   ```powershell
   pip install -e ".[addons]"
   py addons\mdl-init\init_local.py https://mydramalist.com/70241-ni-ye-you-jin-tian
   ```

   Enélkül másold a `TRANSLATION.md` „Aktuális sorozat adatai” sablonját a
   fájlba kézzel. Mindkét esetben neked kell kitöltened a magyar címet, a
   *Megszólítási regisztert* és a speciális kifejezéseket — a scraper ezeket
   `TODO:` sorként hagyja benne.

   Az add-on a `glossary.json`-ba is felveszi a **sorozat és a forrásmű címét**,
   hogy a fordító ne próbálkozzon a lefordításukkal. Szereplőneveket
   szándékosan nem — azokat a 1.5 lépés (`subtr.py glossary`) szedi ki magából
   a feliratból, a tényleges írásmódjukkal.
3. Tedd a forrásnyelvi SRT fájlt az `input/` mappába, `.eng.srt` végződéssel
   (vagy más nyelvnél a megfelelő kóddal — lásd [Forrásnyelv](#forrásnyelv)).

### Meglévő fordítás átvétele (vtt-import)

Ha egy sorozat korábbi részei **már le vannak fordítva** más forrásból (pl.
`.vtt`-ben), és csak a maradékot fordítod a pipeline-nal, a következetesség
három lépésben vihető át — részletek:
[`addons/vtt2srt/README.md`](addons/vtt2srt/README.md).

1. `python3 addons/vtt2srt/vtt2srt.py …/*.vtt` — a pipeline SRT-t vár; a
   konverter az időzítést és a szöveget (`<i>`, `♫`, `[kártyák]`) változatlanul
   viszi, csak újraszámoz és a `.`→`,` cserét végzi el az időbélyegben.
2. `python3 subtr.py glossary "input/…EXX.eng.srt" "…/…EXX.hun.srt"` — a
   [szójegyzék utólagos módja](#szójegyzék-bővítése) a **ténylegesen használt**
   magyar alakot tanulja meg. A párosítás sorszám szerint megy, ezért az angol
   és a magyar fájl cue-számának egyeznie kell.
3. `python3 subtr.py register "…/…EXX.hun.srt" --hungarian` — a
   [regiszter-kinyerés](#megszólítási-regiszter-kinyerése-subtrpy-register--opcionális)
   a kész magyar szövegből dolgozik: a tegezés/magázás ott nem következtetés,
   hanem a magyar igealak leolvasása.

## Használat (PowerShell)

### Teljes folyamat (egy epizód)

```powershell
# 1. Szétvágás blokkokra (alapból 150 szekciónként)
python subtr.py split "input\Sorozat - S01E01.eng.srt"
# Újra-splitnél (pl. más --block-size) --clean törli a régi blokkokat —
# enélkül a parancs leáll, hogy a két generáció ne keveredjen a merge-nél

# 2. Fordítás — a --provider választja ki a fordítót (default: claude)
python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider claude --agents 3
# vagy Gemini API-val (olcsóbb alternatíva, ugyanazokat a blokkokat dolgozza fel)
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider gemini --agents 3
# vagy Codex CLI-vel — első futáskor egy blokkot, egy agenttel ellenőrizz
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider codex --block 1 --agents 1
# vagy Grok CLI-vel (fordítás default: grok-4.5)
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider grok --block 1 --agents 1

# 3. Összefűzés egy fájlba
python subtr.py merge "blocks\Sorozat - S01E01.eng" "output\Sorozat - S01E01.hun.srt"

# 4. Strukturális ellenőrzés (sorszámok, időbélyegek, szekciószámok)
python subtr.py verify "input\Sorozat - S01E01.eng.srt" "output\Sorozat - S01E01.hun.srt"

# 5. Stilisztikai review — a default provider gemini, --provider-rel válthatsz
python subtr.py review "output\Sorozat - S01E01.hun.srt"
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_GEMINI.txt + .json

# vagy Claude Code-dal
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider claude
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_CLAUDE.txt + .json

# vagy Codex CLI-vel
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider codex
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_CODEX.txt + .json

# vagy Grok CLI-vel (review default: grok-4.6)
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider grok
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_GROK.txt + .json

# 5b. Review-javaslatok alkalmazása (a riportokat összefésüli, deduplikálja,
#     találatonként y/n/e/q kérdéssel viszi át a fájlba, .bak mentéssel)
python subtr.py apply "output\Sorozat - S01E01.hun.srt"
# vagy 5c. Ugyanez kérdés nélkül, előre elkészített döntés-fájlból
# python subtr.py apply-auto "output\Sorozat - S01E01.hun.srt" decisions.json

# 7. Szegmentálás — sorhossz-riport + automatikus tördelés (a review-javítások után)
python subtr.py resegment report "output\Sorozat - S01E01.hun.srt"
python subtr.py resegment reflow "output\Sorozat - S01E01.hun.srt" -o "output\Sorozat - S01E01.hun.reflow.srt"
```

A review parancs **négy providere** — Gemini (default), Claude, Codex, Grok —
**független** egymástól: futtathatod csak az egyiket vagy többet, `--provider`-rel
váltva. A találatokat a `subtr.py apply` fésüli össze és viszi át
interaktívan; kézzel is javíthatsz a riportok alapján.

### Forrásnyelv

A pipeline alapesetben **angol** feliratból fordít, de nem minden epizódhoz van
használható angol sáv — előfordul, hogy a kiadó rossz sávot muxol be, vagy egy
adott release-ben egyszerűen nincs angol felirat. Ilyenkor másik nyelvből is
lehet fordítani; a fordító-, review-, glossary- és regiszter-promptok
mindegyike a tényleges forrásnyelvhez igazodik.

#### Hogyan derül ki a forrásnyelv?

Feloldási sorrend (a legerősebb nyer):

| # | Forrás | Példa |
|---|---|---|
| 1 | `--source-lang` kapcsoló | `--source-lang ger` |
| 2 | `SUBTR_SOURCE_LANG` env | `SUBTR_SOURCE_LANG=ger` |
| 3 | **a fájlnév `.kód` tagja** | `input/Sorozat - S01E02.ger.srt` |
| 4 | alapértelmezés | `eng` |

A 3. pont miatt a legtöbb esetben **nem kell semmit beállítani**: elég a
megszokott névkonvenció szerint elnevezni a fájlt. A `split` a blokkmappa nevét
is a fájlnévből képzi (`blocks/Sorozat - S01E02.ger`), így a `translate` is
felismeri.

```powershell
# Nincs teendő — a .ger tagból jön a nyelv
python subtr.py split "input\Sorozat - S01E02.ger.srt"
python subtr.py translate "blocks\Sorozat - S01E02.ger" --provider claude
python subtr.py review "output\Sorozat - S01E02.hun.srt"

# Kézi felülbírálás, ha a fájlnév nem árulkodik
python subtr.py translate "blocks\Sorozat - S01E02" --source-lang ger
```

Támogatott kódok (ISO 639-2/B — ugyanaz, amit az mkv-k a feliratsávokon
használnak): `ara`, `chi`, `eng`, `fre`, `ger`, `hin`, `ind`, `ita`, `jpn`,
`kor`, `may`, `pol`, `por`, `rus`, `spa`, `tha`, `tur`, `vie`. Az ISO 639-1
rövidítések (`de`, `fr`, `zh`, …) is elfogadottak.

#### Miért számít ez a tegezés/magázásnál?

Az angol `you` **nem jelöli a formalitást**, ezért a magyar tegezés/magázás
döntést a pipeline közvetett jelekből következteti ki — vagy kikerüli. A legtöbb
más forrásnyelv viszont grammatikailag jelöli: német `Sie`/`du`, kínai `您`/`你`,
olasz `Lei`/`tu`, japán keigo, koreai beszédszintek.

Ahol van ilyen jel, ott a promptok **átfordulnak**: a modellnek nem
következtetnie kell, hanem leolvasnia — és a `register` parancs a
formalitás-alakot idézhető bizonyítékként kezeli. Ilyenkor a nem angol forrás
nemcsak pótlék, hanem **pontosabb** is az angolnál.

```powershell
# A regiszter a német Sie/du alapján áll össze, nem találgatásból
python subtr.py register "input\Sorozat - S01E02.ger.srt"
```

Új nyelv felvétele: `subtr/config.py` → `SOURCE_LANGS` (magyar név +
a formalitás-jelölés leírása; `None`, ha a nyelv nem jelöli).

### Fordítás — opciók

A fordításhoz **négy alternatíva** van: a Claude Code-, a Gemini API-, a Codex
CLI- és a Grok CLI-provider — mind a `subtr.py translate --provider <claude|gemini|codex|grok>`
parancson keresztül érhető el. Mindegyik ugyanazon a `blocks/` mappa-szerkezeten
dolgozik (`subtr.py split` outputja) és ugyanúgy checkpoint-ol — futtathatod
ugyanazon a projekten akár felváltva is.

#### Claude Code fordító (`subtr.py translate --provider claude`)
```powershell
# Egyedi blokk méret szétvágáshoz
python subtr.py split "input\eng.srt" --block-size 100

# Claude modell-választás (default: sonnet)
python subtr.py translate "blocks\eng" --provider claude --model haiku    # olcsóbb
python subtr.py translate "blocks\eng" --provider claude --model opus     # alaposabb

# Csak egy konkrét blokk újrafordítása
python subtr.py translate "blocks\eng" --provider claude --agents 1 --block 003

# Sikertelen blokkok újrafordítása — egyszerűen futtasd újra
python subtr.py translate "blocks\eng" --provider claude --agents 3
# A parancs automatikusan csak a hiányzó blokkokat fordítja (checkpoint).

# Hibás blokk törlése és újrafordítása
del "blocks\eng\eng_block_003_0301-0450_HUN.srt"
python subtr.py translate "blocks\eng" --provider claude --agents 1
```

> A Claude-ág egy ismert CLI-mellékhatást magától javít: ha az agent a Read tool
> `sorszám<TAB>tartalom` megjelenítését másolja a kimenetbe (minden sor elé
> sorszám kerül), a parancs a prefixeket leszedi és `(Read-sorszámprefix
> eltávolítva)` üzenettel elfogadja a blokkot — a fordítás ilyenkor jó, csak a
> szerializálás romlott el.

#### Gemini API fordító (`subtr.py translate --provider gemini`) — alternatíva
```powershell
# Default modell: gemini-3.6-flash (erős és stabilan elérhető)
python subtr.py translate "blocks\eng" --provider gemini --agents 3

# Tetszőleges Gemini modell --model flag-gel
python subtr.py translate "blocks\eng" --provider gemini --model gemini-3.7-flash
python subtr.py translate "blocks\eng" --provider gemini --model gemini-3.5-flash-lite   # olcsó, bő napi kvóta
python subtr.py translate "blocks\eng" --provider gemini --model gemini-3.1-pro-preview

# Csak egy konkrét blokk újrafordítása (auto zero-pad: 3 → 003)
python subtr.py translate "blocks\eng" --provider gemini --agents 1 --block 3

# Checkpoint és újraindítás ugyanúgy működik mint a Claude-ágnál.
```

#### Codex fordító (`subtr.py translate --provider codex`) — alternatíva
```powershell
# Első futás: egy blokk, egy agent — ellenőrizd a kimenetet subtr.py verify-jal
python subtr.py translate "blocks\eng" --provider codex --block 1 --agents 1

# Ezután a hiányzó blokkok fordítása checkpointtal
python subtr.py translate "blocks\eng" --provider codex --agents 1

# Opcionális modell és óvatos párhuzamosítás
python subtr.py translate "blocks\eng" --provider codex --agents 2 --model gpt-5.6-terra
```

#### Grok fordító (`subtr.py translate --provider grok`) — alternatíva
```powershell
# Default modell: grok-4.5. Előfeltétel: `grok` a PATH-on, `grok login` vagy XAI_API_KEY.
# Első futás: egy blokk, egy agent
python subtr.py translate "blocks\eng" --provider grok --block 1 --agents 1

# Hiányzó blokkok checkpointtal
python subtr.py translate "blocks\eng" --provider grok --agents 1

# Erősebb modell, ha kell
python subtr.py translate "blocks\eng" --provider grok --model grok-4.6
```

A fordító-ágak ugyanazt a `TRANSLATION.md` + `glossary.json` kontextust adják át a
modellnek system promptként, így a fordítások konzisztensek maradnak akkor is,
ha váltogatod őket. A Gemini-ág **strukturált JSON kimenetet** ad
(Pydantic séma), és a sorszám + időbélyeg Python oldalon garantáltan
változatlan marad — a modell csak a szöveget kapja és csak szöveget ad vissza.

> **Párhuzamosság (`--agents`):** a Gemini API nem tiltja a párhuzamos hívást,
> csak RPM (requests/min) korlátok vonatkoznak rá. Free tier-en ~10-30 RPM
> modelltől függően; `--agents 10` fölött 429 rate limit hibákra számíthatsz, amiket a
> retry logika kezel, de pazarol API-időt. A parancs `--agents > 10` esetén
> figyelmeztetést is ad. Részletek:
> [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) ·
> [saját tier-limitek (AI Studio)](https://aistudio.google.com/rate-limit).

### Review — opciók

#### Claude review (`subtr.py review --provider claude`)
```powershell
# Default modell: sonnet (default chunk-size: 100)
python subtr.py review "output\hun.srt" --provider claude

# Modell-választás: haiku (olcsóbb), sonnet (default), opus (alaposabb)
python subtr.py review "output\hun.srt" --provider claude --model haiku
python subtr.py review "output\hun.srt" --provider claude --model opus

# Egyedi chunk méret
python subtr.py review "output\hun.srt" --provider claude --chunk-size 150

# Csak egy chunk-tartomány lefuttatása (pl. megszakítás utáni pótlás)
python subtr.py review "output\hun.srt" --provider claude --start-chunk 9 --suffix _part2
python subtr.py review "output\hun.srt" --provider claude --start-chunk 5 --end-chunk 7 --suffix _part2

# Forrásnyelvi SRT kézi megadása / kikapcsolása
python subtr.py review "output\hun.srt" --provider claude --source "input\eng.srt"
python subtr.py review "output\hun.srt" --provider claude --no-source
```

#### Grok review (`subtr.py review --provider grok`)
```powershell
# Default modell: grok-4.6
python subtr.py review "output\hun.srt" --provider grok
python subtr.py review "output\hun.srt" --provider grok --model grok-4.5
```

A review minden providernél automatikusan megkeresi a **forrásnyelvi SRT-t**
(a `.hun.srt` névből `.eng.srt`-t, `.ger.srt`-t stb. keres az `input/`
mappában, ill. a hun fájl mellett — az összes ismert nyelvkódot végigpróbálja),
és minden szekció mellé odaadja a modellnek a forrás eredetit is
`[FORRÁS]` sorként. Így a lektor a forráshoz tudja mérni a magyart — jelentősen
kevesebb a téves találat, és a félrefordításokat is elkapja, nem csak a
stílushibákat.

A `--source` kapcsoló **nyelvfüggetlen**: bármilyen forrásnyelvi SRT-t elfogad.
(A kapcsoló régi neve `--english` volt; aliasként továbbra is működik, de az új
név a helyes.) A megtalált fájl nevéből a review a **forrásnyelvet is felismeri**,
és eszerint fogalmazza a lektor-promptot — lásd [Forrásnyelv](#forrásnyelv).

A párosítás előtt **igazítás-ellenőrzés** fut (cue-számok + időbélyeg-
szúrópróba): ha a két fájl elcsúszott egymáshoz képest (pl. a magyar
`resegment --split` után újraszámozódott), a parancs figyelmeztet és kihagyja
a párosítást — elcsúszott forrássorok tömeges hamis találatot adnának.
Explicit `--source` megadással felülbírálható.

A review minden providernél a szöveges riport mellé **JSON riportot** is ír
(`_REVIEW_*.json`) — ezt dolgozza fel a `subtr.py apply`.

#### Review-javaslatok alkalmazása (`subtr.py apply`)
```powershell
# A hun.srt melletti összes riport összefésülése + interaktív alkalmazás
python subtr.py apply "output\hun.srt"

# Csak megadott riportok, ill. csak listázás módosítás nélkül
python subtr.py apply "output\hun.srt" "output\hun_REVIEW_GEMINI.json"
python subtr.py apply "output\hun.srt" --dry-run
```

A parancs a Claude-, Gemini-, Codex- és Grok-riportokat szekciószám szerint összefésüli, az
azonos javaslatokat deduplikálja (jelölve, hogy mindkét lektor egyetért), az
eltérőeket variánsként kínálja fel. Találatonként kérdez: `y` = alkalmaz,
`1..9` = adott variáns, `e` = kézi szerkesztés, `n` = kihagy, `q` = kilépés
mentéssel. Az első módosítás előtt `.bak` mentést készít az eredetiről.

#### Nem interaktív alkalmazás (`subtr.py apply-auto`)

A `subtr.py apply` minden találatnál kérdez — sok részt átnézve ez több száz
konzol-kérdés. Ha a döntéseket **előre** meghozod (magad, vagy egy agenttel,
aki a javaslatokat az angol eredetihez méri), ez a testvér-parancs kérdés nélkül
vezeti át őket:

```powershell
python subtr.py apply-auto "output\hun.srt" decisions.json
python subtr.py apply-auto "output\hun.srt" decisions.json --dry-run
```

A döntés-fájl neve szabad (a `/review-triage` skill pl. `<stem>_decisions.json`
néven, a hun.srt mellé írja) — a tartalma egy egyszerű lista: szekciószám és a
végleges szöveg:

```json
[
  {"sorszam": 12, "eredeti": "A régi szöveg", "javaslat": "Az új magyar szöveg"},
  {"sorszam": 40, "javaslat": "Első sor\nMásodik sor"}
]
```

A sorszám + időbélyeg itt is érintetlen marad, az első íráskor `.bak` mentés
készül, a fájlban nem létező szekciókat kihagyja és jelzi. Ami már egyezik a
javaslattal, azt nem írja újra — a parancs idempotens.

> **Az `eredeti` mező opcionális, de ajánlott.** Ha megadod, a parancs
> ellenőrzi, hogy tényleg az áll-e a fájlban — vagyis hogy a döntés-fájl
> ehhez a fájl-állapothoz készült-e —, és eltérés esetén **kihagyja** az adott
> bejegyzést. Erre azért van szükség, mert a sorszámok nem örökérvényűek: a
> `subtr.py resegment reflow --split` újraszámozza a cue-kat, és onnantól egy korábban
> készült döntés-fájl más szekciókra mutat. Ha sok bejegyzés tér el egyszerre,
> a parancs külön jelzi, hogy valószínűleg ez történt. Az összehasonlítás
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
>
> Ezt a szűrési folyamatot a **`/review-triage`** skill automatizálja Claude
> Code-ban (lásd a *Claude Code skillek* szakaszt).

#### Gemini review (`subtr.py review` — a default provider)
```powershell
# Default modell: gemini-3.6-flash (erős és stabilan elérhető)
python subtr.py review "output\hun.srt"

# Tetszőleges modell-azonosító --model flag-gel
python subtr.py review "output\hun.srt" --model gemini-3.7-flash
python subtr.py review "output\hun.srt" --model gemini-3.5-flash-lite   # olcsó, bő napi kvóta
python subtr.py review "output\hun.srt" --model gemini-3.1-pro-preview
# Modell-lista: https://ai.google.dev/gemini-api/docs/models

# Csak egy chunk-tartomány lefuttatása (pl. kvótahiba utáni pótlás)
python subtr.py review "output\hun.srt" --start-chunk 9 --suffix _part2
python subtr.py review "output\hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

# Forrásnyelvi SRT kézi megadása / kikapcsolása
python subtr.py review "output\hun.srt" --source "input\eng.srt"
python subtr.py review "output\hun.srt" --no-source
```

A Gemini-ág **strukturált JSON kimenetet** ad (Pydantic séma), ami stabilabb
mint a szabad szöveg, és automatikusan retry-ol rate limit (429) vagy 5xx hiba esetén.
A forrásnyelvi SRT párosítása itt is működik (lásd fent a Claude review-nál).

#### Gemini modellek — mit érdemes választani

| Modell | Mire jó |
|---|---|
| `gemini-3.6-flash` | **Default** a fordításban és a review-ban is. Erős és — a 3.7-tel ellentétben — stabilan elérhető. |
| `gemini-3.7-flash` | A legújabb Flash, papíron a legerősebb, de a gyakorlatban rendszeresen `503 UNAVAILABLE` („high demand") — több egymást követő próbálkozás sem ment át rajta, ezért nem default. Érdemes időnként újrapróbálni. |
| `gemini-3.5-flash` | Előző Flash generáció, ha a 3.6-nál kvótába futsz. |
| `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` | Olcsó, gyors, **bő napi kvóta** free tier-en. Nagy tömegű fordításra, illetve ha a nem-lite napi limit elfogyott. |
| `gemini-3.1-pro-preview` | Pro (preview) — a legerősebb, de lassabb és szűkösebb kvótájú. Nehéz részekhez. |
| `gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-pro-latest` | Alias-ok, mindig az adott sáv legújabb kiadására mutatnak. Kényelmes, de nem determinisztikus (kiadásváltáskor csendben más modellt kapsz). |

A pontos, aktuális listát a saját kulcsoddal is le tudod kérni:

```powershell
curl "https://generativelanguage.googleapis.com/v1beta/models?key=%GEMINI_API_KEY%"
```

> ⚠️ **A Gemini modellek listája időről időre változik.** Új modellek jelennek
> meg, preview verziók stabilizálódnak (és a `-preview` suffix lekerül), régi
> verziók nyugdíjba mennek. A README-ben szereplő modell-példák ezért
> elavulhatnak. Mielőtt egy konkrét `--model <név>` argumentumot használsz,
> ellenőrizd az aktuálisan elérhető modelleket:
> **https://ai.google.dev/gemini-api/docs/models**
>
> Ha egy nem létező modell-azonosítót adsz át, a parancs API hibával fog
> visszatérni — ilyenkor a fenti oldalon nézd meg a helyes nevet.

### Gemini kvóta — mennyi hívás van még ma? (`subtr.py quota`)

A Gemini API **nem adja vissza a maradék napi kvótát**: a Service Usage API
API-kulccsal 403-at ad, a válaszfejlécekben nincs `ratelimit-*`, a `models.get()`
csak token-limiteket ismer. A napi limitbe így csak akkor futnál bele, amikor
már megtörtént (429) — a `subtr.py quota` ezért **helyben könyveli** a
hívásokat, és a futás előtt megmondja, belefér-e a tervezett munka.

Csak Python stdlib, nincs telepítendő függőség.

```powershell
python subtr.py quota                  # mai fogyás modellenként
python subtr.py quota --days 7         # utolsó 7 nap
python subtr.py quota --projects       # projektmappa szerinti bontás is
python subtr.py quota --model gemini-3.1-flash-lite   # csak egy modell
python subtr.py quota --where          # hol van a napló
python subtr.py quota --reset          # mai számlálók nullázása
python subtr.py quota --forget-limit gemini-3.6-flash # megtanult limit elfelejtése
```

A `subtr.py translate --provider gemini` és a `subtr.py review --provider gemini`
(illetve a review default ága) **automatikusan** használja: indulás előtt kiírja
a várható fogyást, és minden sikeres hívást elkönyvel. Ha a modul hiányzik, a
parancsok változatlanul futnak tovább — a kvótakövetés kényelmi funkció, nem
állíthatja meg a fordítást.

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
> csendes-óceáni idő (PT) szerint nullázódik. A parancs PT szerint könyvel, és
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
`python subtr.py quota` kiírja őket — ha valamelyik hibásnak tűnik, a
`--forget-limit <modell>` törli, és a következő valódi napi 429-nél újratanul.
Amíg nincs mért adat, becslést használ, és ezt `(becs)` jelöléssel jelzi.

> **A számláló alsó becslés, a maradék ezért felső korlát.** A naplóba csak
> azok a hívások kerülnek, amelyek a `subtr.py` Gemini-ágán mentek ki
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

A `subtr.py glossary` két módban működik — a magyar argumentum dönti el, melyikben:

```powershell
# (A) Fordítás ELŐTTI mód — CSAK az angol fájl (a magyar argumentum elhagyva).
#     Az agent a TRANSLATION.md szabályai alapján JAVASLATOT tesz a magyar fordításra,
#     te jóváhagyod, és a párhuzamos fordítás már egységes nevekkel/címekkel indul.
python subtr.py glossary "input\eng.srt"

# (B) Fordítás UTÁNI mód — angol-magyar pár. A "hu" a kész feliratban
#     ténylegesen használt fordítás (a meglévő viselkedés).
python subtr.py glossary "input\eng.srt" "output\hun.srt"

# Egyéni glossary útvonal (mindkét módban)
python subtr.py glossary "input\eng.srt" --glossary my_glossary.json

# Másik provider (Claude az alapértelmezett)
python subtr.py glossary "input\eng.srt" --provider codex
python subtr.py glossary "input\eng.srt" --provider grok
python subtr.py glossary "input\eng.srt" --provider gemini
python subtr.py glossary "input\eng.srt" --provider gemini --model gemini-3.5-flash-lite

# Csak a biztos találatokat veszi át, a bizonytalanokat kihagyja (nem kérdez)
python subtr.py glossary "input\eng.srt" --yes

# Mindegyiket végigkérdezi (a --yes/auto ág kikapcsolása)
python subtr.py glossary "input\eng.srt" --all-interactive

# Csak kiírja, mi kerülne be — a glossary.json nem módosul
python subtr.py glossary "input\eng.srt" --dry-run
```

A Gemini ág strukturált JSON sémával dolgozik, és a `subtr.py quota`-ba
könyvel, mint a többi Gemini-ágú parancs. Hosszú feliratnál a kinyerés több
darabban megy — **darabonként egy API-hívás**, ezt a napi kvótánál vedd
figyelembe (`python subtr.py quota`).

#### Biztos / bizonytalan javaslatok

A javaslatok besorolást kapnak, a `subtr.py register` mintájára. A modell maga
is nyilatkozik (`confidence`), de az önbevallása nem szűr — tapasztalat szerint
mindent „biztos"-nak jelöl —, ezért egy **gépi fék** felül is bírálja: ha a
kifejezés a forrásfeliratban `MIN_OCCURRENCES`-nél (2) kevesebbszer fordul elő,
a javaslat bizonytalan lesz, akármit is állít magáról.

| kapcsoló | viselkedés |
|---|---|
| *(nincs)* | a biztosakat automatikusan átveszi, csak a bizonytalanokat kérdezi |
| `--yes` | a biztosakat átveszi, a bizonytalanokat **kihagyja**, nem kérdez |
| `--all-interactive` | mindegyiket végigkérdezi |
| `--dry-run` | nem ír fájlba, csak kilistázza, mi kerülne be |

Kérdésnél: `y` (vagy üres Enter) = elfogad, `n` = elutasít, `e` = szerkeszt,
`q` = kilép. Az automatikusan átvett sorokat a futás végén kilistázza az
előfordulásszámmal, hogy utólag is ellenőrizhesd őket.

#### Amit a kinyerő lát

A prompt a fordítóéval **azonos** kontextust kap: a teljes `TRANSLATION.md` +
`TRANSLATION.local.md` (csonkítatlanul), és a teljes jóváhagyott szójegyzék a
`hu` és `context` mezőkkel együtt. Ez utóbbi a fontos: a rokon kifejezéseket
így a már eldöntött terminológiához igazítja (ha a szójegyzékben `"Sect"` =
`"Rend"`, akkor a `"Sect Elder"` sem lesz „szekta véne").

> Ebből következik, hogy a **sorozatspecifikus terminológiai döntések helye a
> `glossary.json` `context` mezője** — onnan a kinyerő is olvassa őket.

A `glossary.json`-t minden fordító- és review-provider automatikusan betölti
és átadja a modellnek, hogy a fordítások
konzisztensek maradjanak.

### Megszólítási regiszter kinyerése (`subtr.py register`) — opcionális

A tegezés/magázás az angol forrásból nem derül ki közvetlenül, ezért a
`TRANSLATION.local.md` *Megszólítási regisztere* dönt róla (lásd a *Tippek*
szakaszt). Ezt **kézzel is megírhatod** — ez a parancs csak felkínál egy első
változatot, illetve továbbvezeti a meglévőt.

```powershell
# Egy epizód alapján, Gemini API-val (default provider)
python subtr.py register "input\S01E01.eng.srt"

# Több rész = pontosabb. A részek közti eltérés VÁLTÁS-jelöltként jön fel,
# nem néma felülírásként — pont ezt kell a regiszter "váltás:" sorába írni.
python subtr.py register "input\S01E01.eng.srt" "input\S01E02.eng.srt"

# Másik provider
python subtr.py register "input\S01E01.eng.srt" --provider claude
python subtr.py register "input\S01E01.eng.srt" --provider codex
python subtr.py register "input\S01E01.eng.srt" --provider grok

# Csak nézni akarod, nem írni
python subtr.py register "input\S01E01.eng.srt" --dry-run

# KÉSZ MAGYAR feliratból (meglévő fordítás átvételekor): a tegezés/magázás
# ott nem következtetés, hanem leolvasás
python subtr.py register "Season 01\S01E01.hun.srt" "Season 01\S01E02.hun.srt" --hungarian
```

| Kapcsoló | Jelentés |
|---|---|
| `--provider gemini\|claude\|codex\|grok` | Modell-provider (default: gemini) |
| `--model NÉV` | Modell-felülbírálás (a `.env` `SUBTR_<PROVIDER>_MODEL_REGISTER` is jó) |
| `--source-lang KÓD` | A forrás nyelve, ha a fájlnév nem árulkodik (lásd *Forrásnyelv*) |
| `--hungarian` | A bemenet(ek) kész **magyar** felirat(ok): a formát a magyar szövegből olvassa le |
| `--local-file ÚTVONAL` | Melyik fájlban van a regiszter (default: `TRANSLATION.local.md`) |
| `--dry-run` / `--yes` / `--all-interactive` | Csak mutat / nem kérdez / mindenre kérdez |
| `--timeout MP` | Egy hívás időkorlátja |

Hogyan dönt, mit kérdez meg:

| Eset | Viselkedés |
|---|---|
| **Biztos** viszony (legalább 2 idézhető bizonyíték a feliratból) | automatikusan bemegy, a végén bizonyítékkal együtt listázva |
| **Bizonytalan** viszony | megkérdez: `y` elfogad, `m` a másik forma, `n` kihagy, `e` szerkeszt, `q` kilép |
| **Ütközik** a meglévő regiszterrel | mindig megkérdez — csendben soha nem ír felül |
| Epizódok közt **eltér** a forma | VÁLTÁS-jelölt: bizonytalanná válik, és kiírja, melyik részben mi volt |

> **Miért nem a modell magabiztosságára hagyatkozunk:** mérve a modell
> gyakorlatilag *mindent* „biztos"-nak jelöl magáról. Ezért a parancs gépi féket
> tesz elé: két idézhető bizonyíték alatt a sor bizonytalan, akármit állít
> magáról — és a bizonytalan sorok nálad kötnek ki, nem a fájlban.

A `--all-interactive` minden párnál kérdez, a `--yes` egyáltalán nem kérdez
(csak a biztos sorokat veszi át). Mentés előtt `TRANSLATION.local.md.bak`
készül, és a parancs csak a *pár-sorokat* kezeli — az `alapértelmezés`, `váltás`
és megjegyzés-sorokat érintetlenül átmenti.

> A regiszterben egy **téves sor rosszabb, mint a hiányzó**: a fordító a
> regisztert kötelezőnek veszi, hiány esetén viszont kikerülő megfogalmazást
> választ. Kétes sort inkább hagyj ki.

## Kontextus-átadás — fontos!

Minden fordító- és review-ág átadja a **TRANSLATION.md**-t és a
**glossary.json**-t system promptként a modellnek:

| Provider / feladat | Mechanizmus |
|--------|-------------|
| `translate --provider claude` | `--append-system-prompt-file` (Claude Code) |
| `translate --provider gemini` | `system_instruction` (Gemini API) |
| `translate --provider codex` | Codex `exec --output-schema` |
| `translate --provider grok` | Grok CLI `--json-schema` |
| `review --provider claude` | `--append-system-prompt-file` (Claude Code) |
| `review` (default: gemini) | `system_instruction` (Gemini API) |
| `review --provider codex` | Codex `exec --output-schema` |
| `review --provider grok` | Grok CLI `--json-schema` |

**Következmény:** ha bővíted a TRANSLATION.md-t (új szabály) vagy a glossary-t,
a változás a következő futáskor automatikusan érvényesül — a translate-nél
és a review-nál is. Külön beállítás nem kell.

## Workflow-skillek

A repó két projekt-szintű skillt tartalmaz (`.claude/skills/`) — ezek Claude
Code-ban `/névvel` hívható, kódolt munkafolyamatok. Clone után azonnal működnek,
külön telepítés nélkül:

| Skill | Mit csinál |
|---|---|
| `/review-triage <hun.srt>` | A `_REVIEW_*.json` riportok minden találatát a forráshoz méri, kiszűri a no-opokat és hamis riasztásokat, `decisions.json`-t épít és a `subtr.py apply-auto`-val átvezeti a jóváhagyottakat |
| `/epizod <név>` | A fájlokból felismeri, hol tart egy epizód a pipeline-ban, és onnan viszi tovább a lépéseket a `steps.txt` szerint — a csapdákkal együtt (`--clean`, `.clean.srt` elleni verify, resegment-sorrend) |

A skillek csak **munkafolyamatot** kódolnak — a fordítási szabályok forrása
továbbra is a `TRANSLATION.md` és a `glossary.json`. Ugyanez a két skill
három helyen él: `.claude/skills/`, `.codex/skills/` és `.grok/skills/`
(`epizod`, `review-triage`).

## Más forrásnyelv (nem angol forrásból)

A gépi oldal nyelvfüggetlen — a promptok, a forrás automatikus megkeresése és a
regiszter-kinyerés a felismert forrásnyelvhez igazodik (lásd a *Forrásnyelv*
szakaszt). Ami **nem** áll át magától, az a szabályzat szövege:

| Mi | Mi történik | Mit tegyél |
|---|---|---|
| A `TRANSLATION.md` angol forrásnyelvi hibamintái konkrét angol kifejezésekre épülnek | Ezek a szabályok nem sülnek el — holt teher, de nem ártanak | Cseréld a saját forrásnyelved tipikus csapdáira |
| A `TRANSLATION.md` *Tegezés/magázás* szakasza | A döntési sorrend, a Megszólítási regiszter és a kikerülő megfogalmazás nyelvfüggetlen | A *Formalitás-jelek angol forrásban* alszakaszt cseréld a saját forrásnyelved jeleire; az *eredeti nyelvből átvett megszólítások* alszakasz nem ázsiai eredetinél elhagyható |
| A `glossary.json` kulcsa `en` | Csak elnevezés; funkcionálisan „forrásnyelvi kifejezés" | — |
| A forrás fájlneve nem követi a `.kód.srt` konvenciót | A review nem találja meg a forrást, és **forrás-összevetés nélkül** fut (több téves találat) | `--source "input\....srt"` kézzel — vagy nevezd át a fájlt a konvenció szerint |

A `glossary.json` szerepe nem angol forrásnál még nagyobb: mivel a hibaminta-szabályok
kiesnek, a konzisztencia jórészt a szójegyzéken múlik.

## Modell-defaultok .env-ből

Az összes fordítási és review parancs (Claude, Gemini, Codex, Grok ág) a `.env` fájlból
automatikusan betölt modell-beállításokat. A definiálandó változók neve mindig
`SUBTR_<PROVIDER>_MODEL` formátumú, ahol a `<PROVIDER>` az egyik: `GEMINI`,
`CLAUDE`, `CODEX` vagy `GROK`.

| Env-kulcs | Hatás |
|---|---|
| `SUBTR_GEMINI_MODEL` | Gemini default modell minden feladathoz |
| `SUBTR_GEMINI_MODEL_TRANSLATE` | task-specifikus felülbírálás fordításhoz |
| `SUBTR_GEMINI_MODEL_REVIEW` | task-specifikus felülbírálás review-hoz |
| `SUBTR_GEMINI_MODEL_GLOSSARY` | task-specifikus felülbírálás glossary extractionhez |
| `SUBTR_GEMINI_MODEL_REGISTER` | task-specifikus felülbírálás regiszter extractionhez |
| `SUBTR_CLAUDE_MODEL` + `_TRANSLATE` / `_REVIEW` / `_GLOSSARY` / `_REGISTER` | ugyanez Claude CLI-hez |
| `SUBTR_CODEX_MODEL` + `_TRANSLATE` / `_REVIEW` / `_GLOSSARY` / `_REGISTER` | ugyanez Codex CLI-hez |
| `SUBTR_GROK_MODEL` + `_TRANSLATE` / `_REVIEW` / `_GLOSSARY` / `_REGISTER` | ugyanez Grok CLI-hez (beégetett: translate / glossary / register `grok-4.5`, review `grok-4.6`) |
| `SUBTR_DEFAULT_PROVIDER` | fordításnál kötelező helyettesítő (`--provider` nélkül ez dönt), a `subtr.py glossary` default providere (`claude`, felülírható), a `subtr.py register` default providere (`gemini`, felülírható) |

**Feloldási precedencia** (az első nem-üres érték nyer):
1. CLI `--model` kapcsoló (ha megadva)
2. Task-specifikus env (`SUBTR_<PROVIDER>_MODEL_<TASK>`)
3. Generikus env (`SUBTR_<PROVIDER>_MODEL`)
4. Beégetett default a parancsban

**Példa .env-ből:**
```bash
# Gemini alapértelmezé: gemini-3.6-flash minden feladathoz
SUBTR_GEMINI_MODEL=gemini-3.6-flash

# Fordítást egy gyorsabb, olcsóbb modellel végezzük
SUBTR_GEMINI_MODEL_TRANSLATE=gemini-3.5-flash-lite

# Review pedig a erősebb Pro verzióval
SUBTR_GEMINI_MODEL_REVIEW=gemini-3.1-pro-preview

# Glossary extraction alapvetően Claudeval, Geminivel nem
SUBTR_DEFAULT_PROVIDER=claude

# Claude fordító: Opus minden fordítási jobhoz
SUBTR_CLAUDE_MODEL_TRANSLATE=opus
```

## Tippek

- **Agent szám:** 3 az ajánlott. Gemininél `--agents 10` fölött 429 rate limit jöhet
  (a parancs figyelmeztet is); Claude-nál/Codexnél a CLI-folyamatok száma a korlát.
- **Blokk méret:** 150 az alapértelmezett. Ha sok a hiba, csökkentsd 100-ra.
- **TRANSLATION.md:** Minél részletesebb az aktuális sorozat adatai rész, annál jobb
  a fordítás minősége (karakter-háttér, formalitás-szintek, kontextus).
- **Megszólítási regiszter:** a tegezés/magázás az angol forrásból nem derül ki
  megbízhatóan, a magyar viszont megköveteli a döntést. A `TRANSLATION.local.md`
  *Megszólítási regisztere* (ki kit tegez / magáz) minden blokk promptjába bekerül,
  ezért ez az egyetlen eszköz, ami a **párhuzamosan futó blokkok között** egységes
  formát tud tartani. Minden epizód előtt frissítsd — egy elavult regiszter rosszabb,
  mint a hiányzó: magabiztosan rossz formát kényszerít. A döntési eljárást a
  `TRANSLATION.md` *Tegezés/magázás* szakasza írja le. Kézzel írod, de a
  `subtr.py register` felkínál egy első változatot (lásd fent).
- **Checkpoint:** mind a három fordító-ág fájl-alapú checkpointtal fut (újraindításkor
  csak a hiányzó blokkokat fordítja; a szekció-eltéréses blokk outputja
  törlődik, így az is újramegy), mind a három review-ág pedig `--start-chunk` /
  `--end-chunk` / `--suffix` kapcsolókkal folytatható. A `subtr.py merge`
  `--force` kapcsolóval hiányzó blokkok mellett is összefűz (a hiányt listázza).
- **Részleges megtagadás:** ha az agent szerkezetileg ép fájlt ír, de egyes cue-k
  helyére placeholdert tesz (`[DAL]`, `[SONG]`, `[TODO]`, üres szöveg ott, ahol a
  forrásban volt), a blokk `warning`-gal törlődik és újrafutáskor újramegy — a
  hiányos fordítás nem kerül a merge-be. A részletes ok (az érintett cue-k és az
  agent válasza) a projekt gyökerében lévő **`.translate.log`**-ban van
  (gitignore-olt, 2 MB fölött `.translate.log.1`-re forog).
- **Fordító finomhangolás:** `subtr.py translate --provider claude --timeout <mp>` (default
  900), `--max-turns <n>` (default 20, futó-galopp elleni plafon),
  `--no-cleanup` (régi sys-prompt fájlok megtartása); `subtr.py glossary
  --timeout <mp>` (default 300).
- **Review-k összevetése:** ugyanazon a fájlon futtathatsz több review-t —
  a két modell más-más típusú hibákat talál (Claude inkább kontextus,
  Gemini inkább morfológia / ikes igék).
- **Review modell-választás — tapasztalati javaslat:** kezdetben Claude
  Opus-szal (`subtr.py review --provider claude`) review-oztam, ami minőségileg jó,
  de drága. Később átálltam a Gemini API-ra (`subtr.py review`, a default ág), és nem
  bántam meg — töredék költséggel hasonló minőséget ad a felirat-review
  feladathoz. Ha most kezdesz, érdemes Gemini-vel próbálkozni elsőként.
  A jelenlegi default a `gemini-3.6-flash`; ha a napi kvótád szűkös, a
  `--model gemini-3.5-flash-lite` a bevált olcsó alternatíva (a korábbi
  default a `gemini-3.1-flash-lite` volt, azzal is használható a pipeline).
- **Gemini napi limit:** ingyenes szinten a `-lite` modellek bőkezűek, a
  nem-lite modellek viszont tapasztalat szerint napi ~20 kérésnél elfogynak —
  **modellenként külön**, ezért modellváltással aznap tovább lehet dolgozni.
  (Nagyságrend: egy ~400 szekciós rész review-ja 4-5 kérés.) Hogy hol tartasz:
  `python subtr.py quota`. Ha egy hosszú futás közben fogyna el, a review
  `--start-chunk` / `--end-chunk` / `--suffix` kapcsolókkal folytatható.
- **Prompt cache:** a `subtr.py translate --provider claude` a system promptot tartalom-hash
  alapján fájlba menti, így a párhuzamos agent-ek és az ismételt futások is
  cache-hit-tel indulhatnak — drasztikus költségcsökkenés.

## Utómunka — a review után

A review riport (`_REVIEW_CLAUDE.txt` / `_REVIEW_GEMINI.txt` / `_REVIEW_CODEX.txt`) csak **jelzi**
a hibákat — a javítást neked kell elvégezni. A teljes folyamat innen még
négy lépés:

### 1. Review-hibák javítása

A riportban listázott hibákat háromféleképpen javíthatod:

- **Interaktívan** (`subtr.py apply`): a parancs összefésüli a riportokat és
  találatonként megkérdezi, alkalmazza-e. A legegyszerűbb út, de sok részen
  több száz kérdés.
- **Döntés-fájllal** (`subtr.py apply-auto`): a javaslatokat előre átnézed —
  magad, vagy egy agenttel, aki mindegyiket az angol eredetihez méri —, és a
  jóváhagyott szövegeket egy `decisions.json`-ben adod át. Kérdés nélkül fut le.
  Ez az ajánlott út, ha több részt viszel át egyszerre; a szűrés miért fontos,
  arról lásd fent a parancs szakaszát.
- **Manuálisan**: szövegszerkesztőben (VSCode, Notepad++, Subtitle Edit,
  stb.) sorszám szerint megkeresed és javítod.

> **Sorrend:** a review-javításokat a szegmentálás (2. lépés) **előtt** vidd át.
> A `resegment --split` újraszámozhatja a cue-kat, és onnantól a riportok
> sorszámai már nem a régi szekciókra mutatnak. A `subtr.py apply-auto` ezt
> észreveszi, ha a döntés-fájlban megadod az `eredeti` mezőt.

### 2. Automatikus szegmentálás — `subtr.py resegment`

A **sorhossz** (max karakter/sor) technikai rendezését a `subtr.py resegment`
determinisztikusan automatizálja — így jóval kevesebb kézi munka marad a
Subtitle Edit-nek. Csak Python stdlib, nincs telepítendő függőség.

```powershell
# QA-riport (csak olvasás): mely cue-k sértik a plafont (CPS / sorhossz / rés)
python subtr.py resegment report "output\Sorozat - S01E01.hun.srt"

# Sorhossz-tisztítás (időzítést NEM változtat) -> új fájl
python subtr.py resegment reflow "output\Sorozat - S01E01.hun.srt" -o "output\Sorozat - S01E01.hun.reflow.srt"

# Ha kell: a 2 sorba nem férő cue-k idő-arányos bontása (cue-számot változtat)
python subtr.py resegment reflow "output\Sorozat - S01E01.hun.srt" --split -o "...reflow.srt"
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
beszédstílusa, dialógus-ritmus), amiket egyik LLM sem fog megbízhatóan 
kezelni.

A *Megszólítási regiszter* ebből elveszi a felsorolt karakterpárokat: azokra a
forma blokkok között is egységes. Ami itt marad: a regiszterben NEM szereplő
párok, az epizódon belüli váltások, ha a regiszter nem jelöli meg a helyüket,
és minden olyan jelenet, ahol a szövegből nem derül ki, ki beszél kihez.

Ez a négy utómunka-lépés teszi teljessé a folyamatot — nélkülük a fordítás
nyelvileg jó lehet, de a néző-élmény nem lesz az.

## Hivatkozott dokumentumok

- `TRANSLATION.md` — közös fordítási szabályok és sorozat-kontekstus
- `CLAUDE.md` — Claude Code belépési pont a közös szabályzathoz
- `steps.txt` — gyors parancs-cheatsheet
- `resegment_srt.md` — a szegmentáló eszköz (`subtr.py resegment`) részletes leírása
- `proposals/` — fejlesztési irányok, alternatívák, tervezési dokumentumok
  (lásd: [`proposals/README.md`](proposals/README.md))
- `addons/` — opcionális segédscriptek (lásd: [`addons/README.md`](addons/README.md))
- `LICENSE` — MIT licenc

## Hogyan készült — AI-asszisztált fejlesztés

**Ez a projekt kódjának túlnyomó része AI-asszisztensekkel készült**, emberi
irányítás, tesztelés és jóváhagyás mellett. Ezt fontosnak tartom kiírni, mert
befolyásolja, hogyan érdemes a kódhoz viszonyulni.

- **[Claude Code](https://claude.com/claude-code)** — a fejlesztés zöme: a
  `subtr/` csomag, a CLI, a promptok, a tesztek és ez a dokumentáció is.
- **Codex CLI** — főleg a Codex-providerhez (`subtr/providers/codex_cli.py`)
  kapcsolódó részek, illetve egy-egy második vélemény a review-körökben.
- **Grok CLI** — a Grok-provider (`subtr/providers/grok_cli.py`) és a
  `.grok/skills/` munkafolyamat-skillek.

Az AI-val írt commitok `Co-Authored-By` sorral vannak megjelölve, így a
`git log`-ból utólag is látszik, mi hogyan készült.

Amit ez a gyakorlatban jelent:

- **A kód működik, de nem „iparilag auditált".** Van teszt-lefedettség
  (`pytest`), a pipeline több sorozaton végigfutott élesben — de ez egy hobbi
  projekt, nem egy review-boardon átment termék. Ha éles környezetben
  használnád, olvasd át, amit futtatsz.
- **Az API-hívások pénzbe kerülnek.** A fordítás és a review a te kulcsoddal,
  a te kvótádból fut. A `subtr.py quota` parancs segít nyomon követni.
- **A fordítás maga is LLM-kimenet**, tehát hibázhat. A README *Utómunka* és
  *Tippek* szakaszai pont arról szólnak, hogy ezt hogyan kapd el — a kézi
  lektorálási kör nem opcionális dísz, hanem a folyamat része.

## Licenc

[MIT](LICENSE) — Copyright (c) 2026 Edit Diószegi (dioszedit).

Röviden: **bárki szabadon használhatja, módosíthatja és továbbadhatja**, akár
kereskedelmi célra is; az egyetlen feltétel, hogy a szerzői jogi megjegyzés és
a licenc szövege maradjon meg a másolatokban. Garancia nincs — a szoftver
„ahogy van" állapotban használható.

Ez a licenc **a keretrendszer kódjára** vonatkozik. Amit a segítségével
fordítasz — feliratfájlok, sorozat-adatok, glossary-tartalom — nem tartozik
ide: azok jogi helyzetéért (szerzői jog, terjesztés) a felhasználó felel. A
`.gitignore` szándékosan kizárja az `input/`, `output/` és `blocks/` mappák
tartalmát, hogy ilyesmi ne kerüljön véletlenül a repóba.
