# Add-onok

Opcionális, önálló segédscriptek a fordítási pipeline köré. Nem részei a
`subtr` csomagnak: külön futtatod őket, és nem minden sorozatnál kellenek.
Mindegyiknek saját README-je van a részletekkel.

| Add-on | Mikor | Mit csinál |
|---|---|---|
| [`tmdb-init/`](tmdb-init/README.md) | Sorozatonként **egyszer**, a legelső lépés | TMDB-linkből (hivatalos API) megírja a `TRANSLATION.local.md`-t (cím, magyar cím, szereplők, szinopszis), és a sorozat címét beírja a `glossary.json`-ba |
| [`srt-preclean/`](srt-preclean/README.md) | Epizódonként, **csak SDH-forrásnál** | A nyers SRT-ből kiszedi a hang-/effekt-cue-kat, újraszámoz, blokkokra bont |
| [`vtt2srt/`](vtt2srt/README.md) | **Csak ha van kész fordítás** `.vtt`-ben más forrásból | WebVTT → SRT (fejléc/NOTE/STYLE eldobása, újraszámozás, `.`→`,`), hogy a `glossary`/`register`/`verify`/`review` dolgozni tudjon vele |
| [`mkv-subs/`](mkv-subs/README.md) | Ha a felirat a videóban van, vagy kell az **eredeti nyelvű sáv a regiszterhez** | Feliratsávok listázása és kicsomagolása **nyelvcímke szerint** (a sávsorrend fájlonként változik) — `ffmpeg` kell hozzá |

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
```

## Függőségek

Mindegyik add-on csak a Python standard libet használja — nem kell
telepíteni semmit. Két külső feltétel van: az `mkv-subs` `ffmpeg`-et hív
(annak a PATH-on kell lennie), a `tmdb-init` pedig egy ingyenes TMDB
API-kulcsot vár a `.env`-ben (`TMDB_API_KEY`, részletek a saját READMÉ-jében).

## Új add-on hozzáadása

Egy mappa, benne a script(ek) és egy README, ami leírja **mikor kell** és
**mikor nem**. Ha külső csomag kellene hozzá, az a `pyproject.toml`-ban egy
`[project.optional-dependencies]` extrába kerüljön, ne a fő függőségek közé —
a napi fordítási menet telepítését ne terhelje.
