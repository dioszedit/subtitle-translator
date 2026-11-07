---
name: hardsub
description: A videóba égetett idegen (pl. kínai) felirat takarása — a kész magyar SRT-ből fekete, szöveghez igazodó dobozos ASS-t készít az addons/hardsub-cover add-onnal, a beégetett felirat helyét képkockákon méri és a .env-be állítja, próbaképeken ellenőrzi, majd alapértelmezett sávként az MKV-ba teszi. Akkor használd, ha a felhasználó a beégetett felirat eltakarását, dobozos/fekete hátterű feliratot, vagy a kész felirat MKV-ba ágyazását kéri.
argument-hint: <kész .hun.srt vagy epizód, pl. "Season 01/Sorozat - S01E02.hun.srt">
---

# Hardsub-takarás — dobozos ASS a beégetett felirat fölé

Az eszköz az `addons/hardsub-cover/cover_ass.py`; a részletes leírás és a
beállítások táblázata az `addons/hardsub-cover/README.md`-ben van — a kapcsolókat
onnan vedd, ne fejből. A felirat **nem** égetődik rá a videóra: ASS-sávként kerül
az MKV-ba, a lejátszó rajzolja ki.

## 0. Előfeltételek

- **Bemenet**: a KÉSZ, lektorált magyar SRT (`Season XX/<X>.hun.srt`), mellette az
  azonos nevű `<X>.mkv`. Ha az SRT még az `output/`-ban van, vagy a pipeline nem
  ért végig (resegment, kézi lektorálás), szólj — a takarás az utolsó lépés.
- **ffmpeg**: a muxhoz (stream copy) bármilyen ffmpeg jó, de a próbaképekhez
  `libass` kell. Ellenőrzés: `ffmpeg -hide_banner -filters | grep -w ass`.
  macOS-en a sima Homebrew `ffmpeg` nem tudja → `brew install ffmpeg-full`
  (keg-only: `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`). A telepítést a
  felhasználó végzi; addig a mux megy, a vizuális ellenőrzés nem.

## 1. Van-e beégetett felirat, és hol?

Ezt sorozatonként EGYSZER kell megmérni; ha a `.env`-ben már vannak `HARDSUB_*`
értékek, és a felhasználó szerint jók, ugorj a 3. lépésre.

1. Válassz 3–4 időpontot az SRT-ből, ahol beszéd van (a cue közepe), és ments ki
   képkockákat a scratchpadba:
   `ffmpeg -v error -ss <mp> -i "<X>.mkv" -frames:v 1 frame_<mp>.png`
2. Nézd meg a képeket. Ha egyiken sincs beégetett felirat → állj meg, ez a
   skill nem kell (más időpontokkal még egyszer próbáld, mielőtt ezt kimondod).
3. Állapítsd meg: a videó felbontása (`ffprobe`), a beégetett felirat függőleges
   középpontja, magassága, legnagyobb szélessége, és hogy egy- vagy kétsoros-e.

## 2. Beállítás a `.env`-be

Az alapértékek (`HARDSUB_PLAY_RES=1280x720`, `HARDSUB_Y=650`, `HARDSUB_PAD=12`, …)
egy alul középen lévő, egysoros 720p-s beégetett feliratra jók. A lejátszó skáláz,
ezért a koordinátákat a `HARDSUB_PLAY_RES` rendszerében add meg (1080p videón
mért y-t szorozd 720/1080-nal, vagy állítsd a play-res-t 1920x1080-ra).

- Ha a mért hely az alapértéktől érdemben eltér, javasold a `HARDSUB_*` sorokat a
  sorozat `.env`-jébe (a magyarázat a `.env.example` végén van), és a
  felhasználó jóváhagyása után írd be. A `.env` titkokat is tartalmaz: csak a
  `HARDSUB_*` sorokat add hozzá/módosítsd, a többihez ne nyúlj, és ne írd ki a
  tartalmát.
- Ha a beégetett felirat kétsoros, a `HARDSUB_Y` az ALSÓ sor középe legyen, és
  a `HARDSUB_PAD`-ot úgy növeld, hogy a doboz a felső sort is fedje.

## 3. ASS generálás és vizuális ellenőrzés

A próba-ASS a scratchpadba menjen (`--out-dir`), ne a `Season XX/`-be — az
.mkv mellett a lejátszó külső feliratként is felvenné:

```bash
python3 addons/hardsub-cover/cover_ass.py "Season 01/<X>.hun.srt" --out-dir "<scratchpad>"
```

