# Antigravity CLI (`agy`) mint ötödik provider — terv

> **Státusz: MEGVALÓSULT (2026-10-05)** — `subtr/providers/antigravity_cli.py`,
> használat: README → *Antigravity fordító* / *Antigravity review*. Az F0-ból a
> stdin-formátum, az elszigetelés és a párhuzamosság macOS-en igazolva; a
> megvalósításban a tervhez képest új: várakozásos újrapróbálás átmeneti
> szerverhibára (élesben `503 No capacity` jött). Nyitott: a Windows-oldali
> élő próba és az előfizetéses kvóta kimerülésének viselkedése.

> Dátum: 2026-10-05 · Kiindulás: az Antigravity CLI (`agy` 1.2.16), amely
> Gemini-előfizetéssel használható. Cél: `subtr.py translate|review|glossary|register
> --provider antigravity`, a Gemini-modellek előfizetésből, API-kulcs és napi
> 20-as ingyenes kvóta nélkül.

## 1. Mit tud az `agy` — kipróbálva (2026-10-05)

| Kérdés | Eredmény |
|---|---|
| Headless futás | `agy -p="<prompt>" --output-format json` — egy forduló, exit 0 |
| JSON-séma | `--json-schema '<séma>'` működik; a válasz envelope-ja `{"status":"SUCCESS","structured_output":{…},"response":"…","usage":{…}}` |
| A `structured_output` tisztasága | Tiszta, csak a séma kulcsai. A `response` szövegben viszont plusz kulcsok voltak (`toolAction`, `toolSummary`) → **csak a `structured_output`-ra szabad építeni** |
| Modellválasztás | `agy models`: `gemini-3.8/3.7/3.6-flash-{low,medium,high}`, `gemini-3.1-pro-{low,high}` (+ Claude Opus/Sonnet 5.5, GPT-OSS). Az effort a modellnév része; van külön `--effort` is |
| Sebesség | 2 soros próba: ~18 mp (gemini-3.6-flash-medium) |
| Hosszú prompt argumentumként | macOS-en ~120 KB-os `-p=` argumentum gond nélkül ment |
| Prompt stdin-ről | Sima `-p` **nem** olvas stdin-t. A `-p= --input-format stream-json --output-format stream-json` viszont igen, egy NDJSON-sorral: `{"event":"user","message":{"content":"<prompt>"}}`. Ez nem dokumentált, a bináris hibaüzeneteiből derült ki. **Kipróbálva:** 120 KB-os prompt + `--json-schema` → `{"event":"result","result":{"status":"SUCCESS","structured_output":{…}}}`. Ez a Windows-út |
| Agent-viselkedés | A teljes agent-toolkészlet be van töltve (`run_command`, `write_to_file`, böngésző, subagentek…), `permission_mode: request-review`. **Nincs** `--tools ""` / `--max-turns` kapcsoló, mint a Grok CLI-nél |
| Overhead | Egy 2 soros kérés is ~13 400 input token → az agent system promptja minden hívásban benne van |
| Buktató | `-p "<prompt>"` szóközzel hibát ad, ha utána kapcsoló jön → mindig `-p=<prompt>` alakban kell átadni |

## 2. Hová illeszkedik

A kódbázis erre kész: a `subtr/providers/__init__.py` szerint a Codex és a Grok
egy **közös headless CLI-adapter felületen** fut (`LABEL`, `MISSING_HINT`,
`find_cli()`, `RunError`, `run_json(prompt, schema, …)`), és a tasks réteg
(translate / review / glossary / register) egyetlen `codex/grok` ágon kezeli
őket. Az `agy` ugyanebbe a mintába esik: a modell JSON-t ad, a Python írja az
SRT-t vagy a riportot (nem a Claude-féle „az agent maga írja a fájlt” út).

**Javasolt név:** `--provider antigravity`, riport-utótag `_REVIEW_ANTIGRAVITY`.
A `gemini` név foglalt: az API-s utat jelenti, és mindkettő maradjon meg (az
API-s út kvótakönyvelése, `quota.py`, az előfizetésre nem érvényes).

## 3. Munkacsomagok

### F0 — Felderítés (½ nap) — ezek döntik el a kockázatot

1. **Windows-út — KÖTELEZŐ, a formátum macOS-en MEGOLDVA (2026-10-05).** A
   Windows argumentumlimitje (32 767 karakter) alatt a prompt nem fér el, ezért
   mindig stdin-es stream-json út kell (lásd 1. pont). Windowson
   még igazolni kell: `agy` telepítés, az UTF-8 stdin (ékezetek, `♪`), és az,
   hogy ott is ugyanez az envelope jön-e vissza.
2. **Tool-izoláció:** üres temp `cwd`-ben futtatva hozzányúl-e bármihez,
   olvas-e `AGENTS.md`/`GEMINI.md`-t a home-ból, ír-e a projektbe. Kell-e a
   `--sandbox` vagy a `--mode plan`.
3. **Párhuzamosság:** 3–4 egyidejű `agy -p` ütközik-e (közös állapot,
   bejelentkezés, rate limit).
4. **Előfizetéses kvóta:** egy teljes rész (≈4 blokk + review) mennyit fogyaszt,
   és mit ad vissza a CLI kvóta-túllépéskor (hibaüzenet → retry vs. leállás).
