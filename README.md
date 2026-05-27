# SRT Felirat Fordító — Claude Code projekt

Koreai (és egyéb ázsiai) sorozatok angol feliratainak fordítása magyarra, SRT formátumban.
A workflow Claude Code-on alapul, a stilisztikai review opcionálisan Gemini API-val is fut.

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
├── translate_parallel.py        ← 2. Párhuzamos fordítás Claude Code-dal
├── merge_srt.py                 ← 3. Blokkok összefűzése
├── verify_srt.py                ← 4. Strukturális ellenőrzés
├── review_with_claude.py        ← 5a. Stilisztikai review Claude Code-dal
├── review_with_gemini.py        ← 5b. Stilisztikai review Gemini API-val (opcionális)
├── glossary_extract.py          ← 6. Szójegyzék bővítése feliratpárból (interaktív)
│
├── input/                       ← Ide tedd az angol SRT fájlokat
├── blocks/                      ← Auto-generált blokk-fájlok
├── output/                      ← Kész magyar fájlok + review riportok
│
├── info/                        ← Háttér-jegyzetek (pl. translategemma alternatíva)
├── plan/                        ← Tervezési dokumentumok (pl. desktop GUI terv)
└── lepesek.txt                  ← Quick-reference parancslista
```

Az `input/`, `output/`, `blocks/` mappák tartalma nem kerül a git repóba —
projektenként / epizódonként más, és gyakran szerzői jogi védettség alá esik.

## Előfeltételek

- **Python 3.10+**
- **Claude Code CLI** (`claude` parancs) — a fordításhoz és a Claude review-hoz
- **Gemini API kulcs** (opcionális) — csak ha Gemini review-t is használsz
- **Git** (opcionális) — verziókezeléshez

## Telepítés

### Új gépen — clone GitHub-ról

```powershell
git clone https://github.com/dioszedit/subtitle-translator.git
cd subtitle-translator

# Gemini review függőségei (csak ha használod)
pip install google-genai python-dotenv pydantic

# .env létrehozása a sablonból
copy .env.example .env
# Szerkeszd: GEMINI_API_KEY=...   (https://aistudio.google.com/apikey)
```

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

# 2. Fordítás 3 párhuzamos agent-tel
python translate_parallel.py "blocks\Sorozat - S01E01.eng" --agents 3

# 3. Összefűzés egy fájlba
python merge_srt.py "blocks\Sorozat - S01E01.eng" "output\Sorozat - S01E01.hun.srt"

# 4. Strukturális ellenőrzés (sorszámok, időbélyegek, szekciószámok)
python verify_srt.py "input\Sorozat - S01E01.eng.srt" "output\Sorozat - S01E01.hun.srt"

# 5a. Stilisztikai review Claude Code-dal
python review_with_claude.py "output\Sorozat - S01E01.hun.srt"
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_CLAUDE.txt

# 5b. Stilisztikai review Gemini-vel (opcionális, párhuzamos vélemény)
python review_with_gemini.py "output\Sorozat - S01E01.hun.srt"
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_GEMINI.txt
```

A két review script **független** — futtathatod csak az egyiket, csak a másikat,
vagy mindkettőt. A jelölt hibák alapján manuálisan javítsd a magyar fájlt.

### Fordítás — opciók

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

### Review — opciók

#### Claude review (`review_with_claude.py`)
```powershell
# Egyedi chunk méret (default: 100)
python review_with_claude.py "output\hun.srt" --chunk-size 150
```

#### Gemini review (`review_with_gemini.py`)
```powershell
# Default modell: gemini-2.5-flash (gyors, olcsó)
python review_with_gemini.py "output\hun.srt"

# --pro shortcut: gemini-2.5-pro (alaposabb, drágább)
python review_with_gemini.py "output\hun.srt" --pro

# Tetszőleges modell-azonosító (--pro felülírva)
python review_with_gemini.py "output\hun.srt" --model gemini-3-flash-preview
python review_with_gemini.py "output\hun.srt" --model gemini-3.1-flash-lite-preview
# Modell-lista: https://ai.google.dev/gemini-api/docs/models

# Csak egy chunk-tartomány lefuttatása (pl. kvótahiba utáni pótlás)
python review_with_gemini.py "output\hun.srt" --start-chunk 9 --suffix _part2
python review_with_gemini.py "output\hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2
```

