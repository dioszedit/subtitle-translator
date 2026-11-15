# 3. Szójegyzék és megszólítási regiszter

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Szójegyzék bővítése

A `subtr.py glossary` két módban működik — a magyar argumentum dönti el, melyikben:

```powershell
# (A) Fordítás ELŐTTI mód — CSAK az angol fájl (a magyar argumentum elhagyva).
#     Az agent a TRANSLATION.md szabályai alapján JAVASLATOT tesz a magyar fordításra,
#     te jóváhagyod, és a párhuzamos fordítás már egységes nevekkel/címekkel indul.
python subtr.py glossary "input\eng.srt"

# (B) Fordítás UTÁNI mód — angol-magyar pár. A "hu" a kész feliratban
#     ténylegesen használt fordítás (a meglévő viselkedés).
python subtr.py glossary "input\eng.srt" "output\hun.srt"

# Egyéni glossary útvonal (mindkét módban)
python subtr.py glossary "input\eng.srt" --glossary my_glossary.json

# Másik provider (alapérték: SUBTR_GLOSSARY_PROVIDER, a defaults.env-ben claude)
python subtr.py glossary "input\eng.srt" --provider codex
python subtr.py glossary "input\eng.srt" --provider grok
python subtr.py glossary "input\eng.srt" --provider antigravity
python subtr.py glossary "input\eng.srt" --provider gemini
python subtr.py glossary "input\eng.srt" --provider gemini --model gemini-3.5-flash-lite

# Csak a biztos találatokat veszi át, a bizonytalanokat kihagyja (nem kérdez)
python subtr.py glossary "input\eng.srt" --yes

# Mindegyiket végigkérdezi (a --yes/auto ág kikapcsolása)
python subtr.py glossary "input\eng.srt" --all-interactive

# Csak kiírja, mi kerülne be — a glossary.json nem módosul
python subtr.py glossary "input\eng.srt" --dry-run
```

A Gemini ág strukturált JSON sémával dolgozik, és a `subtr.py quota`-ba
könyvel, mint a többi Gemini-ágú parancs. Hosszú feliratnál a kinyerés több
darabban megy — **darabonként egy API-hívás**, ezt a napi kvótánál vedd
figyelembe (`python subtr.py quota`).

### Biztos / bizonytalan javaslatok

A javaslatok besorolást kapnak, a `subtr.py register` mintájára. A modell maga
is nyilatkozik (`confidence`), de az önbevallása nem szűr — tapasztalat szerint
mindent „biztos"-nak jelöl —, ezért egy **gépi fék** felül is bírálja: ha a
kifejezés a forrásfeliratban `MIN_OCCURRENCES`-nél (2) kevesebbszer fordul elő,
a javaslat bizonytalan lesz, akármit is állít magáról.

| kapcsoló | viselkedés |
|---|---|
| *(nincs)* | a biztosakat automatikusan átveszi, csak a bizonytalanokat kérdezi |
| `--yes` | a biztosakat átveszi, a bizonytalanokat **kihagyja**, nem kérdez |
| `--all-interactive` | mindegyiket végigkérdezi |
| `--dry-run` | nem ír fájlba, csak kilistázza, mi kerülne be |

Kérdésnél: `y` (vagy üres Enter) = elfogad, `n` = elutasít, `e` = szerkeszt,
`q` = kilép. Az automatikusan átvett sorokat a futás végén kilistázza az
előfordulásszámmal, hogy utólag is ellenőrizhesd őket.

### Amit a kinyerő lát

