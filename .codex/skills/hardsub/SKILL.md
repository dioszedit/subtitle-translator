---
name: hardsub
description: Videóba égetett idegen felirat takarása dobozos magyar ASS-sel (addons/hardsub-cover), a hely mérése és .env-beállítása, vizuális ellenőrzés és MKV-ba ágyazás. Használd beégetett felirat eltakarására vagy a kész felirat MKV-ba tételére.
---

# Hardsub-takarás

Az eszköz az `addons/hardsub-cover/cover_ass.py`; a kapcsolók és a `HARDSUB_*` beállítások leírása az `addons/hardsub-cover/README.md`-ben és a `.env.example` végén van. A felirat nem égetődik rá: ASS-sávként kerül az MKV-ba.

## Előfeltételek

- Bemenet a kész, lektorált `Season XX/<X>.hun.srt`, mellette az azonos nevű `<X>.mkv`. Félkész feliratot ne ágyazz be.
- Muxhoz bármilyen ffmpeg jó; a próbaképekhez `libass` kell (`ffmpeg -filters | grep -w ass`). macOS-en: `brew install ffmpeg-full` → `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`.

## Lépések

1. **Mérés (sorozatonként egyszer):** 3–4 beszédes cue közepén ments képkockát (`ffmpeg -ss <mp> -i <X>.mkv -frames:v 1 f.png`), nézd meg. Ha nincs beégetett felirat, a skill nem kell. Állapítsd meg a felbontást és a beégetett felirat középpontját, magasságát, szélességét.
2. **Beállítás:** az alapértékek 720p, alul középen, egysoros feliratra jók (`HARDSUB_Y=650`, `HARDSUB_PAD=12`). Eltérésnél javasolj `HARDSUB_*` sorokat a sorozat `.env`-jébe, és csak jóváhagyás után írd be; a `.env` többi sorához ne nyúlj, a tartalmát ne írd ki. A koordináták a `HARDSUB_PLAY_RES` rendszerében értendők. Kétsoros beégetett feliratnál `HARDSUB_Y` az alsó sor középe, a `HARDSUB_PAD`-ot növeld.
3. **Generálás és ellenőrzés:** `python3 addons/hardsub-cover/cover_ass.py "<X>.hun.srt" --out-dir <scratchpad>` (ne a `Season XX/`-be). A `!`-es sorok kimaradt cue-kat jelentenek → előbb az SRT-t kell javítani, szólj. Próbakép libass-os ffmpeg-gel rövid, hosszú, kétsoros és (ha van) átfedő cue-n; az `ass=` szűrő a különleges fájlneveket nem bírja, ezért másold `check.ass` névre, és a scratchpadból futtasd: `ffmpeg -ss <mp> -copyts -i "<abs>/<X>.mkv" -vf ass=check.ass -frames:v 1 c.png`. Ha a beégetett felirat teteje/alja kilátszik: `HARDSUB_PAD` vagy `HARDSUB_Y`. Rövid magyar szövegnél kilógó szél és az egymás fölé rakott átfedő feliratok szándékosak, csak jelezd.
4. **Beágyazás:** `python3 addons/hardsub-cover/cover_ass.py "<X>.hun.srt" --mux` — az eredeti MKV-t lecseréli (stream copy; csak a saját ass/`hun`/„Magyar” sávját cseréli, minden más sáv marad; csere előtt ellenőriz). Az első epizódnál kérj megerősítést; „megtartott másik magyar feliratsáv” figyelmeztetést jelezd. Ellenőrizd `ffprobe`-bal: az első feliratsáv `ass`, `language=hun`, `title=Magyar`, `default=1`.

A végén foglald össze a beállításokat, és jelezd: ha egy Plex-kliens elrontja a dobozt, a kliensben **Burn subtitles → Always**.
