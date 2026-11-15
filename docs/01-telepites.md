# 1. Telepítés és mappaszerkezet

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Előfeltételek

- **Python 3.10+**
- **Claude Code CLI** (`claude` parancs, opcionális) — a Claude providerhez
- **Gemini API kulcs** (opcionális) — ha Gemini-vel fordítasz vagy review-zol (`subtr.py translate --provider gemini` / `subtr.py review --provider gemini`)
- **Codex CLI** (`codex` parancs, opcionális) — a Codex providerhez. Bejelentkezett CLI-t használ; külön Python-csomag nem kell.
- **Grok CLI** (`grok` parancs, opcionális) — a Grok providerhez. Bejelentkezett CLI (`grok login`) vagy `XAI_API_KEY`; külön Python-csomag nem kell.
- **Antigravity CLI** (`agy` parancs, opcionális) — az Antigravity providerhez: Gemini-modellek előfizetésből, API-kulcs és napi API-kvóta nélkül. Bejelentkezett CLI; külön Python-csomag nem kell. Az elérhető modelleket az `agy models` listázza.
- **Git** (opcionális) — csak ha a programot git-tel töltöd le / frissíted, vagy fejleszted; sima használathoz nem kell

## Telepítés

### Új gépen — letöltés GitHub-ról

Git nélkül: a https://github.com/dioszedit/subtitle-translator oldalon
**Code → Download ZIP**, majd csomagold ki. Ha használsz git-et, ugyanez:
`git clone https://github.com/dioszedit/subtitle-translator.git`.

```powershell
cd subtitle-translator

# Gemini-provideres parancsok függőségei (translate --provider gemini és/vagy review --provider gemini)
pip install google-genai python-dotenv pydantic

# .env létrehozása a sablonból
copy .env.example .env
# Szerkeszd: GEMINI_API_KEY=...   (https://aistudio.google.com/apikey)
```

> Opcionális: `pip install -e .` után a parancs `subtr <parancs> ...` alakban is
> hívható (meg `python -m subtr`-ként) — a dokumentáció a `python subtr.py` formát
> használja, mert az telepítés nélkül is működik.

> **macOS / Linux megjegyzés:** a dokumentáció parancsai Windows PowerShell-re vannak
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