A prompt a fordítóéval **azonos** kontextust kap: a teljes `TRANSLATION.md` +
`TRANSLATION.local.md` (csonkítatlanul), és a teljes jóváhagyott szójegyzék a
`hu` és `context` mezőkkel együtt. Ez utóbbi a fontos: a rokon kifejezéseket
így a már eldöntött terminológiához igazítja (ha a szójegyzékben `"Sect"` =
`"Rend"`, akkor a `"Sect Elder"` sem lesz „szekta véne").

> Ebből következik, hogy a **sorozatspecifikus terminológiai döntések helye a
> `glossary.json` `context` mezője** — onnan a kinyerő is olvassa őket.

A `glossary.json`-t minden fordító- és review-provider automatikusan betölti
és átadja a modellnek, hogy a fordítások
konzisztensek maradjanak.

### Alap-szótárak (`glossaries/`)

A sorozatfüggetlen terminusok (udvari rangok, megszólítások, művelési szintek,
irodai beosztások) újrahasznosítható alap-szótárakban élnek, nyelv és műfaj
szerint (`glossaries/zh-historical.json`, `glossaries/ko-modern.json` …). A
sorozat a `glossary.json` `meta.bases` listájában választ közülük:

```json
{"meta": {"series": "…", "bases": ["zh-common", "zh-historical"]}, …}
```

- Futáskor fésülődnek össze: a sorozat saját bejegyzése **felülírja** az
  alapot (pl. ha egy sorozatban a „Marquis” nem „márki”), a később felsorolt
  alap a korábbit.
- Az alap-bejegyzések csak akkor kerülnek a promptba, ha az epizódban
  előfordulnak — a nagy alapok nem fújják fel a hívásokat.
- A `subtr.py glossary` az alap terminusait nem javasolja újra, és a sorozat
  fájljába nem írja vissza őket.
- A fordítás és a review indulásakor egy sor mutatja a használt alapokat
  (`Alap-szótár: zh-common, zh-historical (…)`).

A `subtr.py bases` parancs kezeli őket:

```powershell
python subtr.py bases list                                  # alapok + a sorozat választása
python subtr.py bases check                                 # alap ↔ sorozat ↔ kész fordítások ütközései
# terminus a sorozatból az alapba — abból a mappából, amelyik glossaries/-ába írjon:
python subtr.py bases promote "Grand Tutor" --to zh-historical --from "..\Sorozat\glossary.json" --context "太傅; a trónörökös nevelője"
```

A `check` a már lefordított részeket is összeveti a forrással: ha egy futó
sorozathoz utólag kapcsolsz alapot, megmutatja, hol írna az alap mást, mint a
kész részek (ott a sorozat glossaryjába felülírás kell). A `promote`
alapból kiveszi a bejegyzést a sorozatból (`--keep`: marad), a `context`-et
`--context`-tel általánosra cserélheted — ha az alapot megosztod (vagy a
nyilvános programba javasolod), ne maradjon benne sorozatspecifikus részlet.

Részletek és szabályok: `glossaries/README.md`.

## Megszólítási regiszter kinyerése (`subtr.py register`) — opcionális

A tegezés/magázás az angol forrásból nem derül ki közvetlenül, ezért a
`TRANSLATION.local.md` *Megszólítási regisztere* dönt róla (lásd a [*Tippek*](09-tippek.md)
fejezetet). Ezt **kézzel is megírhatod** — ez a parancs csak felkínál egy első
változatot, illetve továbbvezeti a meglévőt.

```powershell
# Egy epizód alapján (alapérték: SUBTR_REGISTER_PROVIDER, a defaults.env-ben gemini)
python subtr.py register "input\S01E01.eng.srt"

# Több rész = pontosabb. A részek közti eltérés VÁLTÁS-jelöltként jön fel,
# nem néma felülírásként — pont ezt kell a regiszter "váltás:" sorába írni.
python subtr.py register "input\S01E01.eng.srt" "input\S01E02.eng.srt"

# Másik provider
python subtr.py register "input\S01E01.eng.srt" --provider claude
python subtr.py register "input\S01E01.eng.srt" --provider codex
python subtr.py register "input\S01E01.eng.srt" --provider grok
python subtr.py register "input\S01E01.eng.srt" --provider antigravity

# Csak nézni akarod, nem írni — nem is kérdez, a bizonytalan/ütköző párok
# „DÖNTENDŐ” jelöléssel listázódnak (agentből, pipe-ból is futtatható)
python subtr.py register "input\S01E01.eng.srt" --dry-run

# KÉSZ MAGYAR feliratból (meglévő fordítás átvételekor): a tegezés/magázás
# ott nem következtetés, hanem leolvasás
python subtr.py register "Season 01\S01E01.hun.srt" "Season 01\S01E02.hun.srt" --hungarian
```

| Kapcsoló | Jelentés |
|---|---|
| `--provider gemini\|claude\|codex\|grok\|antigravity` | Modell-provider (alapérték: `SUBTR_REGISTER_PROVIDER`) |
| `--model NÉV` | Modell-felülbírálás (a `.env` `SUBTR_REGISTER_MODEL` sora is jó) |
| `--effort SZINT` | Gondolkodási szint (a `.env` `SUBTR_REGISTER_EFFORT` sora is jó) |
| `--source-lang KÓD` | A forrás nyelve, ha a fájlnév nem árulkodik (lásd [*Forrásnyelv*](04-forditas.md#forrásnyelv)) |
| `--hungarian` | A bemenet(ek) kész **magyar** felirat(ok): a formát a magyar szövegből olvassa le |
| `--local-file ÚTVONAL` | Melyik fájlban van a regiszter (default: `TRANSLATION.local.md`) |
| `--dry-run` / `--yes` / `--all-interactive` | Csak mutat / nem kérdez / mindenre kérdez |
| `--timeout MP` | Egy hívás időkorlátja |

Hogyan dönt, mit kérdez meg:

| Eset | Viselkedés |
|---|---|
| **Biztos** viszony (legalább 2 idézhető bizonyíték a feliratból) | automatikusan bemegy, a végén bizonyítékkal együtt listázva |
| **Bizonytalan** viszony | megkérdez: `y` elfogad, `m` a másik forma, `n` kihagy, `e` szerkeszt, `q` kilép |
| **Ütközik** a meglévő regiszterrel | mindig megkérdez — csendben soha nem ír felül |
| Epizódok közt **eltér** a forma | VÁLTÁS-jelölt: bizonytalanná válik, és kiírja, melyik részben mi volt |

> **Miért nem a modell magabiztosságára hagyatkozunk:** mérve a modell
> gyakorlatilag *mindent* „biztos"-nak jelöl magáról. Ezért a parancs gépi féket
> tesz elé: két idézhető bizonyíték alatt a sor bizonytalan, akármit állít
> magáról — és a bizonytalan sorok nálad kötnek ki, nem a fájlban.

A `--all-interactive` minden párnál kérdez, a `--yes` egyáltalán nem kérdez
(csak a biztos sorokat veszi át). Mentés előtt `TRANSLATION.local.md.bak`
készül, és a parancs csak a *pár-sorokat* kezeli — az `alapértelmezés`, `váltás`
és megjegyzés-sorokat érintetlenül átmenti.

> A regiszterben egy **téves sor rosszabb, mint a hiányzó**: a fordító a
> regisztert kötelezőnek veszi, hiány esetén viszont kikerülő megfogalmazást
> választ. Kétes sort inkább hagyj ki.

---

[← 2. Az első epizód — a teljes folyamat](02-elso-epizod.md) · [Tartalomjegyzék](README.md) · [4. Fordítás →](04-forditas.md)
