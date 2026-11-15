# SRT Felirat Fordító — Claude, Gemini, Codex, Grok és Antigravity

> **In English.** A command-line pipeline for translating SRT subtitles **into
> Hungarian** with LLMs, built for TV series (Korean, Chinese and other Asian
> dramas in particular) where consistent names, honorifics and the formal/informal
> address (*tegez/magáz*) matter more than raw speed. One CLI, `subtr.py`, runs the
> whole chain: split into blocks → translate with checkpointing → merge →
> structural verify → stylistic review by a second model → triage and apply the
> accepted fixes → re-segment long lines. Terminology lives in a mandatory
> `glossary.json`; the address register is extracted from the original-language
> track, not guessed. Five interchangeable providers: Claude Code, Gemini API,
> Codex CLI, Grok CLI and Antigravity CLI (Gemini models via subscription). 18 source languages are recognised from the file name
> (`.eng`, `.ger`, `.kor`, …); the **target language is fixed to Hungarian** — the
> prompts are written in Hungarian and this is a design decision, not a
> parameter. Add-ons cover new-series setup from the TMDB API, SDH pre- and post-cleaning,
> WebVTT import and subtitle-track extraction from video. ~450 tests, no network
> in the test suite. The full documentation is in Hungarian, split into chapters
> in [`docs/`](docs/README.md). MIT licensed; most of the code was written with AI
> assistants under human direction — see
> [*Hogyan készült*](docs/10-fejlesztes.md#hogyan-készült--ai-asszisztált-fejlesztés).

SRT felirat-fordítási keretrendszer LLM-alapú fordítással és stilisztikai review-val.
A workflow Claude Code-, Gemini API-, Codex CLI-, Grok CLI- és Antigravity CLI-providerrel futtatható.

**Irány:** forrásnyelvből magyarra. A **célnyelv fixen magyar** — a fordító és a
review promptok magyar nyelvre vannak megírva, ez nem paraméter. A **forrásnyelv
alapból angol**, de bármelyik támogatott nyelv lehet: a fájlnév `.kód` tagjából
(`.eng`, `.ger`, `.kor`, …) minden lépés automatikusan felismeri, és a promptok
ehhez igazodnak — részletek: [*Forrásnyelv*](docs/04-forditas.md#forrásnyelv).

**Tipikus use-case:** sorozat-feliratok fordítása (pl. koreai és más ázsiai drámák),
ahol fontos a karakterek, megszólítások és kulturális kifejezések konzisztens
kezelése — de a keretrendszer bármilyen videó/film/sorozat-felirathoz használható.

> **AI-asszisztált projekt, MIT licenc.** A kód túlnyomó része Claude Code-dal
> (részben Codex CLI-vel és Grok Build-del) készült, emberi irányítás és
> tesztelés mellett; bárki szabadon használhatja. Részletek: [*Hogyan készült*](docs/10-fejlesztes.md#hogyan-készült--ai-asszisztált-fejlesztés)
> és [*Licenc*](#licenc).

## Gyors indulás

1. **Letöltés:** a GitHub-oldalon **Code → Download ZIP**, majd kicsomagolás
   (vagy `git clone`). Python 3.10+ kell.
2. **Eszközök és kulcsok:** az alapbeállítás a fordításhoz és a szójegyzékhez a
   **Claude Code CLI**-t (`claude`), a review-hoz az **Antigravity CLI**-t
   (`agy`), a megszólítási regiszterhez a **Gemini API**-t használja — ezekből
   ami kell, telepítsd és jelentkezz be. Bármelyik funkció átállítható másik
   providerre ([6. fejezet](docs/06-providerek.md)). A Gemini API-hoz:
   `pip install google-genai python-dotenv pydantic`, és a `.env.example`
   másolata `.env` néven, benne a `GEMINI_API_KEY`-jel.
3. **Új sorozat:** a program mappáját sorozatonként egy-egy mappába másolod.
   Létrehozod a `TRANSLATION.local.md`-t — a `tmdb-init` add-on TMDB-linkből
   megírja, vagy a `TRANSLATION.md` sablonjából kézzel —, és kitöltöd benne a
   megszólítási regisztert.
4. **Forrásfelirat:** az `input/` mappába, a nyelvkóddal a névben, pl.
   `Sorozat - S01E01.eng.srt` (más nyelvnél `.ger`, `.kor`, …) — ebből tudja a
   program a forrásnyelvet, és a review is ez alapján találja meg a forrást.
5. **Első epizód:** a [teljes folyamat lépésről lépésre](docs/02-elso-epizod.md);
   a `steps.txt` ugyanezt bővebb, másolható parancslistaként adja (az
   opcionális lépésekkel együtt).

Részletesen: [1. Telepítés és mappaszerkezet](docs/01-telepites.md).

## Dokumentáció

A teljes leírás a [`docs/`](docs/README.md) mappában van, fejezetekre bontva:

1. [Telepítés és mappaszerkezet](docs/01-telepites.md) — előfeltételek, letöltés, új sorozat indítása, frissítés új verzióra, a mappák szerepe
2. [Az első epizód — a teljes folyamat](docs/02-elso-epizod.md) — egy epizód lépésről lépésre, a szabályok átadása a modellnek, workflow-skillek
3. [Szójegyzék és megszólítási regiszter](docs/03-szojegyzek.md) — a fordítás előtti lépések: glossary, alap-szótárak, a tegezés/magázás kinyerése
4. [Fordítás](docs/04-forditas.md) — forrásnyelv, a fordító providerek és kapcsolóik
5. [Review és javítás](docs/05-review.md) — a review providerei, megszakadt review folytatása, a javaslatok alkalmazása
6. [Provider, modell és effort](docs/06-providerek.md) — melyik funkció melyik modellel fusson, .env-beállítások
7. [Gemini: modellek, limitek, kvóta](docs/07-gemini-kvota.md) — modellválasztás, Free tier és saját limitek, napi kvóta, modellváltás
8. [Utómunka](docs/08-utomunka.md) — review-hibák, sorhossz-szegmentálás, Subtitle Edit, kézi lektorálás, MKV
9. [Tippek](docs/09-tippek.md) — gyakorlati tanácsok
10. [Fejlesztés és háttér](docs/10-fejlesztes.md) — fejlesztőknek: tesztek, commit előtti szűrő; mindenkinek: hogyan készült

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

A `tmdb-init` add-on a [TMDB](https://www.themoviedb.org/) API-ját használja.
This product uses the TMDB API but is not endorsed or certified by TMDB.
