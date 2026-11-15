# 7. Gemini: modellek, limitek, kvóta

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Gemini modellek — mit érdemes választani

| Modell | Mire jó |
|---|---|
| `gemini-3.8-flash` | A `defaults.env` Gemini-modellje (API-n és Antigravityn is); a legújabb Flash. Az Antigravity-ágon mért review-n a 3.6-nál jóval több valódi hibát talált (lásd: [Antigravity fordító](04-forditas.md#antigravity-fordító-subtrpy-translate---provider-antigravity--alternatíva)). |
| `gemini-3.6-flash` | Az előző Flash: az API-n elérhető (Stable, saját napi kerettel), 2026 októberében csak átmenetileg nem volt hívható. A napi limitnél használt tartaléklista első eleme. Az Antigravityben csak Enterprise-előfizetéssel érhető el (lásd: [Antigravity fordító](04-forditas.md#antigravity-fordító-subtrpy-translate---provider-antigravity--alternatíva)). |
| `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` | Olcsó, gyors, **bő napi kvóta** free tier-en. Nagy tömegű fordításra, illetve ha a nem-lite napi limit elfogyott. |
| `gemini-flash-latest`, `gemini-flash-lite-latest`, `gemini-pro-latest` | Alias-ok, mindig az adott sáv legújabb kiadására mutatnak. Kényelmes, de nem determinisztikus (kiadásváltáskor csendben más modellt kapsz). |

Az aktuális modellek, free tier limitjeik és a kivezetések: `python subtr.py models`
(lásd lent). Ha `--model`-lel vagy a `.env` modell-soraiban olyan nevet adsz meg,
amelyet a Google már átirányít vagy leállított, a pipeline figyelmeztet, és az
utódot hívja; bejelentett, de még el nem jött leállásnál csak figyelmeztet.

## Gemini-modellek, limitek, kivezetések (`subtr.py models`)

A Gemini-modellek kínálata és a limitjeik néhány hetente változnak. A program
ezeket egy beépített adatfájlból ismeri (`subtr/gemini_models.json`): ebből
számolja a kvóta-előrejelzést, ebből tudja, melyik modellt vezette ki a Google,
és ebből választ, ha napi limitnél modellt kell váltani. Kézzel ne szerkeszd.

```powershell
python subtr.py models          # szöveges modellek: RPM / TPM / RPD, mai fogyás
python subtr.py models --all    # minden kategória
```

### A program a Free tier limitjeivel érkezik

A beépített adatfájl **a Gemini API ingyenes (Free tier) limitjeit**
tartalmazza: ez az, ami mindenkinek, minden új Google AI Studio projektnek
elérhető, előfizetés nélkül. Ha Free tierrel dolgozol, **nincs teendőd** — a
program új verziója a friss adatokat is hozza.

A limit **tierenként más**: fizetős tieren (Tier 1, 2, 3 — ha a projekthez
számlázás tartozik) a napi és percenkénti keret jóval nagyobb, és olyan
modellek is használhatók, amelyeknek Free tieren 0 a limitje (pl. a Pro
modellek). Hogy a te projekted melyik tieren van, az AI Studio rate-limit
oldalának fejlécében látszik (pl. „Free tier” vagy „Tier 1”).

### Saját limitek beállítása

Két esetben érdemes a saját limitjeidet beállítani: ha **fizetős tiered** van,
vagy ha a Google közben módosította a Free tier limitjeit, és nem akarsz a
program következő verziójára várni. Mindkettő ugyanígy megy:

1. Nyisd meg: https://aistudio.google.com/rate-limit (a projekt, amelyikhez a
   `GEMINI_API_KEY` tartozik)
2. Kapcsold **be** az „All models” kapcsolót
3. Jelöld ki és másold az egész oldalt: Ctrl+A, Ctrl+C (Macen Cmd+A, Cmd+C) —
   a szöveg a vágólapra kerül, **sehova nem kell beilleszteni**
4. Bármelyik fordítási mappádban, terminálban:
   `python subtr.py models refresh --local` — a program maga olvassa ki a
   vágólapról

A limitek **a gépedre** mentődnek (`~/.gemini_quota/models.json`, a
kvótanapló mellé), nem a program mappájába: így **minden fordítási mappádra
érvényesek**, és a program frissítése sem írja felül őket. Az API-kulcsodhoz
kötődnek: más kulccsal (vagy ha egy modell nincs a mentésben) a beépített adat
marad érvényben. A `python subtr.py models` fejléce mutatja, ha saját
limitekkel dolgozol. Ha a tiered változik, futtasd újra; a beépített adatokra
— például a program frissítése után — a `python subtr.py models reset-local`
állít vissza.

```powershell
python subtr.py models refresh --local       # saját limitek a vágólapról
python subtr.py models refresh --local --open   # előbb megnyitja a rate-limit oldalt
python subtr.py models refresh --local --file oldal.txt   # ha a vágólap helyett
                                             # fájlba illesztetted a szöveget
python subtr.py models refresh --local --dry-run   # csak kiírja, mi változna
python subtr.py models reset-local           # vissza a beépített adatokra
```

Ha a kimásolt szövegben kevesebb mint 10 modell van (jellemzően mert az
„All models” nincs bekapcsolva), a program nem menti el — különben a többi
modell adata elveszne (`--force`: mégis).

A limiteket API-kulccsal nem lehet lekérni, ezért kell a kimásolt oldal. A
többit a program magától tölti le: a modellek pontos azonosítóját és
státuszát (https://aistudio.google.com/docs/models), a kivezetéseket
(https://aistudio.google.com/docs/deprecations), és hogy az API ténylegesen
mely modelleket kínálja a kulcsodnak. Kiírja, mi változott, mire figyelj a
beállításaidban (pl. 0-s limit, közelgő leállás), és összeveti az AI Studio
használati adatát a saját naplójával.

Ezen felül, ha egy modell a kulcsodon belefut a napi limitbe, a program a
hibából kiolvassa a valódi limitet, és onnantól azt használja erre a kulcsra
(`subtr.py quota` — lásd lent) — ez tiertől függetlenül mindig a te kereted.

### Napi limitnél modellváltás

Ha a Gemini API-n egy modell napi kerete
elfogy, a futás nem áll meg feltétlenül:

| `SUBTR_GEMINI_ON_QUOTA` | Viselkedés |
|---|---|
| `ask` (alapérték) | terminálban felkínálja a tartaléklistáról a még használható modelleket (maradék kerettel), és megkérdezi, melyikre váltson; nem interaktív futásnál (pl. ha Claude Code futtatja) kérdés nélkül vált, mint az `auto` |
| `auto` | kérdés nélkül a lista első még használható modelljére vált, és kiírja |
| `off` | nem vált — a futás a napi limitnél megáll |

A tartaléklista sorrendje a preferencia: `SUBTR_GEMINI_FALLBACK_MODELS`
(`defaults.env`, felülírható a `.env`-ben). Csak olyan modellre vált, amelyik a
`gemini_models.json`-ban szöveges modellként szerepel — egy elírt név így nem
viheti a futást egy nem létező modellre. Kimarad, ami ma már kimerült, amit a
Google ugyanarra a modellre irányít át, a kulcsodra érvényes napi limitje 0,
vagy amit a kulcsod API-ja nem kínál. Csak a strukturált (`quotaId`-s) napi 429
vált modellt. A váltás folyamatszintű: a futás hátralévő hívásai már az új
modellel mennek. Hogy mit végzett más modell, az pontosan látszik: a fordítás
blokkonként (`[modell: …]` a kimenetben és a `translate.log`-ban, az
összegzésben blokklistával — szelektíven újrafordítható), a review
chunkonként (a .txt riport fejlécében, a JSON-ban külön `chunk_models`
mezőben; a `model` mező a beállított modell marad), megszakított review
folytatásakor a korábbi futás chunkjaira is. Napi limitnél ugyanazt a modellt
nem próbálja újra, és ha nem vált, a futás további hívásai kérés nélkül
ugyanazt a hibát kapják — aznap úgysem mennének.

### Ha a programot fejleszted: a beépített adat frissítése

A beépített `subtr/gemini_models.json` a `--local` nélküli
`python subtr.py models refresh`-sel frissül, Free tieres projekt oldaláról
(más tier oldalát nem fogadja el — a beépített adat mindenkinek a Free tier).
Ez csak annak a mappának a programpéldányát írja át, ahol futtatod — ezért a
fejlesztői példányban (git) futtasd, és a fájlt commitold. A `--no-limits`
csak a modell-azonosítókat és a kivezetéseket frissíti, a limiteket nem.

## Gemini kvóta — mennyi hívás van még ma? (`subtr.py quota`)

A Gemini API **nem adja vissza a maradék napi kvótát**: a Service Usage API
API-kulccsal 403-at ad, a válaszfejlécekben nincs `ratelimit-*`, a `models.get()`
csak token-limiteket ismer. A napi limitbe így csak akkor futnál bele, amikor
már megtörtént (429) — a `subtr.py quota` ezért **helyben könyveli** a
hívásokat, és a futás előtt megmondja, belefér-e a tervezett munka.

Csak Python stdlib, nincs telepítendő függőség.

```powershell
python subtr.py quota                  # mai fogyás modellenként
python subtr.py quota --days 7         # utolsó 7 nap
python subtr.py quota --projects       # projektmappa szerinti bontás is
python subtr.py quota --model gemini-3.1-flash-lite   # csak egy modell
python subtr.py quota --where          # hol van a napló
python subtr.py quota --reset          # mai számlálók nullázása
python subtr.py quota --forget-limit gemini-3.8-flash # megtanult limit elfelejtése
```

A `subtr.py translate --provider gemini` és a `subtr.py review --provider gemini`
(és minden más Gemini API-hívás) **automatikusan** használja: indulás előtt kiírja
a várható fogyást, és minden sikeres hívást elkönyvel. Ha a modul hiányzik, a
parancsok változatlanul futnak tovább — a kvótakövetés kényelmi funkció, nem
állíthatja meg a fordítást.

**A napló gépszintű, nem projektszintű** — ez a leggyakoribb félreértés:

```
~\.gemini_quota\usage.json          (felülírható: GEMINI_QUOTA_FILE env-változó)
```

A napi kvóta az **API kulcshoz** tartozik, nem a munkakönyvtárhoz. Ha egy gépen
több felirat-projekt fut ugyanazzal a kulccsal, mind ugyanabból a napi keretből
fogyaszt — ezért közös a napló, és a kulcs **ujjlenyomata** szerint van bontva
(maga a kulcs soha nem kerül a fájlba). A `--projects` megmutatja, melyik
mappából mennyi fogyott.

> ⚠️ **A nap nem helyi éjfélkor vált.** A Google ingyenes napi kvótája
> csendes-óceáni idő (PT) szerint nullázódik. A parancs PT szerint könyvel, és
> kiírja, hány óra van hátra a nullázásig.

**A limitek öntanulók — de csak a napi limit.** A Gemini többféle 429-et ad, és
csak az egyik jelenti azt, hogy elfogyott a napi keret:

| `quotaId` | Mit jelent | Mit csinál a könyvelés |
|---|---|---|
| `...PerDay...` | napi kérés-limit | megtanulja a pontos limitet, a napot kimerültnek jelöli |
| `...PerMinute...` | percenkénti rate limit | figyelmen kívül hagyja — a retry-logika átvészeli |
| `...Tokens...` | token-alapú limit | figyelmen kívül hagyja — nem kérésszám |

Ez a megkülönböztetés lényeges: magas `--agents` értéknél a percenkénti 429
rutinszerű, és ha azt napi limitnek vennénk, egy múló hiba rossz értéket égetne
be, és a nap hátralévő részére hamisan „kimerült"-nek jelölné a modellt.

A napi limit forrása, erősségi sorrendben: (1) a kulcsodra 429-ből tanult érték
(az a te tieredre mért szám); (2) a `models refresh --local`-lal mentett saját
limitek; (3) a programba épített `subtr/gemini_models.json` Free tier adata (a korlátlan
limit is ezekből jön); (4) becslés. Ha a tanult és a mentett érték eltér, a
`subtr.py models` szól. A megtanult
limitek **tartósak** (nem évülnek a napi számlálókkal), ezért a
`python subtr.py quota` kiírja őket — ha valamelyik hibásnak tűnik, a
`--forget-limit <modell>` törli. Ha sehonnan nincs adat, becslést használ, és
ezt `(becsült)` jelöléssel jelzi.

> **A számláló alsó becslés, a maradék ezért felső korlát.** A naplóba csak
> azok a hívások kerülnek, amelyek a `subtr.py` Gemini-ágán mentek ki
> **és** sikeresen vissza is tértek. Kimarad tehát: az API kulcs használata
> máshol (AI Studio webUI, curl, másik eszköz — ez a legnagyobb forrás), az
> 5xx-szel elhalt hívás, ami a szerveren már fogyaszthatott, és a válasz előtt
> megszakított futás. A 429-cel elutasított kérés viszont helyesen marad ki:
> az nem fogyaszt kvótát.
>
> A kiírások ezért „legalább ennyit használtál" / „legfeljebb ennyi maradt"
> formában fogalmaznak. Ha a könyvelés túl sokat mutat (pl. félresikerült
> teszt), a `--reset` nullázza a mai számlálókat; ha kevesebbet a valóságnál,
> azt az első napi 429 korrigálja — onnantól a maradék nullára vált.

---

[← 6. Provider, modell és effort](06-providerek.md) · [Tartalomjegyzék](README.md) · [8. Utómunka →](08-utomunka.md)
