# SRT Felirat Fordító — Claude Code projekt

## Mappaszerkezet

```
srt-translate/
├── CLAUDE.md                ← Feladat leírás (Claude Code ezt olvassa)
├── split_srt.py             ← 1. SRT szétvágása blokkokra
├── translate_parallel.py    ← 2. Párhuzamos fordítás indítása
├── merge_srt.py             ← 3. Blokkok összefűzése
├── verify_srt.py            ← 4. Ellenőrzés
├── review_with_claude.py    ← 5a. Stilisztikai review Claude-dal
├── review_with_gemini.py    ← 5b. Stilisztikai review Gemini API-val (opcionális)
├── glossary_extract.py      ← 6. Szójegyzék bővítése (interaktív)
├── glossary.json            ← Fordítási szójegyzék (kézzel validált)
├── input/                   ← Ide tedd az angol SRT fájlokat
├── blocks/                  ← Automatikusan jön létre
└── output/                  ← Kész magyar fájlok
```

## Előkészítés

1. Másold ezt a mappát oda, ahol dolgozni akarsz
2. Nyisd meg a `CLAUDE.md` fájlt és töltsd ki a sorozat adataival
3. Tedd az angol SRT fájlt az `input/` mappába

## Használat (PowerShell)

### Teljes folyamat

```powershell
# 1. Szétvágás blokkokra (150 szekciónként)
python split_srt.py input\Sorozat_S01E01_eng.srt

# 2. Fordítás 3 párhuzamos agent-tel
python translate_parallel.py blocks\Sorozat_S01E01_eng --agents 3

# 3. Összefűzés
python merge_srt.py blocks\Sorozat_S01E01_eng output\Sorozat_S01E01_hun.srt

# 4. Ellenőrzés
python verify_srt.py input\Sorozat_S01E01_eng.srt output\Sorozat_S01E01_hun.srt

# 5a. Stilisztikai review Claude-dal (riport: ..._REVIEW_CLAUDE.txt)
python review_with_claude.py output\Sorozat_S01E01_hun.srt

# 5b. Stilisztikai review Gemini-vel — opcionális (riport: ..._REVIEW_GEMINI.txt)
python review_with_gemini.py output\Sorozat_S01E01_hun.srt
# --pro flag-gel a drágább/alaposabb gemini-2.5-pro modell
```

### Gemini review beállítása (egyszeri)

```powershell
pip install google-genai python-dotenv pydantic
# Másold a .env.example-t .env néven, és töltsd ki:
# GEMINI_API_KEY=...   (https://aistudio.google.com/apikey)
```

### Egyedi blokk méret (pl. 200)

```powershell
python split_srt.py input\Sorozat_S01E01_eng.srt --block-size 200
```

### Csak egy blokk újrafordítása

```powershell
# A 3. blokk újrafordítása
python translate_parallel.py blocks\Sorozat_S01E01_eng --agents 1 --block 003
```

### Sikertelen blokkok újrafordítása

```powershell
# Egyszerűen futtasd újra — csak a hiányzókat fordítja!
python translate_parallel.py blocks\Sorozat_S01E01_eng --agents 3
```

### Hibás blokk törlése és újrafordítása

```powershell
# Töröld a hibás fordítást
del blocks\Sorozat_S01E01_eng\Sorozat_S01E01_eng_block_003_0301-0450_HUN.srt

# Futtasd újra — checkpoint észreveszi a hiányzót
python translate_parallel.py blocks\Sorozat_S01E01_eng --agents 1
```

### Szójegyzék bővítése (az első néhány rész után ajánlott)

```powershell
# Kifejezések kinyerése feliratpárból — interaktív jóváhagyás
python glossary_extract.py input\Sorozat_S01E01_eng.srt output\Sorozat_S01E01_hun.srt

# Egyéni glossary útvonal
python glossary_extract.py input\eng.srt output\hun.srt --glossary my_glossary.json
```

A `glossary.json`-t a `translate_parallel.py` automatikusan betölti és használja a fordításnál.

## Tippek

- **Agent szám:** 3 az ajánlott. 5-nél API rate limit jöhet, ami üres választ ad
- **Blokk méret:** 150 az alapértelmezett. Ha sok a hiba, csökkentsd 100-ra
- **CLAUDE.md:** Minél részletesebb a sorozat leírás, annál jobb a fordítás minősége
- **Checkpoint:** A translate script mindig csak a hiányzó blokkokat fordítja — biztonságosan újraindítható
