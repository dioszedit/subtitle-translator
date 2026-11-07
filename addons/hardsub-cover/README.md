# hardsub-cover add-on (beégetett idegen felirat takarása)

A kész magyar `.hun.srt`-ből **„dobozos” ASS** feliratot készít: minden felirat
fehér szövegként, a **szöveg méretéhez igazodó** fekete dobozban jelenik meg, a
videóba égetett (pl. kínai) felirat helyén, így azt eltakarja. A felirat
**nem** égetődik rá a videóra — a lejátszó rajzolja ki, ezért nincs
újrakódolás és minőségromlás.

Csak akkor kell, ha a forrásvideóban beégetett idegen nyelvű felirat van.

## Mit csinál

- fehér Arial 40-es szöveg átlátszatlan fekete dobozban (ASS `BorderStyle=3`):
  a dobozt a lejátszó rajzolja a szöveg köré, ezért **soronként a szöveg
  méretéhez igazodik** (12 px belső margóval), és csak a felirat idején látszik;
- a szöveg függőlegesen a beégetett felirat helyére kerül; kétsoros cue-nál
  az alsó sor marad ott, a felső fölé kerül;
- kompromisszum: ha a magyar szöveg rövidebb, a beégetett felirat két széle
  kilóghat a doboz mellől;
- **időben átfedő feliratok** (pl. dal + párbeszéd): a korábban kezdődött
  marad a beégetett felirat helyén, a többi fölé kerül, egymást nem takarva;
  amikor az alsó lejár, a fölötte lévő visszacsúszik a helyére — így a
  beégetett felirat végig takarva marad;
- a dőlt / félkövér megmarad (`<i>` → `{\i1}…{\i0}`); más tag (`<font>`)
  eltávolítva; nincs benne rajzparancs (`\p1`), ezért az ASS-t egyszerűsítő
  lejátszók sem írnak ki értelmetlen szöveget;
- az SRT-t soronként olvassa: dupla üres sor, hiányzó sorszám vagy ponttal írt
  időbélyeg nem gond; amit nem tud felhasználni (hibás időbélyeg, időbélyeg
  nélküli szöveg, üres vagy nulla hosszú felirat), azt **kiírja**, és a
  kilépési kód 1 lesz — csendben semmi nem esik ki;
- kimenet: `… .hun.dobozos.ass` az `.srt` mellé, vagy az `--out-dir` mappába;
- `--mux`: beteszi az azonos nevű `.mkv`-ba **alapértelmezett** feliratsávként
  (`hun`, „Magyar”), stream copy-val, majd lecseréli az eredeti `.mkv`-t.
  - Csak a **saját**, korábban betett sávját (ass + `hun` + „Magyar”) cseréli,
    így újrafuttatható (pl. feliratjavítás után). Minden más sáv megmarad —
    egy máshonnan származó magyar feliratsáv is (erről figyelmeztet).
  - Csere előtt ellenőrzi az új fájlt (videó-, hang- és mellékletsávok száma,
    hossz, az új sáv megléte és alapértelmezettsége); hibánál az eredeti
    érintetlen marad, ideiglenes fájl nem marad hátra.
  - Muxnál az ASS nem marad az `.mkv` mellett (a lejátszó külső feliratként is
    felvenné) — csak ha `--out-dir` is meg van adva.
  - Több fájlnál egy hibás rész nem állítja le a többit.

## Használat

```bash
# csak ASS (az .srt mellé)
python3 addons/hardsub-cover/cover_ass.py "Season 01/Sorozat - S01E02.hun.srt"

# csak ASS, próbához egy külön mappába
python3 addons/hardsub-cover/cover_ass.py "Season 01/Sorozat - S01E02.hun.srt" --out-dir proba

# ASS + beágyazás az mkv-ba
python3 addons/hardsub-cover/cover_ass.py "Season 01/Sorozat - S01E02.hun.srt" --mux
python3 addons/hardsub-cover/cover_ass.py "Season 01"/*.hun.srt --mux   # minden kész rész
```

