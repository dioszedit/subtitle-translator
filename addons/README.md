# Add-onok

Opcionális, önálló segédscriptek a fordítási pipeline köré. Nem részei a
`subtr` csomagnak: külön futtatod őket, és nem minden sorozatnál kellenek.
Mindegyiknek saját README-je van a részletekkel.

| Add-on | Mikor | Mit csinál |
|---|---|---|
| [`mdl-init/`](mdl-init/README.md) | Sorozatonként **egyszer**, a legelső lépés | MyDramaList-linkből megírja a `TRANSLATION.local.md`-t (cím, szereplők, szinopszis) |
| [`srt-preclean/`](srt-preclean/README.md) | Epizódonként, **csak SDH-forrásnál** | A nyers SRT-ből kiszedi a hang-/effekt-cue-kat, újraszámoz, blokkokra bont |
| [`vtt2srt/`](vtt2srt/README.md) | **Csak ha van kész fordítás** `.vtt`-ben más forrásból | WebVTT → SRT (fejléc/NOTE/STYLE eldobása, újraszámozás, `.`→`,`), hogy a `glossary`/`register`/`verify`/`review` dolgozni tudjon vele |

```bash
# 0/a — új sorozat indítása (egyszer)
python addons/mdl-init/init_local.py https://mydramalist.com/70241-ni-ye-you-jin-tian

# 0/b — SDH-forrás előtisztítása (epizódonként, ha kell)
python addons/srt-preclean/preclean_srt.py "input/Sorozat - S01E01.eng.srt"

# 0/c — meglévő .vtt fordítás átvétele (csak ha a korábbi részek már kész vannak)
python addons/vtt2srt/vtt2srt.py "Season 01"/*.hun.vtt
```

## Függőségek

A `srt-preclean` és a `vtt2srt` csak a Python standard libet használja — nem
kell telepíteni semmit. Az `mdl-init` scrapel, ezért külön csomagok kellenek hozzá:

```bash
pip install -e ".[addons]"
```

Ezek szándékosan **nem** a `pyproject.toml` fő `dependencies` listájában
vannak: a napi fordítási menethez nincs rájuk szükség, és feleslegesen
lassítanák/törnék a telepítést azon a gépen, ahol csak fordítasz.

## Új add-on hozzáadása

Egy mappa, benne a script(ek) és egy README, ami leírja **mikor kell** és
**mikor nem**. Ha külső csomag kell hozzá, az a `pyproject.toml`
`[project.optional-dependencies]` `addons` extrájába kerüljön, ne a fő
függőségek közé.
