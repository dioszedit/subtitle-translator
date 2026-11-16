# 4. Fordítás

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Forrásnyelv

A pipeline alapesetben **angol** feliratból fordít, de nem minden epizódhoz van
használható angol sáv — előfordul, hogy a kiadó rossz sávot muxol be, vagy egy
adott release-ben egyszerűen nincs angol felirat. Ilyenkor másik nyelvből is
lehet fordítani; a fordító-, review-, glossary- és regiszter-promptok
mindegyike a tényleges forrásnyelvhez igazodik.

### Hogyan derül ki a forrásnyelv?

Feloldási sorrend (a legerősebb nyer):

| # | Forrás | Példa |
|---|---|---|
| 1 | `--source-lang` kapcsoló | `--source-lang ger` |
| 2 | `SUBTR_SOURCE_LANG` env | `SUBTR_SOURCE_LANG=ger` |
| 3 | **a fájlnév `.kód` tagja** | `input/Sorozat - S01E02.ger.srt` |
| 4 | alapértelmezés | `eng` |

A 3. pont miatt a legtöbb esetben **nem kell semmit beállítani**: elég a
megszokott névkonvenció szerint elnevezni a fájlt. A `split` a blokkmappa nevét
is a fájlnévből képzi (`blocks/Sorozat - S01E02.ger`), így a `translate` is
felismeri.

```powershell
# Nincs teendő — a .ger tagból jön a nyelv
python subtr.py split "input\Sorozat - S01E02.ger.srt"
python subtr.py translate "blocks\Sorozat - S01E02.ger" --provider claude
python subtr.py review "output\Sorozat - S01E02.hun.srt"

# Kézi felülbírálás, ha a fájlnév nem árulkodik
python subtr.py translate "blocks\Sorozat - S01E02" --source-lang ger
```

Támogatott kódok (ISO 639-2/B — ugyanaz, amit az mkv-k a feliratsávokon
használnak): `ara`, `chi`, `eng`, `fre`, `ger`, `hin`, `ind`, `ita`, `jpn`,
`kor`, `may`, `pol`, `por`, `rus`, `spa`, `tha`, `tur`, `vie`. Az ISO 639-1
rövidítések (`de`, `fr`, `zh`, …) is elfogadottak.

### Miért számít ez a tegezés/magázásnál?

Az angol `you` **nem jelöli a formalitást**, ezért a magyar tegezés/magázás
döntést a pipeline közvetett jelekből következteti ki — vagy kikerüli. A legtöbb
más forrásnyelv viszont grammatikailag jelöli: német `Sie`/`du`, kínai `您`/`你`,
olasz `Lei`/`tu`, japán keigo, koreai beszédszintek.

Ahol van ilyen jel, ott a promptok **átfordulnak**: a modellnek nem
következtetnie kell, hanem leolvasnia — és a `register` parancs a
formalitás-alakot idézhető bizonyítékként kezeli. Ilyenkor a nem angol forrás
nemcsak pótlék, hanem **pontosabb** is az angolnál.

```powershell
# A regiszter a német Sie/du alapján áll össze, nem találgatásból
python subtr.py register "input\Sorozat - S01E02.ger.srt"
```

Új nyelv felvétele: `subtr/config.py` → `SOURCE_LANGS` (magyar név +
a formalitás-jelölés leírása; `None`, ha a nyelv nem jelöli).

### A regiszter forrása lehet MÁS, mint a fordításé

