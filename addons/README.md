# Add-onok

Opcionális segédscriptek a fordítási pipeline köré. Nem részei a `subtr`
csomagnak: külön futtatod őket, és nem minden sorozatnál kellenek. A közös
logikát (nyelvkódok, fájlminták kibontása) viszont a `subtr` mappából veszik,
ezért a teljes program mappájából futtasd őket, ne külön kimásolva.
Mindegyiknek saját README-je van a részletekkel.

| Add-on | Mikor | Mit csinál |
|---|---|---|
| [`tmdb-init/`](tmdb-init/README.md) | Sorozatonként **egyszer**, a legelső lépés | TMDB-linkből (hivatalos API) megírja a `TRANSLATION.local.md`-t (cím, magyar cím, szereplők, szinopszis), és a sorozat címét beírja a `glossary.json`-ba |
| [`srt-preclean/`](srt-preclean/README.md) | Epizódonként, **csak SDH-forrásnál** | A nyers SRT-ből kiszedi a hang-/effekt-cue-kat, újraszámoz, blokkokra bont |
| [`vtt2srt/`](vtt2srt/README.md) | **Csak ha van kész fordítás** `.vtt`-ben más forrásból | WebVTT → SRT (fejléc/NOTE/STYLE eldobása, újraszámozás, `.`→`,`), hogy a `glossary`/`register`/`verify`/`review` dolgozni tudjon vele |
| [`mkv-subs/`](mkv-subs/README.md) | Ha a felirat a videóban van, vagy kell az **eredeti nyelvű sáv a regiszterhez**; a végén, ha a kész felirat az **mkv-ba** kell | Feliratsávok listázása és kicsomagolása **nyelvcímke szerint** (a sávsorrend fájlonként változik); `embed_subs.py`: a kész felirat beágyazása — bármilyen nyelvű, a nyelv a fájlnévből (opcionálisan alapértelmezettként) — `ffmpeg` kell hozzá |
| [`audio-asr/`](audio-asr/README.md) | Ha a hang koreai, japán, kínai…, de **nincs eredeti nyelvű feliratsáv** | A hangsáv gépi átirata Whisperrel (`input/asr/…kor.asr.srt`) — regiszter-támpontnak, nem fordítási forrásnak; `faster-whisper` és `ffmpeg` kell hozzá |
| [`hardsub-ocr/`](hardsub-ocr/README.md) | Ha az eredeti nyelvű (pl. kínai) felirat **a képbe van égetve**, és nincs külön sávja | OCR-rel kiolvassa, és a forrás SRT cue-ihoz igazítja (`input/…chi.ocr.srt`, üres cue-nál `—`) — regiszter-támpontnak, nem fordítási forrásnak; macOS-en a beépített Vision, máshol RapidOCR (`pip install -e ".[ocr]"`), `ffmpeg` kell hozzá |
| [`hardsub-cover/`](hardsub-cover/README.md) | Epizódonként a végén, **csak ha a videóban beégetett idegen felirat van** | A kész `.hun.srt`-ből fekete, szöveghez igazodó dobozos ASS-t készít a beégetett felirat fölé; `--mux`-szal alapértelmezett sávként az `.mkv`-ba teszi |

```bash
# 0/a — új sorozat indítása (egyszer)
python addons/tmdb-init/init_local.py https://www.themoviedb.org/tv/12345-sorozat-cime

# 0/b — SDH-forrás előtisztítása (epizódonként, ha kell)
python addons/srt-preclean/preclean_srt.py "input/Sorozat - S01E01.eng.srt"

# 0/c — meglévő .vtt fordítás átvétele (csak ha a korábbi részek már kész vannak)
python addons/vtt2srt/vtt2srt.py "Season 01"/*.hun.vtt

# 0/e — feliratsávok a videóból; az eredeti nyelvű sáv a regiszterhez kell
python addons/mkv-subs/extract_subs.py "Season 01/Sorozat - S01E01.mkv"
python addons/mkv-subs/extract_subs.py "Season 01"/*.mkv --lang jpn --out-dir input

# 0/f — nincs eredeti nyelvű sáv: a hang átirata a regiszterhez (pip install faster-whisper)
python addons/audio-asr/transcribe.py "Season 01"/*.mkv --lang kor
python subtr.py register "input/asr/Sorozat - S01E01.kor.asr.srt"

# 0/g — BEÉGETETT eredeti nyelvű felirat: OCR a regiszterhez, az angol cue-ihoz igazítva
python addons/hardsub-ocr/ocr_subs.py "Season 01"/*.mp4                      # kínai (alap), forrás: input/…eng.srt
python addons/hardsub-ocr/ocr_subs.py "Season 01"/*.mkv --lang kor           # koreai
python subtr.py register "input/Sorozat - S01E01.chi.ocr.srt"

# utómunka után — a kész felirat beágyazása az mkv-ba (opcionális; a nyelv a fájlnévből)
python addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt" --dry-run        # mi történne (nem ír semmit)
python addons/mkv-subs/embed_subs.py "Season 01"/*.hun.srt --default                       # magyar, „Magyar”, alapértelmezett
python addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.eng.srt"                  # angol, „English”
python addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.chi.srt" --title "Chinese (Simplified)"   # saját cím
python addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.srt" --lang kor           # nyelvjelölés nélküli fájlnév

# utómunka után — BEÉGETETT idegen feliratnál: dobozos ASS a takaráshoz, alapértelmezett sávként
python addons/hardsub-cover/cover_ass.py "Season 01/Sorozat - S01E01.hun.srt" --out-dir proba   # előbb próba (ASS a proba/ mappába)
python addons/hardsub-cover/cover_ass.py "Season 01"/*.hun.srt --mux                          # beágyazás: „Magyar (dobozos)”, default
python addons/mkv-subs/embed_subs.py "Season 01"/*.hun.srt                                    # + tartalék sima „Magyar” sáv (default NÉLKÜL)
```

## Függőségek

Az add-onok a Python standard libet használják — nem kell telepíteni
semmit; kivétel az `audio-asr` (`faster-whisper`) és a `hardsub-ocr` RapidOCR-motorja
(`pip install -e ".[ocr]"`; macOS-en a beépített Vision miatt nem kell). Két külső feltétel van: az `mkv-subs`, a `hardsub-ocr` és a `hardsub-cover --mux`
`ffmpeg`-et hív (a `hardsub-cover` `ffprobe`-ot is; a PATH-on kell lenniük), a `tmdb-init` pedig egy ingyenes TMDB
API-kulcsot vár a `.env`-ben (`TMDB_API_KEY`, részletek a saját READMÉ-jében).

## Új add-on hozzáadása

Egy mappa, benne a script(ek) és egy README, ami leírja **mikor kell** és
**mikor nem**. Ha külső csomag kellene hozzá, az a `pyproject.toml`-ban egy
`[project.optional-dependencies]` extrába kerüljön, ne a fő függőségek közé —
a napi fordítási menet telepítését ne terhelje.
