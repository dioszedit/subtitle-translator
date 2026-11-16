# audio-asr add-on (hangsáv gépi átirata)

A videó hangsávjából **eredeti nyelvű „feliratot”** készít Whisperrel, a saját
gépeden futtatva. Akkor kell, ha a sorozat koreai, japán, kínai… nyelvű, de a
kiadásban **nincs eredeti nyelvű feliratsáv**, csak angol.

## Mire jó, és mire nem

**Jó:** a megszólítási regiszterhez. A koreai mondatvég (`-요` / banmal) vagy a
japán `です` / plain alak megmondja, ki tegez és ki magáz kit. Az angol `you`
ezt elfedi. A beszédszintet a Whisper megbízhatóan hallja. Támpontot ad a
névalakokhoz is.

**Nem jó:** fordítási forrásnak. Vannak benne félrehallások (főleg a nevekben),
egy sorban több beszélő mondata is lehet, és nem jelöli, ki beszél. A fordítás
továbbra is az angol feliratból készül.

## Telepítés (egyszer)

```bash
pip install faster-whisper
# kínaihoz opcionálisan (hagyományos → egyszerűsített írásjegyek):
pip install opencc-python-reimplemented
```

Kell még az **ffmpeg** (a `mkv-subs` add-onhoz is kell): macOS-en
`brew install ffmpeg`, Windowson `winget install ffmpeg`.

Az add-on a program `subtr` mappáját és a `mkv-subs` add-ont is használja, ezért
a teljes program mappájából futtasd, ne külön kimásolva.

A **large-v3** modell kb. 3 GB, és az első futáskor töltődik le. Ez eltarthat
egy darabig.

## Használat

```bash
# 1) milyen hangsávok vannak? (nem ír semmit)
python addons/audio-asr/transcribe.py "Season 01/Sorozat - S01E01.mkv" --list

# 2) átirat az egész évadra — ha egy hangsáv van és van nyelvcímkéje
python addons/audio-asr/transcribe.py "Season 01"/*.mkv

# 3) ha a hangsávnak nincs nyelvcímkéje, vagy több hangsáv van (eredeti + szinkron)
python addons/audio-asr/transcribe.py "Season 01"/*.mkv --lang kor

# 3/b) ha a hangsáv címkéje ROSSZ (pl. a koreai hang „eng” címkét kapott):
#      a sorszámot a --list mutatja
python addons/audio-asr/transcribe.py "Season 01"/*.mkv --track 1 --lang kor

# 4) a regiszter az átiratból — a fordítás marad angolból
python subtr.py register "input/asr/Sorozat - S01E01.kor.asr.srt" "input/asr/Sorozat - S01E02.kor.asr.srt"
```

Windowson `py addons\audio-asr\transcribe.py "Season 01\*.mkv" --lang kor`. A
`*.mkv` mintát a script maga bontja ki, mert a Windows parancssora ezt nem teszi meg.

**Kimenet:** `input/asr/Sorozat - S01E01.kor.asr.srt`. A `.asr` jelzi, hogy gépi
átirat. A pipeline a nyelvet így is felismeri (`kor`). A `register` ilyenkor
szól a modellnek, hogy félrehallások lehetnek benne, és a beszélő kilétére
egyetlen sorból ne építsen. A külön `input/asr/` mappa miatt az átirat nem
keveredik a fordítandó feliratok közé.

**Folytatható:** a kész részeket kihagyja, tehát egy félbeszakadt évad-futás
egyszerűen újraindítható. Futás közben a `.part` fájlba ír, és csak a végén
nevezi át, így félkész átirat nem kerül a mappába. Megszakításnál (Ctrl+C) vagy
hibánál a `.part` fájlt törli; az a rész a következő futáskor elölről indul. Felülírás: `--force`.

**Üres átirat:** ha egyetlen felirat sem készül (néma vagy rossz hangsáv), a
script hibát jelez, és nem ment fájlt, így a következő futás nem ugorja át.

**Mire nem használható:** a `subtr split` megáll, ha `.asr` fájlt kap, mert az
átirat nem fordítási forrás. A `subtr glossary` lefut rajta, de figyelmeztet,
és minden javaslatát bizonytalannak jelöli.