5. **Minőség:** egy 150 cue-s blokk próbafordítása 3.6-flash-medium vs.
   3.1-pro-high modellel, összevetve a meglévő Opus-kimenettel.

### F1 — Adapter: `subtr/providers/antigravity_cli.py` (½–1 nap)

- `find_agy()` → `shutil.which("agy")`; `MISSING_HINT` telepítési tanáccsal.
- `run_agy_json(prompt, schema, *, timeout, model, agy_bin)`:
  temp mappa mint `cwd`, `-p=<prompt> --output-format json --json-schema …
  --print-timeout <timeout>s`, `--model`, ha meg van adva.
- `parse_agy_response(raw)`: `status != "SUCCESS"` → hiba; a
  `structured_output`, ha van; tartalékként a `response` JSON-parse-a, a
  séma-gyökér kulcsaira szűrve. A Grok-adapter robusztus `_loads` /
  `_scan_embedded_json` logikája közös helperbe emelhető, hogy ne legyen
  harmadik másolat.
- A prompt **minden platformon stdin-en** megy, stream-json NDJSON-sorként
  (`{"event":"user","message":{"content":…}}`); a kimenetből a
  `"event":"result"` sor `result` objektuma az envelope. Egyetlen út, nincs
  platform-elágazás (a Codex-adapter kétutas megoldásával szemben).
- Regisztráció: `get_provider("antigravity")`.

### F2 — Bekötés a meglévő ágakba (½ nap)

Minden helyen a `("codex", "grok")` tuple bővül, és alapértékek kellenek:

| Fájl | Teendő |
|---|---|
| `subtr/config.py` | `PROVIDERS` + `"antigravity"` |
| `subtr/providers/__init__.py` | `get_provider`, docstring („három headless CLI-adapter”) |
| `subtr/tasks/translate.py` | default modell (javaslat: `gemini-3.6-flash-medium`), `--agents` default, retries, a CLI-ág feltétele |
| `subtr/tasks/review.py` | ugyanígy + `REPORT_SUFFIX` |
| `subtr/tasks/glossary_extract.py`, `register_extract.py` | a CLI-ág feltétele + default modell |
| `subtr/reports.py`, `subtr/tasks/apply_review.py` | `_REVIEW_ANTIGRAVITY` felismerése, keresési minták |

### F3 — Tesztek (½ nap)

- `tests/test_antigravity_cli.py` a `test_grok_cli.py` mintájára: envelope
  `structured_output`-tal, `status: ERROR`, üres kimenet, csak `response`
  szöveg, extra kulcsok (`toolAction`) kiszűrése, nem objektum gyökér.
- `test_config.py`, `test_reports.py`, `test_apply_review.py`,
  `test_providers.py`: az új név végigvezetése.
- Hálózatot nem hívunk (a meglévő tesztcsomag elve).

### F4 — Dokumentáció (½ nap)

`README.md` (provider-szakasz + összefoglaló), `steps.txt` (alternatív sorok),
`TRANSLATION.md` (a provider-felsorolás), a skillek (`.claude/`, `.codex/`,
`.grok/` × `epizod`, `review-triage`), a `proposals/README.md` táblázata.

## 4. Becslés

| | Idő |
|---|---|
| F0 felderítés | ½ nap |
| F1 adapter | ½–1 nap |
| F2 bekötés | ½ nap |
| F3 tesztek | ½ nap |
| F4 dokumentáció | ½ nap |
| **Összesen** | **≈ 2,5–3 nap**, ebből a kód kb. 250–350 sor + 150–200 sor teszt |

A Windows-támogatás kötelező (a pipeline eddig is futott Windowson). A stdin-es út formátuma
már ki van derítve, így a becslés a 2,5 nap közelébe szorul. A maradék
bizonytalanság az F0/2 (tool-izoláció), az F0/3 (párhuzamosság) és az F0/4
(előfizetéses kvóta viselkedése), valamint a Windows-oldali próba.

## 5. Kockázatok

- **Agentes CLI, nem nyers API.** Nem lehet kikapcsolni a toolokat; ha a
  modell tool-hívásba kezd, a futás lassul vagy elakad. Enyhítés: üres temp
  `cwd`, szigorú „csak JSON” utasítás, `--print-timeout`, retry.
- **Nem dokumentált stdin-formátum.** A stream-json bemenetet a bináris
  hibaüzeneteiből fejtettük vissza; egy frissítés megváltoztathatja. Kell rá
  egy célzott smoke-teszt, és értelmes hibaüzenet, ha elromlik.
- **Formátum-sodródás.** Az `agy` fiatal (1.2.x), az envelope változhat →
  a parser legyen toleráns (a Grok-adapter tanulságai), és legyen egy
  kézi smoke-teszt parancs.
- **Overhead.** ~13k token / hívás agent-prompt. Előfizetésnél nem pénz,
  de ha a kvóta tokenalapú, a kis chunkméret drága → nagyobb blokk/chunk.
- **Átfedés a `gemini` providerrel.** Ugyanazok a modellek, más hozzáférés.
  A dokumentációban egyértelművé kell tenni, mikor melyik a jobb.

## 6. Javasolt következő lépés

Először csak az F0 (fél nap): öt kérdés, mindegyikre egy próbafuttatás. Ha a
tool-izoláció és a párhuzamosság rendben van, az F1–F4 mehet egy körben.