## Beállítások (sorozatonként)

Minden érték állítható a sorozat `.env`-jében (`HARDSUB_*`, magyarázattal a
`.env.example` végén) vagy kapcsolóval. Elsőbbség: **kapcsoló > `.env` >
alapérték**. Az alapértékek egy 720p-s, alul középen egysoros beégetett
feliratra vannak beállítva. A script indításkor kiírja, melyik érték honnan jött.

| `.env` kulcs | Kapcsoló | Alap | Jelentés |
|---|---|---|---|
| `HARDSUB_PLAY_RES` | `--play-res` | `1280x720` | koordináta-rendszer; a lejátszó a valós felbontásra skáláz |
| `HARDSUB_X` | `--x` | `640` | a beégetett felirat vízszintes középpontja |
| `HARDSUB_Y` | `--y` | `650` | függőleges középpont (kétsoros magyarnál az alsó sor helye) |
| `HARDSUB_FONT` | `--font` | `Arial` | betűtípus |
| `HARDSUB_FONT_SIZE` | `--size` | `40` | betűméret |
| `HARDSUB_LINE_HEIGHT` | `--line-height` | `48` | egy kirajzolt sor magassága (~1,2 × betűméret) — a sorok és az átfedő feliratok elhelyezéséhez; betűméret-váltáskor arányosan állítsd |
| `HARDSUB_PAD` | `--pad` | `12` | a doboz belső margója; ha a beégetett felirat teteje/alja kilátszik, növeld |
| `HARDSUB_BOX_ALPHA` | `--box-alpha` | `0` | doboz átlátszósága 0–255 (0 = teljesen fedő) |

Mivel a lejátszó skáláz, a 720p-s értékek egy azonos elrendezésű 1080p
videón is jók; csak akkor kell hozzányúlni, ha a beégetett felirat máshol van.
Méréshez ments ki egy képkockát, ahol látszik a beégetett felirat (a koordinátákat
a `HARDSUB_PLAY_RES` rendszerében add meg):

```bash
ffmpeg -ss 00:06:08 -i "Season 01/Sorozat - S01E01.mkv" -frames:v 1 frame.png
```

## Próbakép / próbavideó

Az ASS kirajzolásához `libass`-os ffmpeg kell. Az `ass=` szűrő a fájlnevet a
szűrőleírásban kapja, ahol az aposztróf, vessző, `[`, `:` (Windowson a
meghajtóbetű is) elrontja — ezért a próbához az ASS-t egyszerű néven, a
próbamappából használd:

```bash
python3 addons/hardsub-cover/cover_ass.py "Season 01/Sorozat - S01E01.hun.srt" --out-dir proba
cp "proba/Sorozat - S01E01.hun.dobozos.ass" proba/check.ass
cd proba
# egy képkocka (az -ss a cue közepe; a -copyts kell, különben a feliratidők elcsúsznak)
ffmpeg -v error -ss 368 -copyts -i "../Season 01/Sorozat - S01E01.mkv" -vf ass=check.ass -frames:v 1 check_368.png
# 60 mp-es próbavideó
ffmpeg -v error -ss 330 -t 60 -copyts -i "../Season 01/Sorozat - S01E01.mkv" -vf ass=check.ass -c:a copy proba.mp4
```

## Függőségek

Python stdlib. A `--mux`-hoz `ffmpeg` + `ffprobe` kell (a sima Homebrew
`ffmpeg` is elég; ha van, az `ffmpeg-full`-t használja; más hely: `FFMPEG` /
`FFPROBE` környezeti változó). Az ASS kirajzolását (próbaképhez) csak
`libass`-os ffmpeg tudja: macOS-en `brew install ffmpeg-full`.

## Lejátszás

IINA, VLC, mpv, Plex asztali/HTPC kliens: rendben. Ha egy Plex-kliens
egyszerűsíti az ASS-t (eltűnik a doboz), a kliensben **Burn subtitles →
Always**, és a szerver égeti rá.
