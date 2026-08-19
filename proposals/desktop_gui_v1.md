# Felirat-Fordító Desktop App — Tervezési Dokumentum

> **Státusz:** v1 — első tervezési kör, döntési pontok nyitva
> **Dátum:** 2026-05-07
> **Cél:** A meglévő felirat-fordító scriptekhez egy közös desktop GUI tervezése (Windows + Mac), ami a teljes workflow-t (felirat-extrahálás → fordítás → review) egy ernyő alatt kezeli.

---

## 0. Háttér

A projekt jelenleg külön CLI scriptekből áll:
`split_srt.py`, `translate_parallel.py`, `merge_srt.py`, `verify_srt.py`,
`review_with_claude.py`, `review_with_gemini.py`, `glossary_extract.py`.

A scriptek jól működnek külön-külön, de:
- a workflow több lépésből áll, manuális fájlkezeléssel
- a beállítások (API kulcs, modell-választás) szétszórtak
- nincs egységes progress-megjelenítés
- a beavatkozást igénylő lépések (pl. `glossary_extract.py` interaktív)
  CLI-ben oldódnak meg

A cél egy **vékony orchestráló GUI**, ami a meglévő scripteket NEM írja át,
hanem subprocess-ként hívja és élő stdout-ot mutat.

---

## 1. Magas-szintű architektúra alapelvek

### 1.1 A meglévő scripteket NE írjuk újra
- A scriptek **CLI-eszközök** maradnak
- A GUI **subprocess-ként hívja őket** (`QProcess` vagy hasonló)
- Stdout-ot élő-streamelve mutatja egy konzol-widgetben
- **Előny:** a scriptek továbbra is futtathatók parancssorból, függetlenül; a GUI csak orchestrátor
- **Hátrány:** strukturált progress-hez stdout-parsing kell (vagy a scriptek strukturált státusz-sorokat adnak)

### 1.2 A GUI csak vékony réteg
- Nem tartalmaz fordítási logikát
- Nem tartalmaz API hívást (azt a scriptek csinálják)
- Felelőssége: workflow vezérlés, beállítások, progress megjelenítés

---

## 2. Stack — három opció, javaslattal

| Opció | Tech | Előny | Hátrány |
|-------|------|-------|---------|
| **A) Python + PySide6 (Qt)** | natív look-and-feel, érett | Win + Mac + Linux egy kódból, gazdag widgetek, robosztus, `QProcess` orchestrátorhoz tökéletes | LGPL licensz (proprietary korlátok), tanulási görbe |
| **B) Python + Flet** | Flutter motor, Python-native | gyönyörű, friss, kevés boilerplate | fiatalabb ökoszisztéma, kevesebb stack overflow |
| **C) Python + customtkinter** | modernizált Tkinter | nincs új nehéz függőség, egyszerű | korlátozott widgetek, nem natív look |

**Javasolt: PySide6 (Qt for Python)**

Indok:
- Python-ökoszisztémában maradunk, nincs új JS/Electron stack
- Valódi natív look Win + Mac
- `QProcess`, `QThread` érett megoldások a subprocess-hez
- Cross-platform packaging: `pyinstaller` vagy `briefcase`
- LGPL-licensz korlát saját használatra nem releváns

Electron / Tauri kerülendő — felesleges JS layer.

**Csomagolás:**
- `pyinstaller` — egyszerű, egy `.exe` / `.app`
- `briefcase` (BeeWare) — natívabb, bonyolultabb

---

## 3. Adatkezelési modell

### 3.1 Globális beállítások (felhasználó-szintű)

Hely:
- Windows: `%APPDATA%\Feliratford\config.json`
- Mac: `~/Library/Application Support/Feliratford/config.json`
- Linux: `~/.config/feliratford/config.json`

```json
{
  "api_keys": {
    "anthropic": "sk-ant-...",
    "google": "AIza..."
  },
  "default_models": {
    "translate": "sonnet",
    "review_gemini": "gemini-3.6-flash"
  },
  "default_chunk_size": 100,
  "default_agents": 3,
  "recent_projects": [
    "/path/to/project1",
    "/path/to/project2"
  ],
  "ffmpeg_path": "auto",
  "scripts_dir": "/path/to/Basic_for_claude_code"
}
```