A Gemini review **strukturált JSON kimenetet** ad (Pydantic séma), ami stabilabb
mint a szabad szöveg, és automatikusan retry-ol rate limit (429) vagy 5xx hiba esetén.

### Szójegyzék bővítése (az első néhány rész után ajánlott)

```powershell
# Kifejezések kinyerése feliratpárból — interaktív jóváhagyás
python glossary_extract.py "input\eng.srt" "output\hun.srt"

# Egyéni glossary útvonal
python glossary_extract.py "input\eng.srt" "output\hun.srt" --glossary my_glossary.json
```

A `glossary.json`-t a `translate_parallel.py` és **mindkét review script**
automatikusan betölti és átadja a modellnek, hogy a fordítások konzisztensek
maradjanak.

## Kontextus-átadás — fontos!

Mind a fordító, mind a két review script átadja a **CLAUDE.md**-t és a
**glossary.json**-t system promptként a modellnek:

| Script | Mechanizmus |
|--------|-------------|
| `translate_parallel.py` | `--append-system-prompt-file` (Claude Code) |
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
- **Checkpoint:** A `translate_parallel.py` és a Gemini review (`--start-chunk`)
  is támogatja a megszakítás utáni folytatást.
- **Két review összevetése:** ugyanazon a fájlon futtasd mindkét review-t —
  a két modell más-más típusú hibákat talál (Claude inkább kontextus,
  Gemini inkább morfológia / ikes igék).
- **Prompt cache:** a `translate_parallel.py` a system promptot tartalom-hash
  alapján fájlba menti, így a párhuzamos agent-ek és az ismételt futások is
  cache-hit-tel indulhatnak — drasztikus költségcsökkenés.

## Utómunka — a review után

A review riport (`_REVIEW_CLAUDE.txt` / `_REVIEW_GEMINI.txt`) csak **jelzi**
a hibákat — a javítást neked kell elvégezni. A teljes folyamat innen még
három lépés:

### 1. Review-hibák javítása

A riportban listázott hibákat kétféleképpen javíthatod:

- **Claude Code-dal**: nyisd meg a magyar SRT-t Claude Code-ban, és add át
  neki a review riportot — végigmegy a hibákon és javítja.
- **Manuálisan**: szövegszerkesztőben (VSCode, Notepad++, Subtitle Edit,
  stb.) sorszám szerint megkeresed és javítod.

### 2. Technikai javítás Subtitle Edit-tel

A nyelvi review nem foglalkozik a felirat **olvasási sebességével** és
egyéb technikai paraméterekkel. Ezt a [Subtitle Edit](https://www.nikse.dk/subtitleedit)
(ingyenes, Windows + Mac) intézi:

- **CPS (Characters Per Second)** — túl gyors feliratok jelzése
- **Min/max megjelenési idő** ellenőrzés
- **Átfedések** detektálása
- **Sortörés-optimalizálás** (max sor-hossz)
- **Helyesírás-ellenőrzés** magyar nyelvre

Tools → "Fix common errors" / "Apply min duration" / stb. funkciókkal
automatikusan vagy félautomatikusan rendezhető.

### 3. Végső kézi lektorálás

A fordító és a review modellek sosem tökéletesek, és az automatikus
javítás után is érdemes egyszer **végigolvasni** a kész feliratot —
ideálisan a videóval szinkronban, lejátszás közben. Ekkor jönnek elő
azok a finomságok (kontextus-érzékeny tegezés/magázás, karakterek
beszédstílusa, dialógus-ritmus), amiket egyik LLM sem fog megbízhatóan.

Ez a három utómunka-lépés teszi teljessé a folyamatot — nélkülük a fordítás
nyelvileg jó lehet, de a néző-élmény nem lesz az.

## Hivatkozott dokumentumok

- `CLAUDE.md` — fordítási szabályok, sorozat-kontextus sablon
- `lepesek.txt` — gyors parancs-cheatsheet
- `stilisztika.txt` — stílusbeli megjegyzések
- `info/translategemma_megoldas.md` — alternatív lokális fordító (Mac mini + ollama) jegyzete
- `plan/desktop_app_terv.md` — desktop GUI tervezési dokumentum (folyamatban)
