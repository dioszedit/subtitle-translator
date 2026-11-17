# hardsub-ocr add-on (beégetett felirat kiolvasása)

A videó képébe **beégetett** (hardsub) idegen nyelvű feliratot OCR-rel
kiolvassa, és segédfeliratot készít belőle, ami **a forrás (pl. angol) SRT
cue-ihoz van igazítva**: ugyanazok a sorszámok és időbélyegek, cue-nként a
kiolvasott szöveg, és `—`, ha abban a cue-ban nem talált semmit.

A nyelv tetszőleges: kínai, koreai, japán, thai, vietnámi, akár latin betűs is
(`--lang`). Az alábbi példák a kínait használják, mert ezzel próbáltuk ki
először.

## Mire jó, és mire nem

**Jó:** a megszólítási regiszterhez és a névalakokhoz. A kínai 你/您, a koreai
`-요` / banmal vagy a japán `です` / plain alak megmondja, ki tegez és ki
magáz kit. Az angol `you` ezt elfedi. Ugyanaz a szerepe, mint az
[`audio-asr`](../audio-asr/README.md) átiratának, csak nem a hangból, hanem a
képből.

**Nem jó:** fordítási forrásnak. OCR-hibák vannak benne (főleg ritka
írásjegyeknél és neveknél), és a dalszöveg vagy a képre írt felirat cue-i
gyakran üresek maradnak. A fordítás továbbra is az angol feliratból készül.

## Mikor kell, és mikor nem

| Helyzet | Melyik add-on |
|---|---|
| A videóban van **eredeti nyelvű feliratsáv** (szöveges sáv az mkv-ban) | [`mkv-subs`](../mkv-subs/README.md) — pontosabb, gyorsabb, nem kell OCR |
| Nincs ilyen sáv, de a felirat **a képbe van égetve** | **ez az add-on** |
| Nincs se sáv, se beégetett felirat, csak a hang eredeti nyelvű | [`audio-asr`](../audio-asr/README.md) |

Ha a beégetett feliratot a kész magyar felirattal **takarni** is akarod, az a
[`hardsub-cover`](../hardsub-cover/README.md) dolga; a kettő független egymástól.

## Telepítés

Kell az **ffmpeg** (a `mkv-subs` add-onhoz is kell): macOS-en
`brew install ffmpeg`, Windowson `winget install ffmpeg`. Az add-on a program
`subtr` mappáját és a `mkv-subs` add-ont is használja, ezért a teljes program
mappájából futtasd, ne külön kimásolva.

Az OCR-motor:

- **macOS: Vision** (a rendszer beépített szövegfelismerője) — nem kell
  telepíteni semmit, csak a Swift-fordítót, ami az Xcode Command Line Tools
  része: `xcode-select --install`. A kis segédprogramot (`vocr.swift`) az első
  futáskor lefordítja (egyszer, néhány másodperc), és a felhasználói
  cache-mappába teszi (`~/Library/Caches/subtitle-translator/hardsub-ocr/`).
  Csak akkor fordítja újra, ha a forrás vagy a fordító változott. A helyet a
  `HARDSUB_OCR_CACHE_DIR` környezeti változó felülírja.
- **Windows, Linux (vagy macOS-en kérésre): RapidOCR**:

  ```bash
  pip install -e ".[ocr]"          # vagy: pip install rapidocr onnxruntime
  ```

  A felismerő modellek az első futáskor töltődnek le.

Az `--engine auto` (alap) macOS-en a Visiont, máshol a RapidOCR-t választja.

## Használat

```bash
# egy rész; a forrás SRT a videó nevéből: input/Sorozat - S01E01.eng.srt
python addons/hardsub-ocr/ocr_subs.py "Season 01/Sorozat - S01E01.mp4"

# egész évad
python addons/hardsub-ocr/ocr_subs.py "Season 01"/*.mp4

# koreai beégetett felirat
python addons/hardsub-ocr/ocr_subs.py "Season 01"/*.mkv --lang kor

# megadott forrással, próbamappába
python addons/hardsub-ocr/ocr_subs.py "Season 01/Sorozat - S01E01.mp4" \
    --ref "input/Sorozat - S01E01.eng.srt" --out-dir proba

# a regiszter ebből — a fordítás marad angolból
python subtr.py register "input/Sorozat - S01E01.chi.srt"
```

Windowson `py addons\hardsub-ocr\ocr_subs.py "Season 01\*.mp4"`. A `*.mp4`
mintát a script maga bontja ki, mert a Windows parancssora ezt nem teszi meg.

**Kimenet:** `input/Sorozat - S01E01.chi.srt` (a nyelvkód a `--lang`-ból). A
pipeline a fájlnévből felismeri a nyelvet, így a `register` magától a kínai
ágon fut.

**Forrás SRT:** ha nem adod meg (`--ref`), az `input/` mappában (`--ref-dir`)
keresi a videó nevéhez illő `<név>.<forrásnyelv>.srt` fájlt; az angol az első.
Az OCR nyelvével azonos kódú fájlt (pl. egy korábbi `.chi.srt` kimenetet) nem
veszi forrásnak. Több résznél a `--ref` nem adható meg, ott a `--ref-dir` dönt.

**Kész rész:** ha a kimenet már létezik, kihagyja (`KÉSZ, kihagyva`);
felülírás: `--force`. Félkész fájl nem marad: a végén egyben írja ki.

