# 5. Review és javítás

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Review — opciók

> **Két review-kör (mérés, 2026-11):** három, Opus-szal fordított részen (összesen
> 2151 felirat; két angol és egy kínai forrású) az alapértelmezett Antigravity-review
> (`gemini-3.8-flash`, `high` effort) és a Claude Opus-review találatait egyenként a
> forráshoz mértük.
>
> | | Valódi javítás |
> |---|---|
> | Claude Opus-review | 59 |
> | Antigravity-review | 36 |
> | ebből közös | 17 |
> | a kettő együtt | 78 |
>
> Az Antigravity 51 találatából 36 volt valódi hiba, 12 ízlés kérdése, 1 téves, 1 videó
> nélkül eldönthetetlen, 1 pedig egy másik találat ismétlése — kevés a zaj. Jellemzően a szabálysértéseket (megszólítási
> regiszter, szójegyzék, névragozás) és a nyelvtani hibákat fogta meg; az Opus több
> félrefordítást és természetellenes mondatot talált. Egyik sem váltja ki a másikat:
> **a két kör együtt kb. harmadával több valódi hibát hoz, mint az Opus egyedül.**
> Ha csak egy kör fér bele, az Opus az erősebb (`SUBTR_REVIEW_PROVIDER=claude`,
> `SUBTR_REVIEW_MODEL=opus`).
>
> Kis minta, és a besorolást is modell végezte, videó nélkül — iránymutatásnak jó,
> pontos aránynak nem.

### Antigravity review (`subtr.py review` — az alapérték)
```powershell
# defaults.env: antigravity, gemini-3.8-flash, effort high → gemini-3.8-flash-high
# (előfizetésből, API-kvóta nélkül) — a modellválasztás mérése: 4. fejezet, Antigravity fordító
python subtr.py review "output\hun.srt"
python subtr.py review "output\hun.srt" --provider antigravity --model claude-opus-5-5-high   # más modell: agy models
```

A review minden providernél automatikusan megkeresi a **forrásnyelvi SRT-t**
(a `.hun.srt` névből `.eng.srt`-t, `.ger.srt`-t stb. keres az `input/`
mappában, ill. a hun fájl mellett — az összes ismert nyelvkódot végigpróbálja),
és minden szekció mellé odaadja a modellnek a forrás eredetit is
`[FORRÁS]` sorként. Így a lektor a forráshoz tudja mérni a magyart — jelentősen
kevesebb a téves találat, és a félrefordításokat is elkapja, nem csak a
stílushibákat.

