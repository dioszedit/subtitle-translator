# vtt2srt add-on (meglévő felirat átvétele)

WebVTT (`.vtt`) → SRT konverter. Akkor kell, ha egy sorozat korábbi részei
**már le vannak fordítva** más forrásból, vtt-ben, és a pipeline-nal
akarod folytatni: a `glossary`, `register`, `verify` és `review` parancsok
SRT-t várnak.

Csak Python stdlib, nincs telepítendő függőség.

## Mit csinál

- eldobja a `WEBVTT` fejlécet és a `NOTE` / `STYLE` / `REGION` blokkokat;
- a cue-azonosítót (sorszám vagy szöveges id) eldobja, és **1..N-ig újraszámoz**
  — a WebVTT-ben az azonosító opcionális, egy sorozaton belül is vegyes lehet;
- az ezredmásodperc-elválasztót `.`-ról `,`-ra cseréli, a rövid `MM:SS.mmm`
  alakot `HH:MM:SS,mmm`-re egészíti ki;
- az időbélyeg-sor végén álló cue-beállításokat (`align:`, `position:`, …) elhagyja;
- a cue-szöveget **változatlanul** viszi: `<i>`, `<b>`, `♫`, sortörések,
  `[kártyák]` maradnak; csak a WebVTT-specifikus `<c.osztály>` és `<v Név>`
  tageket bontja ki (a szöveg marad);
- CRLF → LF, BOM nélküli UTF-8.

Az időzítést **nem** módosítja, cue-t nem von össze és nem dob el: a kimenet
cue-száma megegyezik a bemenetével.

## Használat

```bash
python3 addons/vtt2srt/vtt2srt.py "Season 01/Sorozat - S01E01.hun.vtt"
python3 addons/vtt2srt/vtt2srt.py "Season 01"/*.hun.vtt          # több fájl
python3 addons/vtt2srt/vtt2srt.py input/*.eng.vtt --out-dir input  # más mappába
python3 addons/vtt2srt/vtt2srt.py x.vtt --force                   # létező .srt felülírása
```

| Kapcsoló | Jelentés |
|---|---|
| `vtt…` | Egy vagy több `.vtt` fájl |
| `--out-dir MAPPA` | Kimeneti mappa (alapból a `.vtt` mellé, azonos néven, `.srt`-vel) |
| `--force` | Meglévő `.srt` felülírása (enélkül hibával leáll) |

## Meglévő fordítás „betanítása” a pipeline-nak

Ha az 1–N. rész kész, és a maradékot a pipeline-nal fordítod, a következetesség
három lépésben vihető át (részletek: `steps.txt` → „Meglévő fordítás átvétele”):

1. `vtt2srt` a magyar és — ha van — az angol vtt-kre.
2. `python3 subtr.py glossary "input/…EXX.eng.srt" "output/…EXX.hun.srt"` —
   az utólagos mód a **ténylegesen használt** magyar alakot tanulja meg
   (nevek, megszólítások, helyszínek, dalszöveg-forma).
3. `python3 subtr.py register "output/…EXX.hun.srt" --hungarian` — a
   tegezés/magázás a kész magyar szövegből közvetlenül leolvasható.