**Azonos nevű részek:** ha két bemenet ugyanarra a fájlra írna (pl. két évad
`E01.mkv` része egyszerre megadva), a második hibát kap, és nem írja felül az
elsőt. Ilyenkor futtasd őket külön, más `--out-dir` mappával.

## Kapcsolók

| Kapcsoló | Mit csinál |
|---|---|
| `--lang kor` | a hang nyelve (`kor`/`ko`, `jpn`/`ja`, `chi`/`zh`…); több hangsávnál ez választ |
| `--title …` | több azonos nyelvű hangsávnál a sáv címének részlete |
| `--track N` | a hangsáv sorszáma (a `--list` mutatja); a nyelvcímkét figyelmen kívül hagyja, rossz vagy hiányzó címkéhez — a `--lang` kötelező mellé |
| `--list` | csak listáz, nem ír át |
| `--out-dir …` | kimeneti mappa (alap: `input/asr`) |
| `--device auto` | hol fusson: `auto` (alap), `cpu`, `cuda`, `mps` |
| `--model large-v3` | Whisper-modell; a kisebbek (`medium`, `small`) gyorsabbak, de többet hibáznak |
| `--threads N` | processzorszálak, ha processzoron fut (alap: mind) |
| `--beam 5` | keresési szélesség (alap: 5) |
| `--force` | kész átirat felülírása |

## Mennyi ideig tart

Az `auto` beállítás NVIDIA-kártyán a kártyát, Macen a grafikus gyorsítót
használja, egyébként a processzort. A választott eszközt mindig kiírja. Ha egy
eszköz nem működik, magától a következőre vált, a processzor mindig marad
tartaléknak. NVIDIA-kártyán előbb a gyors `float16` módot próbálja, és ha a
kártya azt nem tudja (régebbi GTX-ek), `float32`-vel marad a kártyán. Ha a videókártya csak futás közben ad hibát (pl. hiányzó
CUDA-fájl vagy kevés videomemória), az adott részt elölről kezdi processzoron,
és a többi rész is ott megy tovább. Más hiba (pl. a kimeneti fájl nem írható,
mert nyitva van egy másik programban) nem indít újrafuttatást: a script kiírja,
és a következő résszel folytatja. Egy rész hibája nem állítja le az évadot.

**Macen a grafikus gyorsítóhoz a `ctranslate2` csomag 4.9-es vagy újabb
verziója kell.** Régebbivel a script kiírja, hogy az `mps` nem elérhető, és
processzoron fut tovább. Frissítés: `pip install -U ctranslate2`.

Mért értékek large-v3 modellel:

- Apple Silicon gépen, grafikus gyorsítóval: egy 60 perces rész kb. **9 perc**.
- Processzoron, int8-cal: egy rész nagyjából **10–15 perc**, a géptől függően.

## Mit szűr ki

- **Ismert Whisper-hallucinációk**, amelyeket zene vagy csend alatt ír ki,
  például „시청해 주셔서 감사합니다”, „ご視聴ありがとうございました”,
  „谢谢观看” (a kínaiak hagyományos írásjegyekkel is). Csak akkor dobja el, ha a sor teljes egészében ilyen, így valódi
  mondat nem vész el. A sima „감사합니다” (köszönöm) megmarad.
- **Beragadás:** ha ugyanaz a sor kettőnél többször jön egymás után, az első
  kettőt megtartja, a többit eldobja. Egy közbeeső eldobott sor (pl. zene
  alatti hallucináció) megszakítja a sorozatot.
- Üres és csak írásjelből álló sorok.

A végén kiírja, hány sort dobott el.

## Miért nyelvcímke szerint választ

A hangsávok sorrendje fájlonként változhat. Egy rossz nyelvű (pl. szinkron) sáv
átirata hibaüzenet nélkül használhatatlan lenne, ezért a script nem tippel:
ha több sáv közül nem egyértelmű, melyik kell, kilistázza őket, és a `--lang`
vagy a `--title` kapcsolót kéri. Ha maga a címke hibás, a `--track` dönt.

Kilépési kód: `0` siker (a kihagyott kész részek is), `1` hiba.