**Biztonság:** JSON-ban tárolt kulcs olvasható. Saját gépen rendben; ha
többfelhasználós, OS keychain ajánlott (`keyring` csomag — Win Credential
Manager + Mac Keychain).

### 3.2 Projekt-specifikus adatok

Meglévő struktúrát megtartjuk, kiegészítjük:

```
my_drama_s01e03/
├── CLAUDE.md           ← projekt szabályok / sorozat kontextus
├── glossary.json       ← projekt szójegyzék
├── input/              ← angol SRT(-ek)
├── blocks/             ← blokkok (auto)
├── output/             ← magyar SRT(-ek) + review riportok
├── video/              ← (új) videofájlok az extrahálás alapanyagaként
└── .feliratford.json   ← (új) projekt-konfiguráció
```

`.feliratford.json`:
```json
{
  "name": "My Drama S01",
  "language": "ko",
  "chunk_size": 100,
  "agents": 3,
  "review_model": "gemini-3.6-flash",
  "translate_model": "sonnet",
  "current_episode": "S01E03",
  "history": [
    {"step": "split", "file": "S01E01_eng.srt", "ts": "2026-05-07T10:00"}
  ]
}
```

### 3.3 Projekt-felfedezés

A `recent_projects` listából töltődik be a projektmenü. Egy mappa akkor
projekt, ha tartalmaz `.feliratford.json`-t **vagy** `CLAUDE.md`-t (utóbbi
visszafelé kompatibilitás miatt — meglévő projektek automatikusan
importálhatók).

---

## 4. UI tervek — több oldal

### 4.1 Indító képernyő (Welcome)
```
┌─────────────────────────────────────────────┐
│  Felirat-Fordító                       ⚙ ▼  │
├─────────────────────────────────────────────┤
│                                             │
│  📂 Új projekt létrehozása                  │
│  📂 Projekt megnyitása...                   │
│                                             │
│  ── Legutóbbiak ──────────────────────      │
│  • My Drama S01           2 órája           │
│  • Another Show S03       tegnap            │
│  • Sageuk K-drama         1 hete            │
│                                             │
└─────────────────────────────────────────────┘
```

### 4.2 Projekt fő képernyő — bal oldali navigáció

```
┌──────────────────────────────────────────────────────┐
│  My Drama S01 - S01E03                       ⚙ ▼     │
├──────────────────┬───────────────────────────────────┤
│ 📄 Áttekintés    │                                   │
│                  │   [Step 2: Translate]             │
│ 1️⃣ Felirat       │                                   │
│ 2️⃣ Fordítás      │   Input blokk mappa: blocks/...   │
│ 3️⃣ Összefűzés    │   Agent-ek:    [3 ▼]              │
│ 4️⃣ Ellenőrzés    │   Modell:      [sonnet ▼]         │
│ 5️⃣ Review        │   Chunk size:  [100]              │
│ 6️⃣ Glossary      │                                   │
│                  │   [▶ Indítás]                     │
│                  │                                   │
│                  │   ┌─ Folyamat ────────────────┐   │
│                  │   │ [09:32] block_001 ✓        │   │
│                  │   │ [09:33] block_002 ✓        │   │
│                  │   │ [09:34] block_003 — ...    │   │
│                  │   │ ░░░░░░░░░░░░░░ 30%         │   │
│                  │   └────────────────────────────┘   │
└──────────────────┴───────────────────────────────────┘
```

### 4.3 Oldalak (lépés-panelek)

#### **0. Áttekintés**
- Projekt név, sorozat, jelenleg dolgozott epizód
- Workflow státusz: melyik lépés kész, melyik nincs
- Quick links (CLAUDE.md / glossary.json megnyitása)