1. A letöltött mappát használhatod közvetlenül, vagy sorozatonként egy-egy
   új mappába másolhatod a programot (így minden sorozat munkafájljai —
   `TRANSLATION.local.md`, `glossary.json`, `input/`, `output/` — külön
   maradnak). A program frissítéséről lásd lent: [*Frissítés új verzióra*](#frissítés-új-verzióra).
2. Hozd létre a gitignore-os `TRANSLATION.local.md` fájlt. Ha a sorozat fent
   van a [TMDB](https://www.themoviedb.org/)-n, ezt megcsinálja helyetted a
   `tmdb-init` add-on a hivatalos API-val — egy ingyenes `TMDB_API_KEY` kell
   hozzá a `.env`-ben (részletek: [`addons/tmdb-init/README.md`](../addons/tmdb-init/README.md)):

   ```powershell
   py addons\tmdb-init\init_local.py https://www.themoviedb.org/tv/12345-sorozat-cime
   ```

   Enélkül másold a `TRANSLATION.md` „Aktuális sorozat adatai” sablonját a
   fájlba kézzel. Mindkét esetben neked kell kitöltened a *Megszólítási
   regisztert* és a speciális kifejezéseket — a script ezeket `TODO:` sorként
   hagyja benne; a magyar címet a TMDB-ről átveszi, ha ott fel van véve.

   Az add-on a `glossary.json`-ba is felveszi a **sorozat címét**, hogy a
   fordító ne próbálkozzon a lefordításával. Szereplőneveket
   szándékosan nem — azokat a [szójegyzék-kinyerés](03-szojegyzek.md#szójegyzék-bővítése) (`subtr.py glossary`) szedi ki magából
   a feliratból, a tényleges írásmódjukkal.

   Az ország és a TMDB-műfaj alapján **alap-szótárat is javasol**
   (`glossaries/`, pl. `zh-common` + `zh-historical`), és a létezőket beírja a
   `glossary.json` `meta.bases`-ébe; felülírás: `--base zh-common,zh-wuxia`,
   kihagyás: `--no-base`. Lásd [Alap-szótárak](03-szojegyzek.md#alap-szótárak-glossaries).
3. Tedd a forrásnyelvi SRT fájlt az `input/` mappába, `.eng.srt` végződéssel
   (vagy más nyelvnél a megfelelő kóddal — lásd [Forrásnyelv](04-forditas.md#forrásnyelv)).

### Meglévő fordítás átvétele (vtt-import)

Ha egy sorozat korábbi részei **már le vannak fordítva** más forrásból (pl.
`.vtt`-ben), és csak a maradékot fordítod a pipeline-nal, a következetesség
három lépésben vihető át — részletek:
[`addons/vtt2srt/README.md`](../addons/vtt2srt/README.md).

1. `python3 addons/vtt2srt/vtt2srt.py …/*.vtt` — a pipeline SRT-t vár; a
   konverter az időzítést és a szöveget (`<i>`, `♫`, `[kártyák]`) változatlanul
   viszi, csak újraszámoz és a `.`→`,` cserét végzi el az időbélyegben.
2. `python3 subtr.py glossary "input/…EXX.eng.srt" "…/…EXX.hun.srt"` — a
   [szójegyzék utólagos módja](03-szojegyzek.md#szójegyzék-bővítése) a **ténylegesen használt**
   magyar alakot tanulja meg. A párosítás sorszám szerint megy, ezért az angol
   és a magyar fájl cue-számának egyeznie kell.
3. `python3 subtr.py register "…/…EXX.hun.srt" --hungarian` — a
   [regiszter-kinyerés](03-szojegyzek.md#megszólítási-regiszter-kinyerése-subtrpy-register--opcionális)
   a kész magyar szövegből dolgozik: a tegezés/magázás ott nem következtetés,
   hanem a magyar igealak leolvasása.

### Frissítés új verzióra

Ha a programból új verzió jön, töltsd le ugyanúgy (**Code → Download ZIP**,
vagy git-tel `git pull`), és másold át a **program fájljait** minden fordítási
mappádba, felülírva a régieket:

- `subtr.py`, `subtr/`, `addons/`, `glossaries/`
- `.claude/`, `.codex/`, `.grok/`, `.agents/` (a munkafolyamat-skillek)
- `README.md`, `docs/`, `TRANSLATION.md`, `resegment_srt.md`, `AGENTS.md`, `CLAUDE.md`,
  `.env.example`, `pyproject.toml`, `LICENSE`

**Ne írd felül** a sorozat saját fájljait: `TRANSLATION.local.md`,
`glossary.json`, `.env`, és az `input/`, `output/`, `blocks/`,
`Season 01/` mappákat — ezek a te munkád. Ha a `steps.txt`-t a sorozatodra
szabtad, azt se írd felül vakon: nézd meg, mi változott benne. Ha a
`glossaries/` alap-szótáraiba magad is vettél fel szavakat, azokat másolás előtt
mentsd el.

Ha a Gemini-limiteket saját magad állítottad be (`models refresh --local`), a
frissítés azokat nem írja felül; az új verzió beépített adataira a
`python subtr.py models reset-local` vált át (lásd: [*Gemini-modellek, limitek,
kivezetések*](07-gemini-kvota.md)). Hogy egy mappában mi az érvényes beállítás, a
`python subtr.py config` mutatja.

## Mappaszerkezet

```
subtitle-translator/
├── README.md                    ← Kezdőlap: rövid leírás, gyors indulás, tartalomjegyzék
├── docs/                        ← A dokumentáció fejezetei (docs/README.md: tartalomjegyzék)
├── TRANSLATION.md               ← Közös fordítási szabályok és sorozat-kontekstus
├── CLAUDE.md                    ← Claude Code belépési pont a közös szabályzathoz
├── AGENTS.md                    ← Codex projektutasítások
├── TRANSLATION.local.md         ← Az aktuális sorozat adatai (gitignore-olt, sorozatonként más)
├── glossary.json                ← Fordítási szójegyzék (kézzel validált)
├── glossaries/                  ← Alap-szótárak műfaj × kultúra szerint (a glossary.json `meta.bases` választ)
├── .env.example                 ← .env sablon: API-kulcsok, funkciónkénti provider / modell / effort
├── .gitignore                   ← (git-hez) mi nem része a programnak: .env, munkafájlok
├── LICENSE                      ← MIT licenc
├── pyproject.toml               ← Csomagolás (pip install -e .) és pytest-konfiguráció
│
├── .claude/skills/              ← Workflow-skillek (epizod, review-triage, hardsub) Claude Code-hoz
├── .codex/skills/               ← ugyanezek Codex CLI-hez
├── .grok/skills/                ← ugyanezek Grok CLI-hez
├── .agents/skills/              ← ugyanezek Antigravity CLI-hez (`agy`)
│
├── subtr.py                     ← Egyparancsos CLI — minden lépés ezen keresztül fut
│                                  (split, glossary, register, translate, merge,
│                                  verify, review, apply, apply-auto, resegment, quota, models, config)
│
├── subtr/                       ← A tényleges fordítás- és review-logika
│   ├── cli.py                   ← az alparancsok elosztója (subtr.py és python -m subtr)
│   ├── config.py                ← .env betöltése, provider- / modell- / effort- és forrásnyelv-feloldás
│   ├── defaults.env             ← az alapértékek EGYETLEN helye (provider / modell / effort funkciónként)
│   ├── srt.py                   ← SRT parser
│   ├── blocks.py                ← Blokk-alapú szegmentálás
│   ├── context.py               ← TRANSLATION.md + glossary.json beolvasása
│   ├── glossary.py              ← glossary.json kezelés
│   ├── reports.py               ← Review riportok szerializálása
│   ├── quota.py                 ← Gemini kvóta-számlálás
│   ├── gemini_models.py         ← Gemini-modellek, limitek, kivezetések; modellváltás napi limitnél
│   ├── gemini_models.json       ← GENERÁLT (`subtr.py models refresh`) — a limitek és kivezetések egyetlen helye
│   ├── providers/               ← Provider adapterek
│   │   ├── base.py              ← a CLI-providerek közös felülete
│   │   ├── gemini.py            ← Gemini API + retry + kvótakezelés
│   │   ├── claude_cli.py        ← Claude Code wrapper
│   │   ├── codex_cli.py         ← Codex CLI wrapper        ┐ azonos felület (run_json /
│   │   ├── grok_cli.py          ← Grok CLI wrapper         │ RunError), a taskok egy
│   │   └── antigravity_cli.py   ← Antigravity CLI wrapper  ┘ ággal kezelik (CLI_PROVIDERS)
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
│   ├── tmdb-init/               ← 0/a: új sorozat — TRANSLATION.local.md + glossary-címek TMDB-linkből
│   ├── srt-preclean/            ← 0/b: SDH-forrás előtisztítása, 6/b: SDH-tisztítás a kész fordításon
│   ├── vtt2srt/                 ← 0/d: meglévő .vtt felirat átvétele (WebVTT → SRT)
│   ├── mkv-subs/                ← 0/e: feliratsávok a videóból, nyelvcímke szerint; a végén a kész felirat vissza az mkv-ba (ffmpeg)
│   └── hardsub-cover/           ← utómunka: beégetett idegen felirat takarása dobozos ASS-sávval
│
├── input/                       ← Ide tedd a forrásnyelvi SRT fájlokat
├── blocks/                      ← Auto-generált blokk-fájlok
├── output/                      ← Kész magyar fájlok + review riportok
│
├── proposals/                   ← Fejlesztési irányok, alternatívák, tervek
│                                  (saját README a részletekhez)
├── steps.txt                    ← Quick-reference parancslista
├── resegment_srt.md             ← A resegment parancs részletes leírása
│
│   — csak fejlesztéshez (lásd: docs/10-fejlesztes.md) —
├── tests/                       ← pytest-tesztek, modulonként egy fájl; hálózat és API-kulcs nélkül futnak
├── scripts/
│   └── check_copyright.py       ← commit előtti szűrő: jogvédett tartalom és titok
├── .githooks/
│   └── pre-commit               ← a szűrőt hívja (bekapcsolás: git config core.hooksPath .githooks)
└── .copyright-blocklist.example ← sablon a helyi, gitignore-olt terminus-listához
```

A **`subtr.py`** a program mappájából (ahol maga a `subtr.py` van) fut, és minden alparancsa a `subtr/` csomag
logikáját használja. Ez egy tudatos refaktor-döntés: korábban a glossary-betöltő
logika 6 különálló scriptben élt egyszerre, és a másolatok szétcsúsztak. Most a
valódi logika egyetlen helyen van (`subtr/`), az alparancsok csak vékony
kapcsolódási pontok, és az update-ek mindegyikre azonnal érvényesek.

Az `input/`, `output/`, `blocks/` mappák a te munkafájljaid, nem részei a
programnak (a letölthető programban üresek) — projektenként / epizódonként
mások, és gyakran szerzői jogi védettség alá esnek.

---

[Tartalomjegyzék](README.md) · [2. Az első epizód — a teljes folyamat →](02-elso-epizod.md)