A `--source` kapcsoló **nyelvfüggetlen**: bármilyen forrásnyelvi SRT-t elfogad.
(A kapcsoló régi neve `--english` volt; aliasként továbbra is működik, de az új
név a helyes.) A megtalált fájl nevéből a review a **forrásnyelvet is felismeri**,
és eszerint fogalmazza a lektor-promptot — lásd [Forrásnyelv](04-forditas.md#forrásnyelv).

A párosítás előtt **igazítás-ellenőrzés** fut (cue-számok + időbélyeg-
szúrópróba): ha a két fájl elcsúszott egymáshoz képest (pl. a magyar
`resegment --split` után újraszámozódott), a parancs figyelmeztet és kihagyja
a párosítást — elcsúszott forrássorok tömeges hamis találatot adnának.
Explicit `--source` megadással felülbírálható.

A review minden providernél a szöveges riport mellé **JSON riportot** is ír
(`_REVIEW_*.json`) — ezt dolgozza fel a `subtr.py apply`.

### Claude review (`subtr.py review --provider claude`)
```powershell
# Modell: SUBTR_CLAUDE_MODEL (defaults.env: sonnet); default chunk-size: 100
python subtr.py review "output\hun.srt" --provider claude

# Modell-választás: haiku (olcsóbb), sonnet, opus (alaposabb)
python subtr.py review "output\hun.srt" --provider claude --model haiku
python subtr.py review "output\hun.srt" --provider claude --model opus

# Egyedi chunk méret
python subtr.py review "output\hun.srt" --provider claude --chunk-size 150

# Csak egy chunk-tartomány lefuttatása, külön riportba
python subtr.py review "output\hun.srt" --provider claude --start-chunk 9 --suffix _part2
python subtr.py review "output\hun.srt" --provider claude --start-chunk 5 --end-chunk 7 --suffix _part2

# Forrásnyelvi SRT kézi megadása / kikapcsolása
python subtr.py review "output\hun.srt" --provider claude --source "input\eng.srt"
python subtr.py review "output\hun.srt" --provider claude --no-source
```

### Gemini review (`subtr.py review --provider gemini`)
```powershell
# Modell: SUBTR_GEMINI_MODEL (defaults.env: gemini-3.8-flash)
python subtr.py review "output\hun.srt" --provider gemini

# Tetszőleges modell-azonosító --model flag-gel
python subtr.py review "output\hun.srt" --model gemini-3.8-flash
python subtr.py review "output\hun.srt" --model gemini-3.5-flash-lite   # olcsó, bő napi kvóta
# Modell-lista: https://ai.google.dev/gemini-api/docs/models

# Csak egy chunk-tartomány lefuttatása, külön riportba
python subtr.py review "output\hun.srt" --start-chunk 9 --suffix _part2
python subtr.py review "output\hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

# Forrásnyelvi SRT kézi megadása / kikapcsolása
python subtr.py review "output\hun.srt" --source "input\eng.srt"
python subtr.py review "output\hun.srt" --no-source
```

A Gemini-ág **strukturált JSON kimenetet** ad (Pydantic séma), ami stabilabb
mint a szabad szöveg, és automatikusan retry-ol rate limit (429) vagy 5xx hiba esetén.
A forrásnyelvi SRT párosítása itt is működik (lásd fent a Claude review-nál).

### Grok review (`subtr.py review --provider grok`)
```powershell
# Modell: SUBTR_GROK_MODEL (defaults.env: grok-4.5)
python subtr.py review "output\hun.srt" --provider grok
python subtr.py review "output\hun.srt" --provider grok --model grok-4.6
```

### Codex review (`subtr.py review --provider codex`)
```powershell
# Modell: SUBTR_CODEX_MODEL (üres: a Codex CLI saját alapértéke)
python subtr.py review "output\hun.srt" --provider codex
```

### Megszakadt vagy hiányos review

A review chunkonként lemezre menti a kész találatokat a riport mellé, egy
`…_REVIEW_<PROVIDER>.partial` fájlba — egy megszakadt futás nem vész el.

```powershell
# Folytatás: ugyanaz a parancs újra — a kész chunkok kimaradnak
python subtr.py review "output\hun.srt"

# Riport a kész részből, a provider hívása nélkül (pl. Ctrl+C után)
python subtr.py review "output\hun.srt" --from-partial

# A részeredmény eldobása, elölről
python subtr.py review "output\hun.srt" --no-resume
```

| Helyzet | Mi történik |
|---|---|
| Egy chunk hibára fut | A riport elkészül a többiből, a `.partial` megmarad; a következő futás csak a hiányzókat pótolja (előbb a még meg sem próbáltakat, a korábban hibásakat a végén), és a teljes riportot írja felül |
| Elfogy a provider kerete, vagy két először próbált chunk egymás után hibázik | A futás megáll (nem próbálja végig a maradékot), és **hiányos riportot** ír a kész részből. A korábban is hibás, újrapróbált chunkok a sor végére kerülnek (a legkevesebbszer elbukottal kezdve); köztük csak az állítja meg a futást, ha kettő egymás után ugyanazzal a hibával bukik el |
| Ctrl+C / lefagyás | Riport nem készül, csak a `.partial` marad — folytatható, vagy `--from-partial` |
| A felirat egy része közben megváltozott (pl. átvezetett javítások) | Csak az érintett chunkok mennek újra, a többi kész chunk eredménye megmarad |
| A modell, az effort, a chunkméret vagy a lektor-utasítás (szójegyzék, `TRANSLATION.md`) megváltozott | A részeredmény nem ehhez a futáshoz tartozik: a parancs kiírja az okot, `….partial.stale` néven félreteszi, és elölről kezd. Visszahozható: a beállítás visszaállítása után nevezd vissza `.partial`-ra |

A hiányos riport **triage-olható**: a `.json`-ban a `missing_chunks` mező jelzi a
nem lektorált chunkokat, a `subtr.py apply` és a `/review-triage` ezt kiírja.
Közben a teljes részt egy másik providerrel is lektoráltathatod — a riportok
függetlenek. Ha a hiányos riport javításait már átvezetted, ugyanaz a parancs
akkor is folytat: a hiányzó chunkokat pótolja, a javítással érintetteket újra
lektorálja, a változatlanok korábbi találatait megtartja (ezek a riportban újra
megjelennek — a triage-ban már elbírált tételek).

A keret kimerülését a provider-adapter jelzi, a provider saját hibaüzenete
alapján (a modell válaszának szövegéből soha). A Gemini API-nál csak a napi
limit számít — a percenkénti 429 egyetlen hibás chunk —, és az átmeneti
kapacitáshiány („No capacity", 503) sehol sem keret-kimerülés. Ahol a limit-üzenet
nem ismerhető fel, a „két egymást követő hiba" szabály állítja meg a futást. Egy chunk
korábbi hibaüzenetei — köztük a nem értelmezhető modellválasz megőrzött nyers
szövege — a riportban az újabb futások után is megmaradnak. Rész-tartomány
(`--start-chunk` / `--end-chunk`) futása ugyanígy folytatható, `--suffix` nélkül is.

Rész-tartomány riportja (`--start-chunk` / `--end-chunk`) a `.json`-ban
`chunk_range` mezővel jelzi, mely chunkokat fedi — önmagában nem teljes review.

A `.partial` fájlt sem az `apply`, sem a triage nem olvassa; sikeres futás végén
törlődik, a félretett `.partial.stale`-lel együtt. Ha a részeredmény nem
olvasható, nem írható vagy nem törölhető (megtelt lemez, zárolt fájl), a review
figyelmeztet és végigfut, legfeljebb nem lesz folytatható. A `.partial` és a
`.partial.stale` feliratszöveget tartalmaz, ezért a commit előtti szűrő tiltja.

### Kész, külső fordítás lektorálása

Ha nem a pipeline fordított, hanem egy máshonnan kapott magyar feliratot
lektorálsz, annak a feliratai gyakran **össze vannak vonva**: a magyarban 450
felirat van, az angolban 750. A review a magyar és a forrás feliratait
sorszám szerint párosítja, ezért ilyenkor rossz forrássort látna. Előbb
igazítsd a forrást a magyar sorszámaihoz, időzítés alapján:

```bash
python addons/align-source/align_source.py "output/Sorozat - S01E03.hun.srt"
python subtr.py review "output/Sorozat - S01E03.hun.srt" --source "input/aligned/Sorozat - S01E03.eng.srt"
```

A részletek az add-on leírásában vannak: [`addons/align-source`](../addons/align-source/README.md).
Ha a magyar fájlba utólag feliratot szúrsz be, futtasd újra az igazítást.

### Review-javaslatok alkalmazása (`subtr.py apply`)
```powershell
# A hun.srt melletti összes riport összefésülése + interaktív alkalmazás
python subtr.py apply "output\hun.srt"

# Csak megadott riportok, ill. csak listázás módosítás nélkül
python subtr.py apply "output\hun.srt" "output\hun_REVIEW_GEMINI.json"
python subtr.py apply "output\hun.srt" --dry-run
```

A parancs a Claude-, Gemini-, Codex-, Grok- és Antigravity-riportokat szekciószám szerint összefésüli, az
azonos javaslatokat deduplikálja (jelölve, hogy mindkét lektor egyetért), az
eltérőeket variánsként kínálja fel. Találatonként kérdez: `y` = alkalmaz,
`1..9` = adott variáns, `e` = kézi szerkesztés, `n` = kihagy, `q` = kilépés
mentéssel. Az első módosítás előtt `.bak` mentést készít az eredetiről.

### Nem interaktív alkalmazás (`subtr.py apply-auto`)

A `subtr.py apply` minden találatnál kérdez — sok részt átnézve ez több száz
konzol-kérdés. Ha a döntéseket **előre** meghozod (magad, vagy egy agenttel,
aki a javaslatokat az angol eredetihez méri), ez a testvér-parancs kérdés nélkül
vezeti át őket:

```powershell
python subtr.py apply-auto "output\hun.srt" decisions.json
python subtr.py apply-auto "output\hun.srt" decisions.json --dry-run
```

A döntés-fájl neve szabad (a `/review-triage` skill pl. `<stem>_decisions.json`
néven, a hun.srt mellé írja) — a tartalma egy egyszerű lista: szekciószám és a
végleges szöveg:

```json
[
  {"sorszam": 12, "eredeti": "A régi szöveg", "javaslat": "Az új magyar szöveg"},
  {"sorszam": 40, "javaslat": "Első sor\nMásodik sor"}
]
```

A sorszám + időbélyeg itt is érintetlen marad, az első íráskor `.bak` mentés
készül, a fájlban nem létező szekciókat kihagyja és jelzi. Ami már egyezik a
javaslattal, azt nem írja újra — a parancs idempotens.

> **Az `eredeti` mező opcionális, de ajánlott.** Ha megadod, a parancs
> ellenőrzi, hogy tényleg az áll-e a fájlban — vagyis hogy a döntés-fájl
> ehhez a fájl-állapothoz készült-e —, és eltérés esetén **kihagyja** az adott
> bejegyzést. Erre azért van szükség, mert a sorszámok nem örökérvényűek: a
> `subtr.py resegment reflow --split` újraszámozza a cue-kat, és onnantól egy korábban
> készült döntés-fájl más szekciókra mutat. Ha sok bejegyzés tér el egyszerre,
> a parancs külön jelzi, hogy valószínűleg ez történt. Az összehasonlítás
> whitespace-független, és a `--ignore-drift` felülbírálja.
>
> A review riportok (`_REVIEW_*.json`) amúgy is tartalmaznak `eredeti` mezőt,
> úgyhogy a döntés-fájl összeállításakor érdemes átmásolni.

> **Miért éri meg előre szűrni:** a review-modellek javaslatainak jelentős
> része téves. 10 részen mérve a `gemini-3.1-flash-lite` találatainak ~13%-a
> szó szerint azonos volt az eredetivel (no-op), és ezen felül is sokat el kell
> dobni (nem létező szóalakok, hamis tegezés/magázás-riasztások). Érdemes tehát
> a javaslatokat egyesével az **angol eredetihez** mérni, és csak a jóváhagyott
> (esetleg átírt) szöveget beírni a döntés-fájlba.
>
> Ezt a szűrési folyamatot a **`/review-triage`** skill automatizálja Claude
> Code-ban (lásd: [*Workflow-skillek*](02-elso-epizod.md#workflow-skillek)).

---

[← 4. Fordítás](04-forditas.md) · [Tartalomjegyzék](README.md) · [6. Provider, modell és effort →](06-providerek.md)
