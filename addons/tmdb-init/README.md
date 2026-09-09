# TMDB init add-on (új sorozat indítása)

Egy **új sorozat** fordításának legelső lépése: a
[TMDB](https://www.themoviedb.org/) hivatalos API-járól lekéri a sorozat
adatait, és megírja belőlük a `TRANSLATION.local.md` fájlt — abban a
formában, amit a `TRANSLATION.md` „Aktuális sorozat adatai” szakasza vár.

Ezen felül felveszi a **sorozat (és ha kiolvasható, a forrásmű) címét** a
`glossary.json`-ba, hogy a fordító később ne próbálkozzon a lefordításukkal
(lásd [A címek a szójegyzékben](#a-címek-a-szójegyzékben)).

Sorozatonként egyszer kell futtatni, nem epizódonként.

> This product uses the TMDB API but is not endorsed or certified by TMDB.

## Telepítés

Külső csomag **nem kell** (csak a standard lib). Egyetlen dolog szükséges: egy
ingyenes TMDB API-kulcs a `.env`-ben:

```
TMDB_API_KEY=...        # https://www.themoviedb.org/settings/api
```

A kulcs regisztráció után a TMDB profil *Settings → API* oldalán igényelhető
(a „Developer” opció, nem kereskedelmi használatra ingyenes). A script a
`.env`-et a **munkakönyvtárból** tölti be, ugyanúgy, mint a `subtr` parancsok.

## Használat

```bash
python addons/tmdb-init/init_local.py https://www.themoviedb.org/tv/12345-sorozat-cime
```

A link a TMDB sorozat-oldaláé (`/tv/<id>-<slug>`); a slug elhagyható, és a
puszta szám is elfogadott. **Film-linket (`/movie/`) nem kezel** — a pipeline
sorozatokra van szabva.

```
Lekérés: TMDB tv/12345
Magyar cím a TMDB-ről: Irodai szikrák  (ellenőrizd — --hu-title felülírja)
Kész: TRANSLATION.local.md

Még kitöltendő (3 sor):
  - TODO: Lu Yan → Shen Qing: MAGÁZ | TEGEZ  (viszony)
  ...
```

| Kapcsoló | Jelentés |
|---|---|
| `url` | A sorozat TMDB-linkje vagy id-ja (kötelező, első argumentum) |
| `--hu-title "Cím"` | A magyar cím beírása rögtön — felülírja a TMDB-s fordítást is |
| `--stdout` | Csak kiírja a képernyőre, fájlt nem ír (előnézet) |
| `--force` | Meglévő `TRANSLATION.local.md` felülírása — a régit `.bak`-ba menti |
| `--out ÚTVONAL` | Más kimeneti fájl (alapból a munkakönyvtárban: `./TRANSLATION.local.md`) |
| `--max-cast N` | Legfeljebb N szereplő (alapból **12**), főszereplők előre |
| `--main-cast N` | Legfeljebb N szereplő kap *Main Role* címkét (alapból **4**, lásd lent) |
| `--include-guests` | A vendégszereplők (Guest Role) is kerüljenek bele |
| `--glossary ÚTVONAL` | Másik szójegyzék-fájl (alapból a munkakönyvtárban `glossary.json`) |
| `--no-glossary` | Ne vegye fel a címeket a szójegyzékbe |
| `--glossary-only` | CSAK a szójegyzéket bővítse; a `TRANSLATION.local.md`-hez ne nyúljon |

A `--out` és a `--glossary` alapértelmezése **a munkakönyvtárhoz** képest
értendő (ugyanaz a konvenció, mint a `subtr` parancsoknál) — a scriptet mindig
a sorozat projektmappájából futtasd. Ez azért fontos, mert minden sorozatnak
saját másolata van a repóból: ha az egyik mappából a másik példány scriptjét
hívod, a kimenet akkor is a **munkakönyvtárba** kerül, nem a script repójába.

### Már futó sorozat utólagos kiegészítése

A `TRANSLATION.local.md` ilyenkor kézzel hangolt (regiszter, special terms),
ezért a script `--force` nélkül leállna. A `--glossary-only` ezt kikerüli:
csak a címeket veszi fel, a fájlhoz nem nyúl.

```bash
cd "/útvonal/a/sorozathoz"
python3 addons/tmdb-init/init_local.py <tmdb-url> --hu-title "Magyar cím" --glossary-only
```

## Mit ad a TMDB, és mit nem

Egyetlen API-hívás (`/tv/{id}` + `aggregate_credits,keywords,translations`)
adja a fejlécet, a szinopszist, a kulcsszavakat (ezek kerülnek a `Tags:`
sorba) és a szereplőket. Két dolgot a script számol vagy pótol:

- **Magyar cím.** Ha a TMDB-n valaki felvitte a magyar fordítást, a script
  beírja a `Hungarian title:` sorba, és jelzi, hogy onnan jött. Ez nem mindig a
  forgalmazói cím — ellenőrizd; a `--hu-title` felülírja.
- **Main / Support / Guest Role.** A TMDB nem különbözteti meg a fő- és
  mellékszereplőt, ezért a script a **sorrendből és az epizódszámból** számolja:
  vendég, aki legfeljebb 2 epizódban (vagy az epizódok 10 %-ában) szerepel;
  fő, aki a TMDB sorrendjében az első `--main-cast` (alapból 4) között van **és**
  az epizódok legalább háromnegyedében szerepel; a többi mellékszereplő. A
  címkék ugyanazok, amikkel a regiszter-váz dolgozik, tehát a *Megszólítási
  regiszter* TODO-sorai a főszereplőkből állnak össze.

Ami hiányzik: az epizódhossz újabb sorozatoknál gyakran nincs kitöltve
(`Duration: N/A`), és a szinopszis végén nincs „Adapted from…” lábjegyzet —
a forrásmű címét ilyenkor kézzel vedd fel a szójegyzékbe.

## A címek a szójegyzékben

A `glossary.json` a fordítónak **kötelező**, ezért ez a legbiztosabb hely annak
rögzítésére, hogy egy címet nem szabad lefordítani. Enélkül a fordító
epizódonként külön dönt — a *The Quiet Harbor (2026)*-nál a négy rész
adaptációs kártyáján négyféle cím szerepelt, kettőben lefordítva.

A script három forrásból vesz fel bejegyzést (mind `special_terms`, `en` = `hu`):

| Honnan | Példa |
|---|---|
| a sorozat angol/latin betűs címe | `The Quiet Harbor` |
| a sorozat natív címe | `静港夜话` |
| a **forrásmű** címe, ha a szinopszisban van adaptációs lábjegyzet | `Jing Gang Ye Hua` |

A harmadik a TMDB-overview-ban ritka; ha a `clean_synopsis` talál ilyen
lábjegyzetet (`~~ Adapted from the web novel "…" by …`), eldobja a szövegből,
de a **címet** felveszi — az megjelenik az epizódnyitó adaptációs kártyán.

A sorozatcím bejegyzésének `context`-je külön kimondja a **címkártya-kivételt**:
enélkül a modell a sorozatcím-kártyáról is lehagyná a magyar címet, holott ott a
`TRANSLATION.md` *Címkártya* szabálya érvényes (fölül a magyar cím, alatta az
eredeti). Ha a magyar cím ismert (kapcsolóból vagy a TMDB-ről), az is bekerül a
`context`-be — de csak **új** bejegyzésnél: meglévő címbejegyzést a script soha
nem ír át, tehát a magyar címet utólag kézzel kell a `context`-be tenni.

Az **évszámot a script levágja** a címről: a fejlécben „Office Sparks (2024)”
alak áll (mint a TMDB oldalcímében), a felirat viszont sosem írja ki az évet —
évszámmal a bejegyzés soha nem illeszkedne. A `glossary.json`-ba és a
`meta.series`-be ezért „Office Sparks” kerül.

**Szereplőneveket szándékosan NEM vesz fel.** A TMDB írásmódja gyakran eltér a
feliratétól (`Lin Wan Er` vs. a feliratbeli `Lin Waner`), és egy kötelező
szójegyzékbe rossz alakot tenni rosszabb, mint nem tenni bele semmit. A neveket
a `subtr.py glossary` szedi ki magából a feliratból.

Meglévő `en` kulcsot **soha nem ír felül**, és ha nincs mit hozzáadni, a fájlhoz
sem nyúl. Íráskor `.bak` mentés készül.

Meglévő fájlt `--force` nélkül **nem** ír felül: a `TRANSLATION.local.md`
kézzel hangolt tartalom (regiszter, special terms), amit könnyű elveszíteni.

## Amit a script nem tud kitölteni

A generált fájlban `TODO:` sorok maradnak — ezeket **fordítás előtt** töltsd ki
vagy töröld:

- **Hungarian title** — ha a TMDB-n nincs magyar cím. Vagy add meg a
  `--hu-title` kapcsolóval, vagy kérd meg a Claude-ot, hogy fordítsa le (a
  címkártya-szabály miatt kell: lásd `TRANSLATION.md` → *Címkártya*).
- **Megszólítási regiszter** — ki kit tegez/magáz. A script a főszereplők
  neveiből vázat ír, de **viszonyt nem talál ki**: a `TRANSLATION.md` szerint a
  téves regiszter-sor rosszabb, mint a hiányzó, mert magabiztosan rossz formát
  kényszerít a fordítóra. Ezt nézés/olvasás alapján töltsd ki.
- **Special terms**, **Previous episodes** — ha nincs ilyen, töröld a sort.

A záró `#` kezdetű megjegyzéssorok (forrás-URL, generálás ténye) törölhetők —
a fájl teljes tartalma bekerül a fordítási promptba.

## Fájlok

```
addons/tmdb-init/
├── init_local.py     # TRANSLATION.local.md generálása (fő belépési pont)
├── tmdb_fetch.py     # az API-hívás és a mezőleképezés; önállóan nyers dumpot ír
└── README.md         # ez a leírás
```

A `tmdb_fetch.py` önmagában is futtatható, ha csak meg akarod nézni, mit ad az
API a sorozatról:

```bash
python addons/tmdb-init/tmdb_fetch.py https://www.themoviedb.org/tv/12345-sorozat-cime
```

## Ha elromlik

- `nincs TMDB_API_KEY` — a `.env` nincs a munkakönyvtárban, vagy nincs benne a sor.
- `érvénytelen TMDB_API_KEY (HTTP 401)` — elgépelt vagy visszavont kulcs.
- `nincs ilyen sorozat a TMDB-n (HTTP 404)` — rossz id, vagy film-oldal id-ját
  adtad meg sorozatként.
- `film-link (/movie/)` — a pipeline sorozatra van szabva; filmhez a
  `TRANSLATION.local.md`-t a `TRANSLATION.md` sablonja alapján kézzel töltsd ki.
