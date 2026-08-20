# MyDramaList init add-on (új sorozat indítása)

Egy **új sorozat** fordításának legelső lépése: a
[MyDramaList](https://mydramalist.com/) adatlapjáról letölti a sorozat
adatait, és megírja belőlük a `TRANSLATION.local.md` fájlt — abban a
formában, amit a `TRANSLATION.md` „Aktuális sorozat adatai” szakasza vár.

Sorozatonként egyszer kell futtatni, nem epizódonként.

## Telepítés

Ennek az add-onnak külön függősége van (a fordítási pipeline nem használja):

```bash
pip install -e ".[addons]"      # cloudscraper + beautifulsoup4
# vagy: pip install cloudscraper beautifulsoup4
```

A `cloudscraper` azért kell, mert a MyDramaList Cloudflare mögött van — sima
`requests` hívás 403-at kap.

## Használat

```bash
python addons/mdl-init/init_local.py https://mydramalist.com/70241-ni-ye-you-jin-tian
```

```
Letöltés: https://mydramalist.com/70241-ni-ye-you-jin-tian
Kész: TRANSLATION.local.md

Még kitöltendő (4 sor):
  Hungarian title: TODO: magyar cím
  - TODO: Qian Heng → Cheng Yao: MAGÁZ | TEGEZ  (viszony)
  ...
```

| Kapcsoló | Jelentés |
|---|---|
| `url` | A sorozat MyDramaList-linkje (kötelező, első argumentum) |
| `--hu-title "Cím"` | A magyar cím beírása rögtön (különben `TODO` marad) |
| `--stdout` | Csak kiírja a képernyőre, fájlt nem ír (előnézet) |
| `--force` | Meglévő `TRANSLATION.local.md` felülírása — a régit `.bak`-ba menti |
| `--out ÚTVONAL` | Más kimeneti fájl (alapból a repo gyökerében `TRANSLATION.local.md`) |
| `--max-cast N` | Legfeljebb N szereplő (alapból **12**), főszereplők előre |
| `--include-guests` | A vendégszereplők (Guest Role) is kerüljenek bele |

Meglévő fájlt `--force` nélkül **nem** ír felül: a `TRANSLATION.local.md`
kézzel hangolt tartalom (regiszter, special terms), amit könnyű elveszíteni.

## Amit a script nem tud kitölteni

A generált fájlban `TODO:` sorok maradnak — ezeket **fordítás előtt** töltsd ki
vagy töröld:

- **Hungarian title** — a magyar cím. Vagy add meg a `--hu-title` kapcsolóval,
  vagy kérd meg a Claude-ot, hogy fordítsa le (a címkártya-szabály miatt kell:
  lásd `TRANSLATION.md` → *Címkártya*).
- **Megszólítási regiszter** — ki kit tegez/magáz. A script a főszereplők
  neveiből vázat ír, de **viszonyt nem talál ki**: a `TRANSLATION.md` szerint a
  téves regiszter-sor rosszabb, mint a hiányzó, mert magabiztosan rossz formát
  kényszerít a fordítóra. Ezt nézés/olvasás alapján töltsd ki.
- **Special terms**, **Previous episodes** — ha nincs ilyen, töröld a sort.

A záró `#` kezdetű megjegyzéssorok (forrás-URL, generálás ténye) törölhetők —
a fájl teljes tartalma bekerül a fordítási promptba.

## A szinopszisról

A MyDramaList szinopszisának végén gyakran áll `(Source: Viki)` vagy
`~~ Adapted from the web novel ...` lábjegyzet. Ezeket a script eldobja: a
fordítási döntésekhez nem adnak semmit, viszont zajt visznek a promptba.
A bekezdéstördelést megtartja.

## Fájlok

```
addons/mdl-init/
├── init_local.py     # TRANSLATION.local.md generálása (fő belépési pont)
├── mdl_scrape.py     # a scraper-logika; önállóan nyers dumpot ír a képernyőre
└── README.md         # ez a leírás
```

A `mdl_scrape.py` önmagában is futtatható, ha csak meg akarod nézni az
adatlapot a régi, nyers formátumban:

```bash
python addons/mdl-init/mdl_scrape.py https://mydramalist.com/70241-ni-ye-you-jin-tian
```

## Ha elromlik

A MyDramaList HTML-je változhat; ilyenkor `N/A` értékek jelennek meg a
kimenetben. A CSS-szelektorok a `mdl_scrape.py` `extract_*` függvényeiben
vannak, egy helyen — ott javítsd. Cloudflare-blokk (403) esetén frissítsd a
`cloudscraper` csomagot.