A script kiírja, melyik érték honnan jött (kapcsoló / .env / alap) — ellenőrizd.
Ha `!`-es sorokat ír (hibás időbélyeg, időbélyeg nélküli szöveg, üres felirat),
azok a cue-k KIMARADNAK: előbb az SRT-t kell javítani — szólj a felhasználónak.
Az „N átfedő felirat egymás fölé rendezve” sor tájékoztatás: ezeknél a próbaképet
is nézd meg.

Majd rajzolj próbaképeket `libass`-os ffmpeg-gel, legalább egy RÖVID, egy HOSSZÚ,
egy KÉTSOROS és (ha van) egy ÁTFEDŐ cue közepén. Az `ass=` szűrő a fájlnevet
nem viseli jól (aposztróf, vessző, `[`, `:`, Windowson a meghajtóbetű) — ezért
másold egyszerű névre, és a scratchpadból futtasd:

```bash
cp "<scratchpad>/<X>.hun.dobozos.ass" "<scratchpad>/check.ass"
cd "<scratchpad>" && ffmpeg -v error -ss <mp> -copyts -i "<abs. út>/<X>.mkv" -vf ass=check.ass -frames:v 1 check_<mp>.png
```

(`-copyts` kell, különben a gyors keresés után a feliratidők elcsúsznak.)

Nézd meg, és ítéld meg:

| Látod | Teendő |
|---|---|
| a beégetett felirat teteje/alja kilátszik a doboz fölött/alatt | `HARDSUB_PAD` ↑, vagy `HARDSUB_Y` igazítás |
| a magyar szöveg nem a beégetett helyén ül | `HARDSUB_Y` / `HARDSUB_X` |
| rövid magyar szövegnél a beégetett felirat két széle kilóg | **elfogadott kompromisszum** — a doboz szándékosan a szöveghez igazodik; csak jelezd |
| átfedő feliratok egymás fölött, külön dobozban | **szándékos** — a korábbi marad a beégetett helyén; ha a dobozok összeérnek vagy túl messze vannak: `HARDSUB_LINE_HEIGHT` |
| a szöveg túl kicsi / nagy | `HARDSUB_FONT_SIZE` (+ `HARDSUB_LINE_HEIGHT` arányosan) |

Állítás után generálj újra és nézd meg újra. A képeket mutasd meg / írd le a
felhasználónak, mielőtt a 4. lépésre lépsz. Ha a felhasználó videón akarja
látni, készíts 60 mp-es próbát a scratchpadba (parancs: add-on README).

## 4. Beágyazás az MKV-ba

```bash
python3 addons/hardsub-cover/cover_ass.py "Season 01/<X>.hun.srt" --mux
```

- **Az eredeti `.mkv`-t lecseréli** (stream copy, nincs újrakódolás). Csak a
  saját, korábban betett ASS-sávját (ass + `hun` + „Magyar (dobozos)”, vagy a
  korai „Magyar” címmel) cseréli; minden más sáv megmarad, a többiről csak a
  default jelölés kerül le. Csere előtt ellenőrzi az új fájlt; hibánál az eredeti
  érintetlen. Az első epizódnál erősíttesd meg; utána a felhasználó által
  jóváhagyott beállítással mehet a többi is.
- Ha „megtartott másik magyar feliratsáv” figyelmeztetést ír, jelezd a
  felhasználónak — lehet, hogy azt a sávot nem akarja a fájlban (a script
  szándékosan nem törli).
- Muxnál az ASS nem marad a `Season XX/`-ben; a próbához a scratchpadba írt
  példányok a scratchpadban maradnak.
- Több kész rész egyszerre: `"Season 01"/*.hun.srt --mux` — csak akkor, ha mind
  KÉSZ; egy félkész SRT beágyazása félrevezető.
- Ellenőrzés után: `ffprobe -v error -select_streams s -show_entries stream=codec_name:stream_tags=language,title:stream_disposition=default -of compact "<X>.mkv"`
  → az első feliratsáv `ass`, `language=hun`, `title=Magyar (dobozos)`, `default=1`.
- Feliratjavítás után a parancs újrafuttatható; a régi dobozos sávot cseréli.
- **Tartalék sima SRT-sáv** (ajánld fel): ha egy lejátszó elrontja az ASS-t, a
  felhasználó átválthat rá. `python3 addons/mkv-subs/embed_subs.py "Season 01/<X>.hun.srt"`
  — `--default` NÉLKÜL, hogy a dobozos maradjon az alapértelmezett.

## 5. Zárás

Röviden: melyik rész(ek) kaptak sávot, milyen beállítással (és ha a `.env`-be
került valami, mi). Emlékeztető lejátszáshoz: IINA/VLC/mpv/Plex asztali kliens
rendben; ha egy Plex-kliens elrontja (eltűnik a doboz), a kliensben **Burn
subtitles → Always**.