#### **1. Felirat (új funkcionalitás)**
- Videofájl tallózása (drag-drop)
- Detektált felirat-sávok listája (ffmpeg)
- **A:** beágyazott felirat extrahálás (ffmpeg)
- **B:** hardcoded → OCR (külső eszközzel, kihagyva MVP-ből)
- **C:** beszéd → Whisper STT (későbbi fázis)
- Output: `input/<név>_eng.srt`

#### **2. Fordítás**
- Input fájl tallózás (vagy auto a legutóbbi `input/`-ból)
- Beállítások: agent szám, modell, chunk size
- Részlépések auto: split → translate → merge
- Vagy külön gombok mindegyikre (haladó mód)

#### **3. Összefűzés** — külön, ha manuálisan akarja
#### **4. Ellenőrzés** — `verify_srt.py`
#### **5. Review**
- Tab vagy radio: Claude / Gemini
- Modell-választás (Gemini-nél `--model` is)
- Chunk size, start/end chunk
- Riport megjelenítés a generálás után — kattintható sorok

#### **6. Glossary**
- `glossary.json` táblázatos szerkesztő (kategóriánként tab)
- "Bővítés feliratpárból" gomb → `glossary_extract.py` interaktív
  (CLI confirmation-ek dialog-ablakká alakítva)

### 4.4 Globális Beállítások képernyő (⚙)
- **API kulcsok** tab
- **Default beállítások** tab (modell, chunk size, agent szám)
- **Eszközök** tab (ffmpeg, scripts_dir)
- **Projektek** tab (recent kezelés)

---

## 5. Backend — script orchestráció

### 5.1 Subprocess wrapper (Qt példa)

```python
class ScriptRunner(QObject):
    progress = Signal(str)            # új sor a stdout-on
    finished = Signal(int)            # exit code
    intervention_needed = Signal(str) # ha y/n kérdést kap

    def run(self, cmd: list[str], cwd: str):
        self.process = QProcess()
        self.process.setWorkingDirectory(cwd)
        self.process.readyReadStandardOutput.connect(self._on_output)
        self.process.finished.connect(self._on_finished)
        self.process.start(cmd[0], cmd[1:])
```

### 5.2 Élő stdout-megjelenítés

`QPlainTextEdit` widget, sor-folyamatosan érkező output-tal. Színezés
ANSI escape kódok alapján (zöld OK, piros HIBA).

### 5.3 Interaktív lépések (`glossary_extract.py`)

Jelenleg interaktív (y/n/e/q). GUI-integrációhoz két opció:

- **(a)** A scriptet módosítjuk: `--json-mode` flag → JSON-ban kommunikál
  (egyszerűbb GUI, kompatibilitás-törő ha valaki más is használja CLI-ből,
  de a sima mód marad változatlan)
- **(b)** A GUI a stdout-ot parsolja és a stdin-en beír (törékenyebb)

**Javaslat: (a)** — minimális invazív, CLI mód változatlan.

### 5.4 Hibakezelés

- Exit code != 0 → hibadialog, stderr megjelenítve
- Timeout → értesítés, "újraindítás" gomb
- Beavatkozást igénylő helyzet (pl. szekciószám-eltérés) → modális ablak

---

## 6. Felirat-extrahálás (új capability)

### 6.1 ffmpeg integráció
Beágyazott felirat-sávok detektálása MKV-ban:
```bash
ffmpeg -i video.mkv 2>&1 | grep Subtitle
ffmpeg -i video.mkv -map 0:s:0 output.srt
```

### 6.2 Whisper integráció (opcionális, későbbi fázis)
- `openai-whisper` vagy `faster-whisper`
- Lokálisan fut (CPU/GPU), nem API
- Nehéz függőség (~1-2 GB modell), opcionális modul

### 6.3 OCR (hardcoded feliratokhoz)
- Subtitle Edit beágyazás komplex
- **Kihagyva MVP-ből**, manuális workflow marad

---

## 7. Funkcionális modulok / kód-szervezés

