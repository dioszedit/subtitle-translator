# mkv-subs add-on (beágyazott feliratsávok)

Két script:

- `extract_subs.py` — a videófájl feliratsávjait listázza, illetve **nyelvcímke
  szerint** kicsomagolja `.srt`-be, a pipeline névkonvenciójával
  (`Sorozat - S01E01.jpn.srt`);
- `embed_subs.py` — a végén a **kész magyar feliratot** visszateszi az `.mkv`-ba,
  kérésre alapértelmezett sávként (lásd lent: *Beágyazás*).

Python oldalról csak stdlib; kell viszont **`ffmpeg` + `ffprobe`** a PATH-on
(macOS: `brew install ffmpeg`).

## Mikor kell

- **A fordítás forrásához**, ha nincs külön `.srt` fájl a kiadás mellett.
- **A megszólítási regiszterhez** — és ez a fontosabb eset. Az eredeti nyelvű
  sáv (japán, koreai, kínai…) grammatikailag jelöli a formalitást, az angol
  `you` nem. Fordíthatsz angolból úgy, hogy a regisztert az eredeti nyelvű
  sávból olvasod ki: `subtr.py register` a fájlnév `.jpn` tagjából felismeri a
  nyelvet, és átvált a „leolvasás" ágra. Lásd `README.md` → *Forrásnyelv*.
- Az eredeti nyelvű **CC**-sáv ráadásul gyakran **beszélőcímkés**
  (`（緑）`, `（伸子）`) — a regiszter-kinyerés ezeket szándékosan bennhagyja,
  mert ez az elsődleges támpont ahhoz, hogy ki beszél kihez.

## Mikor nem

Ha a kiadás mellett már ott a szükséges `.srt`, nincs mit kicsomagolni.

## Miért nyelvcímke szerint

A sávok **sorrendje fájlonként változik** — ugyanannak a sorozatnak az egyik
részében a japán a 3., a másikban az 5. stream:

```
S01E14:  2 eng | 3 jpn | 4 kor | 5 chi
S01E17:  2 eng | 3 kor | 4 chi | 5 jpn
```

Egy beégetett `ffmpeg -map 0:5` ezért **némán rossz nyelvet** csomagol ki: a
fájl létrejön, csak épp kínai van benne, és ez csak a tartalomból derül ki.
Ez a script mindig a `language` címke alapján választ.

## Használat

```bash
# mi van benne? (nem ír ki semmit, csak listáz)
python3 addons/mkv-subs/extract_subs.py "Season 01/Sorozat - S01E01.mkv"

# egy nyelv kicsomagolása
python3 addons/mkv-subs/extract_subs.py "Season 01/Sorozat - S01E01.mkv" --lang jpn
#   → "Season 01/Sorozat - S01E01.jpn.srt"

# egész évad az input/ mappába
python3 addons/mkv-subs/extract_subs.py "Season 01"/*.mkv --lang eng --out-dir input

# minden szöveges sáv
python3 addons/mkv-subs/extract_subs.py video.mkv --all
```

Kapcsolók: `--lang` (`jpn`/`ja` egyaránt jó), `--all`, `--title` (több azonos
nyelvű sáv szűkítése a sáv címére), `--out-dir`, `--force` (létező `.srt`
felülírása).

## Korlátok

- Csak **szöveges** sáv (`subrip`, `ass`/`ssa`, `mov_text`, `webvtt`). A képi
  feliratokat (PGS, VobSub) kihagyja és megnevezi — azokhoz OCR kell.
- Ha egy nyelvből **több sáv** van (pl. teljes + forced), nem tippel: kilistázza
  őket, és a `--title` kapcsolót kéri.
- A nyelvcímke a kiadóé — ha az rossz, ez a script is rosszul választ. Az első
  listázásnál a sáv címe (`„Japanese [Original] (CC)"`) általában elárulja.

Kilépési kód: `0` siker, `1` hiba.

## Beágyazás — `embed_subs.py`

A kész, lektorált `Season XX/<név>.hun.srt`-t szöveges (subrip) feliratsávként
beteszi az azonos nevű `<név>.mkv`-ba (`hun`, „Magyar”), **újrakódolás nélkül**,
majd lecseréli az eredeti `.mkv`-t. A `.hun.srt` a helyén marad — az a
javítható forrás; javítás után a parancs egyszerűen újrafuttatható.

```bash
# mi történne? (nem ír semmit)
python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt" --dry-run

# beágyazás, nem alapértelmezettként (a meglévő sávok jelölése nem változik)
python3 addons/mkv-subs/embed_subs.py "Season 01/Sorozat - S01E01.hun.srt"

# alapértelmezett sávként — egész évad
python3 addons/mkv-subs/embed_subs.py "Season 01"/*.hun.srt --default
```

- **Alapértelmezett:** `--default` esetén a magyar lesz az első és az
  alapértelmezett feliratsáv; a többiről **csak** a default jelölés kerül le
  (a `forced` és társai maradnak). Állandó beállításként a sorozat `.env`-jében:
  `MKV_SUBS_DEFAULT=1` — ezt egy futásra a `--no-default` felülírja.
- **Csak a saját sávját cseréli** (subrip + `hun` + „Magyar”). Minden más sáv
  megmarad: angol, eredeti nyelvű, a `hardsub-cover` dobozos ASS-sávja
  („Magyar (dobozos)”), és más, máshonnan származó magyar sáv is (erről szól).
- **Biztonság:** csere előtt ellenőrzi az új fájlt (videó-, hang- és
  mellékletsávok száma, hossz, az új sáv helye és jelölése); hibánál az
  eredeti érintetlen marad, ideiglenes fájl nem marad hátra. Több fájlnál egy
  hibás rész nem állítja le a többit.
- Csak `<név>.hun.srt` ágyazható be — a `.clean`/`.merge` és hasonló köztes
  változatot előbb nevezd át a végleges névre.
- A muxoló mag közös: a `hardsub-cover --mux` is ezt használja.

**Beégetett idegen feliratnál** a takaráshoz a dobozos ASS kell (`hardsub-cover`);
mellé a sima SRT-sáv tartaléknak jó: ha egy lejátszó elrontja az ASS-t, a sima
magyar sávra át lehet váltani. Ilyenkor az SRT-t `--default` NÉLKÜL ágyazd be,
hogy a dobozos maradjon az alapértelmezett (a sorrend mindegy: a `hardsub-cover
--mux` mindig a dobozost teszi alapértelmezetté).
