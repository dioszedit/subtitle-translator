# Felirat fordítás — Claude Code utasítások

## Mi ez a projekt?

Koreai (és egyéb ázsiai) sorozatok angol feliratainak fordítása magyarra, SRT formátumban.

## Aktuális sorozat adatai

> **Minden új sorozatnál frissítsd ezt a részt!**
> Vedd ki a kommentből (töröld a `<!--` és `-->` sorokat) és töltsd ki.

```
<!--
Sorozat: [Cím] ([eredeti cím])
Műfaj: Koreai, [Romance / Historical / Fantasy / Comedy]
Szereplők:
  - [Név] - [szerep]
  - [Név] - [szerep]
Történet: [2-4 mondat a cselekményről]
Speciális kifejezések:
  - Your Highness = Fenséged
  - Your Majesty = Felséged
  - Crown Prince = Koronaherceg
  - Változatlanul hagyandó: Joseon, gibang, gisaeng
Eddig történt: [Korábbi epizódok összefoglalója, ha van]
-->
```

## Fordítási feladat

Amikor egy blokk fájlt kapsz fordításra:

### Input/Output

- **Input:** SRT blokk fájl a `blocks/` mappából (pl. `blocks/xyz/xyz_block_003_0301-0450.srt`)
- **Output:** ugyanoda, `_HUN.srt` végződéssel (pl. `blocks/xyz/xyz_block_003_0301-0450_HUN.srt`)

### SZIGORÚ SZABÁLYOK

1. **Sorszám + időbélyeg:** Az eredeti fájlból 1:1 másold. SOHA ne generáld fejből!
2. **Csak a szöveget fordítsd** angolról magyarra
3. **Megőrzendő elemek:**
   - HTML tagek: `<i>`, `</i>`, `<b>`, `</b>`
   - Kötőjeles párbeszéd: `- szöveg` (ne legyen belőle lista)
   - `[szögletes zárójelbe zárt megjegyzések]` — ezeket is fordítsd
   - Daljelölés: `♫` — hagyd meg, dalszöveget fordítsd ha van
   - Karakternevek — NE fordítsd le
4. **Természetes magyar nyelv:**
   - Ne tükörfordítás, hanem ahogy egy magyar ember mondaná
   - Használj magyar szólásokat ahol illik
   - Tegezés/magázás kontextusból
5. **Sorozat-epizód megnevezése:**
   - Az angol "episode" mindig **"rész"**, NEM "epizód"!
   - Pl. "Episode 1" → "1. rész" (NE "1. epizód")
   - "the next episode" → "a következő rész"
   - "in the previous episode" → "az előző részben"
6. **Nemhez kötött kifejezések:**
   - Az angol "get married" / "marry (you/me)" / "I'll marry you" stb. nemileg semleges, de a magyar NEM az!
   - **"get married" (önállóan, alany nélkül vagy 'we'-vel):**
     - ALAPÉRTELMEZETT: semleges forma → "megházasodni", "összeházasodni"
     - Ha BIZTOSAN férfi: "megnősülni" (NE "férjhez menni"!)
     - Ha BIZTOSAN nő: "férjhez menni"
   - **"I'll marry you" / "Marry me" / "I'm going to marry you" (BESZÉLŐ a házasulandó):**
     - A BESZÉLŐ neme dönt, NEM a megszólítotté!
     - Férfi → nő: "Feleségül veszlek." / "Légy a feleségem!"
     - Nő → férfi: "Hozzád megyek." / "Légy a férjem!" — SOHA "feleségül veszlek"
     - Ha nem egyértelmű, ki a beszélő: semleges → "Összeházasodunk." / "Házasodjunk össze!"
   - **"I want to marry her/him" (HARMADIK fél a házasulandó):**
     - Férfit akar elvenni: "feleségül akarja venni"
     - Nőhöz akar menni: "hozzá akar menni" / "férjhez akar menni hozzá"
   - Ha nem egyértelmű (mellékszereplő, árus, random karakter, 1-2 mondatos jelenet): MINDIG semleges
   - **Gyakori hiba:** automatikus "Feleségül veszlek." fordítás, miközben nő beszél férfihoz — ez nyelvtanilag és tartalmilag is rossz.
7. **Címkártya (sorozatcím):**
   - Ahol a sorozatcím címkártyaként megjelenik (gyakran a betétdal után, NEM feltétlenül az 1. szekcióban), MINDIG KÉT sorban szerepeljen — a magyar cím fölül, az eredeti cím alul, mindkettő szögletes zárójelben:
     ```
     [Magyar cím]
     [Original Title]
     ```
   - A sorozat magyar címét a "## Aktuális sorozat adatai" résznél rögzítsd, és minden részben KÖVETKEZETESEN ezt használd (epizódonként ne térj el tőle).

### Fordítási folyamat

```
1. Olvasd be az input blokkot a Read tool-lal (Bash/cat NEM elérhető)
2. Számold meg a szekciókat
3. Fordítsd le — sorszám + időbélyeg VÁLTOZATLANUL
4. Mentsd el a Write tool-lal: [OUTPUT_FÁJL]
5. Ellenőrizd: input és output szekciószám egyezik-e
```

### Szójegyzék (glossary.json)

Ha a projekt gyökérben létezik `glossary.json` fájl, használd a benne lévő fordításokat:

- **honorifics**: megszólítások (pl. "Your Highness" = "Fenséged")
- **place_names**: helyszínek
- **character_names**: karakternevek (ezeket NE fordítsd le, de itt van a helyes írásmódjuk)
- **special_terms**: speciális/kulturális kifejezések
- **phrases**: visszatérő kifejezések konzisztens fordítása

A szójegyzékben lévő fordításokat MINDIG használd, ne térj el tőlük!

### Gyakori hibák — KERÜLD EL

| Hiba | Megoldás |
|------|---------|
| Sorszám fejből generálva → eltolódik | Az eredetiből másolni |
| Időbélyeg felcserélődik | Eredetiből másolni |
| Karakternév lefordítva | "Yi Gang" → "Yi Folyó", Nevek listája fent |
| Tükörfordítás | Természetes magyar |
| Kötőjel → Markdown lista | Kötőjelet hagyni |
| Több/kevesebb szekció az outputban | Szekciószám ellenőrzés |
| "get married" mindig nőnemű | Alapból semleges (megházasodni), csak ha BIZTOSAN ismert a nem |
| "I'll marry you" → "Feleségül veszlek" nőtől férfinak | Nő → férfi: "Hozzád megyek." A beszélő neme dönt, nem a megszólítotté! |
| Helytelen igeragozás: "tetszesz nekem" | Helyesen: "tetszel nekem" — a "tetszik" ikes ige, E/2 alakja: "tetszel" |
| "framed me" → "kereteztek be" (tükörfordítás) | Bűnügyi kontextusban: "tőrbe csaltak", "rám kentek valamit", "hamis vádakkal illettek" |
| "episode" → "epizód" | MINDIG "rész": "1. rész", "a következő rész", "az előző részben" |
| "stalker" angolul maradva (jövevényszónak tűnik) | MINDIG fordítsd: "zaklató", "üldöző", "leselkedő"; igeként: "zaklat", "követ", "megfigyel" |
| "What brings you here?" → jelen idő: "mi hozza ma ide" | MAGYARUL MÚLT IDŐ: "mi hozta ma ide?", "mi szél hozta erre?" |