A forrásnyelv-váltás fent úgy szerepel, mint kényszermegoldás („nincs angol
sáv"). De a kettő **nem ugyanaz a döntés**, és nem is kell egyszerre meghozni:

> Fordíts angolból — a regisztert viszont az **eredeti nyelvű sávból** olvasd ki.

A pipeline ehhez készen áll: a `register` egy útvonalat kap, a forrásnyelvet a
fájlnév tagjából ismeri fel, tehát egy kicsomagolt `Sorozat - S01E01.jpn.srt`
magától a keigo-ágra fut, függetlenül attól, hogy a `translate` közben angolból
dolgozik.

```powershell
# 1) az eredeti nyelvű sáv kicsomagolása a videóból (nyelvcímke szerint!)
python addons\mkv-subs\extract_subs.py "Season 01\Sorozat - S01E01.mkv" --lang jpn

# 2) a regiszter ebből áll össze — a fordítás marad angolból
python subtr.py register "Season 01\Sorozat - S01E01.jpn.srt"
python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider claude
```

**Ha nincs eredeti nyelvű feliratsáv**, csak a hang koreai, japán vagy kínai,
akkor az `audio-asr` add-on a hangsávból készít gépi átiratot. A `register` ezt
is felismeri (`….kor.asr.srt`), és szól a modellnek a félrehallásokról.
Részletek: [`addons/audio-asr/README.md`](../addons/audio-asr/README.md).

```powershell
python addons\audio-asr\transcribe.py "Season 01\Sorozat - S01E01.mkv" --lang kor
python subtr.py register "input\asr\Sorozat - S01E01.kor.asr.srt"
```

Két nyeresége van, és a második legalább annyit ér, mint az első:

1. **A formalitás-alak közvetlen bizonyíték** — nem következtetés.
2. **Az eredeti nyelvű CC gyakran beszélőcímkés** (`（緑）`, `（伸子）`). A
   regiszter-kinyerés ezeket szándékosan bennhagyja a promptban, mert ez az
   elsődleges támpont ahhoz, hogy **ki beszél kihez**. Egy regiszter-hiba
   sokszor nem abból ered, hogy a formalitást olvastuk félre, hanem hogy a
   beszélőt — és az ilyen hiba *konzisztensnek* látszik, tehát magától nem
   bukik ki.

**Mennyit ér nyelvenként?** Nem egyformát — érdemes tudni, mennyire lehet
ráhagyatkozni:

| Forrásnyelv | Jel | Mennyire dönt |
|---|---|---|
| koreai | `-습니다`/`-요` vs. banmal, `-씨`/`-님` | **legerősebb** — szinte minden mondatvégen ott van |
| japán | `です`/`ます` vs. plain, tiszteleti alakok | **erős** — de lásd a monológ-csapdát alább |
| német, orosz, francia, spanyol, olasz | `Sie`/`du`, `вы`/`ты`, `vous`/`tu`, `Lei`/`tu` | erős, névmás-szintű |
| kínai | `您`/`你` | **gyenge** — a `您` a mai köznyelvben ritka, délen/Tajvanon alig; a hiánya nem bizonyít tegezést |
| angol | — | nincs |

**Monológ-csapda:** a japánban (és a koreaiban) a **belső monológ alapból plain
alakú**, akkor is, ha a szereplő az adott személyt magázza. Egy ilyen sorból
tehát NEM következik tegezés — a `register` promptja ezért csak a
megszólító mondatot fogadja el bizonyítéknak.

**Jelölt kivétel:** ha egy szereplő egy jelenet erejéig szándékosan kilép a
saját regiszteréből (a japán plain alak dramaturgiai csúcsponton), az **nem
következetlenség és nem is VÁLTÁS** — nem fordul meg tartósan a viszony. Ezt a
`TRANSLATION.local.md` regiszterében `kivétel:` sorként rögzítsd, különben a
következő review „kijavítja".

## Más forrásnyelv (nem angol forrásból)

A gépi oldal nyelvfüggetlen — a promptok, a forrás automatikus megkeresése és a
regiszter-kinyerés a felismert forrásnyelvhez igazodik (lásd a [*Forrásnyelv*](#forrásnyelv)
szakaszt). Ami **nem** áll át magától, az a szabályzat szövege:

| Mi | Mi történik | Mit tegyél |
|---|---|---|
| A `TRANSLATION.md` angol forrásnyelvi hibamintái konkrét angol kifejezésekre épülnek | Ezek a szabályok nem sülnek el — holt teher, de nem ártanak | Cseréld a saját forrásnyelved tipikus csapdáira |
| A `TRANSLATION.md` *Tegezés/magázás* szakasza | A döntési sorrend, a Megszólítási regiszter és a kikerülő megfogalmazás nyelvfüggetlen | A *Formalitás-jelek angol forrásban* alszakaszt cseréld a saját forrásnyelved jeleire; az *eredeti nyelvből átvett megszólítások* alszakasz nem ázsiai eredetinél elhagyható |
| A `glossary.json` kulcsa `en` | Csak elnevezés; funkcionálisan „forrásnyelvi kifejezés" | — |
| A forrás fájlneve nem követi a `.kód.srt` konvenciót | A review nem találja meg a forrást, és **forrás-összevetés nélkül** fut (több téves találat) | `--source "input\....srt"` kézzel — vagy nevezd át a fájlt a konvenció szerint |

A `glossary.json` szerepe nem angol forrásnál még nagyobb: mivel a hibaminta-szabályok
kiesnek, a konzisztencia jórészt a szójegyzéken múlik.

## Fordítás — opciók

A fordításhoz **öt alternatíva** van: a Claude Code-, a Gemini API-, a Codex
CLI-, a Grok CLI- és az Antigravity CLI-provider — mind a
`subtr.py translate --provider <claude|gemini|codex|grok|antigravity>`
parancson keresztül érhető el. Mindegyik ugyanazon a `blocks/` mappa-szerkezeten
dolgozik (`subtr.py split` outputja) és ugyanúgy checkpoint-ol — futtathatod
ugyanazon a projekten akár felváltva is.

### Claude Code fordító (`subtr.py translate --provider claude`)
```powershell
# Egyedi blokk méret szétvágáshoz
python subtr.py split "input\eng.srt" --block-size 100

# Claude modell-választás (alapérték a defaults.env-ben: sonnet; ajánlott: opus — lásd docs/06-providerek.md: „Claude — ajánlott modell és effort")
python subtr.py translate "blocks\eng" --provider claude --model haiku    # olcsóbb
python subtr.py translate "blocks\eng" --provider claude --model opus     # alaposabb

# Gondolkodási szint (csak claude): low | medium | high | xhigh | max
python subtr.py translate "blocks\eng" --provider claude --model opus --effort medium

# Csak egy konkrét blokk újrafordítása
python subtr.py translate "blocks\eng" --provider claude --agents 1 --block 003

# Sikertelen blokkok újrafordítása — egyszerűen futtasd újra
python subtr.py translate "blocks\eng" --provider claude --agents 3
# A parancs automatikusan csak a hiányzó blokkokat fordítja (checkpoint).

# Hibás blokk törlése és újrafordítása
del "blocks\eng\eng_block_003_0301-0450_HUN.srt"
python subtr.py translate "blocks\eng" --provider claude --agents 1
```

> A Claude-ág egy ismert CLI-mellékhatást magától javít: ha az agent a Read tool
> `sorszám<TAB>tartalom` megjelenítését másolja a kimenetbe (minden sor elé
> sorszám kerül), a parancs a prefixeket leszedi és `(Read-sorszámprefix
> eltávolítva)` üzenettel elfogadja a blokkot — a fordítás ilyenkor jó, csak a
> szerializálás romlott el.

### Gemini API fordító (`subtr.py translate --provider gemini`) — alternatíva
```powershell
# Modell: SUBTR_GEMINI_MODEL (defaults.env: gemini-3.8-flash)
python subtr.py translate "blocks\eng" --provider gemini --agents 3

# Tetszőleges Gemini modell --model flag-gel
python subtr.py translate "blocks\eng" --provider gemini --model gemini-3.8-flash
python subtr.py translate "blocks\eng" --provider gemini --model gemini-3.5-flash-lite   # olcsó, bő napi kvóta

# Csak egy konkrét blokk újrafordítása (auto zero-pad: 3 → 003)
python subtr.py translate "blocks\eng" --provider gemini --agents 1 --block 3

# Checkpoint és újraindítás ugyanúgy működik mint a Claude-ágnál.
```

### Codex fordító (`subtr.py translate --provider codex`) — alternatíva
```powershell
# Első futás: egy blokk, egy agent — ellenőrizd a kimenetet subtr.py verify-jal
python subtr.py translate "blocks\eng" --provider codex --block 1 --agents 1

# Ezután a hiányzó blokkok fordítása checkpointtal
python subtr.py translate "blocks\eng" --provider codex --agents 1

# Opcionális modell és óvatos párhuzamosítás
python subtr.py translate "blocks\eng" --provider codex --agents 2 --model gpt-5.6-terra
```

### Grok fordító (`subtr.py translate --provider grok`) — alternatíva
```powershell
# Modell: SUBTR_GROK_MODEL (defaults.env: grok-4.5). Előfeltétel: `grok` a PATH-on, `grok login` vagy XAI_API_KEY.
# Első futás: egy blokk, egy agent
python subtr.py translate "blocks\eng" --provider grok --block 1 --agents 1

# Hiányzó blokkok checkpointtal
python subtr.py translate "blocks\eng" --provider grok --agents 1

# Erősebb modell, ha kell
python subtr.py translate "blocks\eng" --provider grok --model grok-4.6
```

### Antigravity fordító (`subtr.py translate --provider antigravity`) — alternatíva
```powershell
# Modell: SUBTR_ANTIGRAVITY_MODEL + _EFFORT (defaults.env: gemini-3.8-flash + high). Előfeltétel: `agy` a PATH-on, bejelentkezve.
# A Gemini-modelleket az előfizetés adja — nincs GEMINI_API_KEY és napi API-kvóta.
python subtr.py translate "blocks\eng" --provider antigravity --agents 3

# Más modell (a teljes lista: `agy models`; az effort a név része: -low/-medium/-high)
python subtr.py translate "blocks\eng" --provider antigravity --model claude-opus-5-5-high
```

> **Modellválasztás (mérés, 2026-10):** egy 497 feliratos kínai drámarész
> Opus-fordítását három Antigravity-modell lektorálta, a találatokat egyenként az
> angol forráshoz mértük. A 19 valódi hibából a `gemini-3.6-flash-high` 10-et, a
> `gemini-3.8-flash-high` és a `gemini-3.1-pro-high` 16-16-ot talált (részben eltérőket); téves riasztás
> 1 / 1 / 0. Ezért a fordítás defaultja a `gemini-3.8-flash-high`, a review-é a
> `gemini-3.1-pro-high`; a glossary és a register a `gemini-3.8-flash-high`-et használja.
> **2026-10-13 óta** az Antigravityben a 3.1 Pro (és a 3.6 / 3.7 Flash) a hivatalos modell-lista
> ([antigravity.google/docs/models](https://antigravity.google/docs/models/)) szerint
> csak Enterprise-előfizetésben érhető el — azóta a review defaultja is a
> `gemini-3.8-flash-high` (a mérésen ugyanannyi valódi hibát talált, mint a Pro).
> Ha a `--model` vagy a `.env` ilyen nevet ad, a pipeline az `agy models` listájából
> ellenőrzi: ha nálad elérhető (Enterprise), azt használja; ha nem, figyelmeztet, és a
> `gemini-3.8-flash` azonos effortú változatát hívja. (Ez csak az Antigravity-ágra
> vonatkozik: a Gemini API-n a 3.6 Flash elérhető, lásd `python subtr.py models`.)
> Az effort az Antigravity-ágon a modellnév utótagja (`-low` / `-medium` / `-high`): a
> pipeline a `SUBTR_…_MODEL` és a `SUBTR_…_EFFORT` sorból fűzi össze, de a modellnévbe
> írt utótag is érvényes.
> A lista szerint a `gpt-oss-120b-medium` **2026. november 2-án** kikerül; a Gemini 4
> Argon csak Ultra / Enterprise előfizetéssel érhető el (a CLI-ből is) — hogy nálad mi
> választható, azt mindig az `agy models` mutatja.
> Egyetlen rész — kis minta; független, magyar nyelvű fordítási benchmark ezekre
> a modellekre nem volt elérhető.

> **Hogyan fut:** headless `agy`, üres ideiglenes munkamappában, JSON-sémás
> válasszal — a sorszámot és az időbélyeget a Python írja, mint a Codex/Grok-ágon.
> A prompt **minden platformon a stdin-en** megy (stream-json), mert a Windows
> parancssora 32 767 karakternél elhasal. Ez a bemeneti formátum az `agy`-ban
> nem dokumentált: ha egy frissítés után a hibaüzenet a stream-json bemenetre
> panaszkodik, a `subtr/providers/antigravity_cli.py` `build_stdin_message`
> függvényét kell igazítani. Átmeneti szerverhibára (`503 No capacity`,
> `429`) az adapter 20, majd 60 mp várakozással újrapróbál.

A fordító-ágak ugyanazt a `TRANSLATION.md` + `glossary.json` kontextust adják át a
modellnek system promptként, így a fordítások konzisztensek maradnak akkor is,
ha váltogatod őket. A Gemini-ág **strukturált JSON kimenetet** ad
(Pydantic séma), és a sorszám + időbélyeg Python oldalon garantáltan
változatlan marad — a modell csak a szöveget kapja és csak szöveget ad vissza.

> **Párhuzamosság (`--agents`):** a Gemini API nem tiltja a párhuzamos hívást,
> csak RPM (requests/min) korlátok vonatkoznak rá. Free tier-en ~10-30 RPM
> modelltől függően; `--agents 10` fölött 429 rate limit hibákra számíthatsz, amiket a
> retry logika kezel, de pazarol API-időt. A parancs `--agents > 10` esetén
> figyelmeztetést is ad. Részletek:
> [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) ·
> [saját tier-limitek (AI Studio)](https://aistudio.google.com/rate-limit).

---

[← 3. Szójegyzék és megszólítási regiszter](03-szojegyzek.md) · [Tartalomjegyzék](README.md) · [5. Review és javítás →](05-review.md)