```
feliratford_gui/
├── main.py
├── config/
│   ├── global_config.py    # ~/.feliratford/config.json
│   └── project_config.py   # .feliratford.json
├── runner/
│   ├── script_runner.py    # subprocess wrapper
│   └── workflow.py         # több-lépéses workflow
├── ui/
│   ├── main_window.py
│   ├── pages/
│   │   ├── welcome.py
│   │   ├── overview.py
│   │   ├── extract.py
│   │   ├── translate.py
│   │   ├── merge.py
│   │   ├── verify.py
│   │   ├── review.py
│   │   └── glossary.py
│   ├── widgets/
│   │   ├── console.py
│   │   ├── progress.py
│   │   └── settings_dialog.py
├── extractors/
│   ├── ffmpeg.py
│   └── whisper.py          # opcionális
├── resources/
│   ├── icons/
│   └── styles.qss
└── tests/
```

---

## 8. Munkamenet-flow (user-side)

1. **Indítás** → Welcome → "Új projekt" vagy létezőt nyit
2. **Új projekt:** mappa kiválasztása, sorozat-adatok kitöltése
   (CLAUDE.md sablonból generálva), üres `glossary.json` létrejön
3. **Felirat lépés:** videó tallózása → felirat extrahálva `input/`-ba
4. **Fordítás lépés:** beállítások → ▶ Indítás → konzol mutat → kész
5. **Review lépés:** Claude vagy Gemini → futtatás → riport
6. **Glossary bővítés** (opcionális, pár epizód után)

---

## 9. Megvalósítási fázisok (MVP → V1)

| Fázis | Tartalom | Idő |
|-------|----------|-----|
| **1. Vázlat** | PySide6 alap-app, Welcome + Overview, globális config, projekt megnyitás | 1-2 nap |
| **2. Workflow integráció** | Script runner (`QProcess`), Console widget, Translate oldal | 2-3 nap |
| **3. További lépések** | Split / merge / verify / Review oldalak | 2-3 nap |
| **4. Glossary & felirat** | Glossary szerkesztő, ffmpeg felirat-extrahálás | 2-3 nap |
| **5. Polish** | Téma, ikonok, packaging, hibakezelés | 2-3 nap |
| **6. (Későbbi)** | Whisper STT integráció | mérés szerint |

**Becslés: ~10-15 munkanap kompetens fejlesztőnek.**

---

## 10. Nyitott döntési pontok

> Ezekre érdemes választ adni, mielőtt kódolnánk.

1. **Stack:** PySide6 (javasolt), Flet, vagy customtkinter?
2. **Felirat-extrahálás scope MVP-ben:** csak ffmpeg, vagy + Whisper?
3. **OS scope:** csak Windows, vagy Mac is? (Mac packaging plusz munka)
4. **Többfelhasználós használat?** Ha nem, JSON kulcs OK; ha igen, OS keychain.
5. **`glossary_extract.py` módosítása `--json-mode` flag-gel?** (GUI integráció)
6. **Project template:** új projektnél a CLAUDE.md sablonból generálva,
   form-ban bekért adatokkal?
7. **Téma:** sötét/világos, vagy elég OS-default?
8. **Kötegelt feldolgozás:** több epizód egyszerre queue-ban, vagy 1-1?

---

## 11. Kockázatok

- **Subprocess-stdout parsing törékeny**: ha az output formátum változik,
  a GUI eltörik. Mitigáció: scriptek strukturált státusz-sorokat is adjanak
  (`STATUS: block_001 OK` formában).
- **Cross-platform packaging**: Mac-en code signing/notarization. Saját
  használatra ignorálható.
- **API kulcs sérülékenység**: JSON-ban olvasható; OS keychain alternatíva.
- **Hosszú futások (5-15 perc)**: a GUI nem fagyhat le — szigorú szálkezelés
  (`QThread` / `QProcess`).

---

## 12. Következő lépés

NE kódoljunk még. Először a **10. szakasz nyitott kérdéseire** választ adni,
és ha bármelyik részen másképp képzeled (pl. nem subprocess wrapper, hanem
library-konverzió), arról beszélni.

A válaszok alapján a következő körben **konkrét implementációs roadmap**
készül fájl-szintű strukturával és az első osztály-vázlatokkal.