**Mennyi ideig tart:** egy 48 perces, 720p-s rész (~900 cue) Apple Silicon
Macen, Visionnel kb. 2 perc. A RapidOCR processzoron lassabb (ugyanott kb.
0,25 mp/képkocka, egy rész nagyjából 8–10 perc).

## Hogyan dolgozik

1. Az ffmpeg a videóból kivágja a **felirat-sávot** (alapból a kép magasságának
   83,3%–98,6% közti része, ez 1280×720-on a 600–710. pixelsor), másodpercenként
   4 képkockát (`--fps`). Az arány miatt 1080p-n is ugyanazt a sávot vágja.
2. Cue-nként 1–2 képkockát olvas: a cue 35%-ánál és 70%-ánál, a 0,8 mp-nél
   rövidebb cue-nál a felénél.
3. **Szűrés:**
   - reklám: webcímek (`.com`, `www.`…) és a nyelv kulcsszólistája (kínainál
     fogadási/kaszinó-hirdetések szavai: 官方, 投注, 娱乐, 平台, 百家乐, 世界杯,
     足球, 篮球…), bővíthető: `--ad-extra`;
   - **nem latin írású** nyelvnél (kínai, koreai, japán, thai…) a latin betűs
     vagy számot tartalmazó sor is reklámnak számít — latin betűs nyelvnél ez
     magától kikapcsol (`--drop-latin`);
   - csak az a sor marad, amiben van **a nyelv írásrendszeréből** karakter
     (kínainál írásjegy, koreainál hangul, japánnál kana vagy kanji, thainál
     thai írás, latin betűs nyelvnél latin betű).
4. A képkockák közül a legjobb jelölt nyer: a legnagyobb megbízhatóság (a
   leggyengébb sora szerint), egyenlőnél a hosszabb.
5. **Pótló kör** az üresen maradt cue-kra: a cue több képkockája (legfeljebb
   8, egyenletesen elosztva), nyersen és **binarizálva** is (a fehér felirat
   feketére, minden más fehérre — így a világos háttér előtti felirat is
   olvasható). Itt csak a legalább 0,5 megbízhatóságú találat számít.

Mért eredmény (kínai beégetett felirat, 720p, Vision): kb. 890 cue-ból
15–50 marad üres, főleg dalszöveg és képi felirat, aminek nincs kínai
megfelelője.

## Beállítások

Elsőbbség: **kapcsoló > `.env` (`HARDSUB_OCR_*`) > alapérték**, ahogy a
`hardsub-cover`-nél. A `.env`-et a munkakönyvtárból (vagy fölötte) keresi. Az
indításkor kiírja, melyik érték honnan jött. Mintát a `.env.example` ad.

| Kapcsoló | `.env` kulcs | Alap | Mit csinál |
|---|---|---|---|
| `--lang` | `HARDSUB_OCR_LANG` | `chi` | a beégetett felirat nyelve (`chi`, `kor`, `jpn`, `tha`, `vie`, `eng`…); a kimenet nevében is ez |
| `--engine` | `HARDSUB_OCR_ENGINE` | `auto` | `auto`, `vision`, `rapidocr` |
| `--engine-lang` | `HARDSUB_OCR_ENGINE_LANG` | – | a motor saját nyelvkódja, ha az alap leképezés nem jó: Vision pl. `zh-Hant,zh-Hans` (hagyományos kínai), RapidOCR pl. `chinese_cht` |
| `--top` | `HARDSUB_OCR_TOP` | `0.833` | a felirat-sáv teteje: arány a kép magasságához (0–1) vagy pixel (pl. `600`) |
| `--bottom` | `HARDSUB_OCR_BOTTOM` | `0.986` | a felirat-sáv alja, ugyanígy |
| `--fps` | `HARDSUB_OCR_FPS` | `4` | kivágott képkocka másodpercenként |
| `--min-conf` | `HARDSUB_OCR_MIN_CONF` | `0` | a fő körben az elfogadás legkisebb megbízhatósága (0–1) |
| `--retry-min-conf` | `HARDSUB_OCR_RETRY_MIN_CONF` | `0.5` | a pótló körben ugyanez |
| `--retry-frames` | `HARDSUB_OCR_RETRY_FRAMES` | `8` | a pótló körben cue-nként legfeljebb ennyi képkocka; `0` = nincs pótló kör |
| `--bin-threshold` | `HARDSUB_OCR_BIN_THRESHOLD` | `215` | a binarizálás küszöbe (0–255) |
| `--ad-extra` | `HARDSUB_OCR_AD_EXTRA` | – | további reklám-minta (regex, pl. `abc\|xyz`) a nyelv alaplistája mellé |
| `--drop-latin` | `HARDSUB_OCR_DROP_LATIN` | `auto` | latin betűs/számos sor eldobása: `auto` (csak nem latin írású nyelvnél), `1`, `0` |
| `--ref`, `--ref-dir` | – | `input` | a forrás SRT, illetve hol keresse |
| `--out-dir` | – | `input` | kimeneti mappa |
| `--force` | – | – | kész kimenet felülírása |

**A felirat-sáv helye** videónként más lehet. Egy kimentett képkockán mérd meg:

```bash
ffmpeg -ss 00:06:08 -i "Season 01/Sorozat - S01E01.mp4" -frames:v 1 frame.png
```

Ha a felirat két sorban is megjelenhet, a sáv mindkét sort fogja át. A túl
magas sáv sem baj, csak a képre tett egyéb szöveg (logó, reklám) is belekerülhet
— azt a szűrés többnyire kiszedi.

Kilépési kód: `0` siker (a kihagyott kész részek is), `1` hiba.
