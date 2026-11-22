# 8. Utómunka

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Utómunka — a review után

A review riport (`_REVIEW_ANTIGRAVITY.txt`, `_REVIEW_CLAUDE.txt`, `_REVIEW_GEMINI.txt`, `_REVIEW_CODEX.txt`, `_REVIEW_GROK.txt`) csak **jelzi**
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
  arról lásd a [parancs leírását](05-review.md#nem-interaktív-alkalmazás-subtrpy-apply-auto).
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
párbeszéd-jelöléseket megőrzi; **idempotens**. A szóköz nélküli párbeszéd-
gondolatjelet egységesíti: `-Gyere!` → `- Gyere!` (a `merge` is; a `report`
`DASH` flaggel jelzi). Részletes leírás (töréspont-
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

### Opcionális: egységesség a részek között — `subtr.py consistency`

A review részenként dolgozik, ezért nem veszi észre, ha ugyanaz a tábla, dalsor
vagy név az egyik részben másképp szerepel, mint a másikban. Ezt a parancs
nézi meg a sorozat **összes kész feliratán** egyszerre. Nem hív modellt, csak
riportál, és pár másodperc alatt lefut:

```bash
python subtr.py consistency                    # a munkakönyvtár sorozata
python subtr.py consistency --no-dialogue      # csak tábla, dal és nevek
python subtr.py consistency --decisions        # + javaslatfájl részenként
```

Kész feliratnak a `Season 01/…hun.srt` (vagy `Season 02/…`) számít, ha van;
különben az `output/…hun.merge.srt`, ha az sincs, az `output/…hun.srt`. A forrás
az `input/…eng.srt` (vagy más nyelv, `--source-lang`, ugyanúgy, mint a review-nál).
A magyar feliratot a forrással **időzítés** alapján párosítja, ezért a
resegment utáni, átszámozott fájlon is működik. Ahol a magyar felirat és a
forrássor időben nem esik egybe (kettévágott dalsor, a dal mellé került
párbeszédsor), azt kihagyja, mert ott az összevetés félrevezető lenne.

Amit keres:

- **Azonos forrás, eltérő fordítás:**
  - képernyőszöveg (`[Old Mill Inn]` → egyszer `[Malom-fogadó]`, máskor `[Malom Fogadó]`),
  - dalszöveg (a főcím- vagy betétdal egy sora részenként másképp),
  - hosszabb párbeszédsor (alapból 25 karaktertől, `--min-chars`). Itt az
    eltérés sokszor jogos, mert a jelenet más, ezért ezt csak tájékoztatásnak
    vedd.
- **Írásmód-változatok:** ugyanannak a névnek több alakja (`Taolu` ↔ `Taolú`,
  `Nagy Zen` ↔ `Nagy Zhen`). A ragozás kötőjellel vagy anélkül (`Fang-ot` ↔
  `Fangot`) külön listában szerepel.

A `--decisions` kapcsolóval a tábla- és dal-eltérésekhez, ahol van egyértelmű
többségi változat, részenként egy javaslatfájl készül az `output/` mappába
(`<név>.hun_consistency.json`; ami egy korábbi futásból maradt, de már nem
érvényes, azt törli). Ugyanolyan formátumú, mint a review-triage
döntésfájlja, tehát az `apply-auto` vezeti át. **Mindig előbb `--dry-run`-nal**
nézd meg, mert a többség nem mindig a jó változat:

```bash
python subtr.py apply-auto "Season 01/Sorozat - S01E05.hun.srt" "output/Sorozat - S01E05.hun_consistency.json" --dry-run
```

A dalsoroknál csak a szöveg cserélődik, a felirat saját jelölése (`♫ … ♫`,
`<i> … </i>`, sor eleji gondolatjel) marad. Párbeszédhez és írásmódhoz nem készül automatikus
javaslat, azokról te döntesz.

SDH-forrásnál a `[…]` beszélőcímke vagy hangjegyzet, nem tábla: ilyenkor add
meg a `--sdh` kapcsolót.

### Opcionális: a kész felirat az MKV-ba

A végleges `Season XX/<név>.hun.srt` az `.mkv` mellett is működik (a lejátszók
külső feliratként felveszik). Ha egyetlen fájlban kell, vagy a magyar legyen az
alapértelmezett sáv, ágyazd be — újrakódolás nélkül, a `.hun.srt` a helyén marad:

```bash
python addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt" --default
```

Ha a videóban **beégetett idegen felirat** van, a takaráshoz a dobozos ASS-sáv
kell (`addons/hardsub-cover`, `/hardsub` skill); a sima SRT-sáv mellette
tartaléknak jó (alapértelmezett jelölés nélkül). Részletek:
[`addons/mkv-subs/README.md`](../addons/mkv-subs/README.md).

---

[← 7. Gemini: modellek, limitek, kvóta](07-gemini-kvota.md) · [Tartalomjegyzék](README.md) · [9. Tippek →](09-tippek.md)
