# 2. Az első epizód — a teljes folyamat

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Használat (PowerShell)

### Teljes folyamat (egy epizód)

```powershell
# 1. Szétvágás blokkokra (alapból 150 szekciónként)
python subtr.py split "input\Sorozat - S01E01.eng.srt"
# Újra-splitnél (pl. más --block-size) --clean törli a régi blokkokat —
# enélkül a parancs leáll, hogy a két generáció ne keveredjen a merge-nél
# .vtt bemenetre (vagy WEBVTT fejlécre) is leáll: előbb addons\vtt2srt

# 1.5 (ajánlott) Szójegyzék MÉG a fordítás előtt: nevek, címek, megszólítások a
#     forrásfeliratból — így a párhuzamos blokkok egységes nevekkel indulnak.
#     A biztosakat átveszi, a bizonytalanokat megkérdezi. Részletek: 3. fejezet
python subtr.py glossary "input\Sorozat - S01E01.eng.srt"

# 1.6 (ajánlott) Megszólítási regiszter: ki kit tegez / magáz — a
#     TRANSLATION.local.md-be kerül, minden blokk promptjába. Minden epizód előtt
#     nézd át (új szereplő, tegeződésre váltás). Részletek: 3. fejezet
python subtr.py register "input\Sorozat - S01E01.eng.srt"

# 2. Fordítás — a --provider választja ki a fordítót (nélküle: SUBTR_TRANSLATE_PROVIDER)
python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider claude --agents 3
# vagy Gemini API-val (olcsóbb alternatíva, ugyanazokat a blokkokat dolgozza fel)
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider gemini --agents 3
# vagy Codex CLI-vel — első futáskor egy blokkot, egy agenttel ellenőrizz
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider codex --block 1 --agents 1
# vagy Grok CLI-vel
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider grok --block 1 --agents 1
# vagy Antigravity CLI-vel (Gemini előfizetésből)
# python subtr.py translate "blocks\Sorozat - S01E01.eng" --provider antigravity --agents 3

# 3. Összefűzés egy fájlba
python subtr.py merge "blocks\Sorozat - S01E01.eng" "output\Sorozat - S01E01.hun.srt"

# 4. Strukturális ellenőrzés (sorszámok, időbélyegek, szekciószámok)
python subtr.py verify "input\Sorozat - S01E01.eng.srt" "output\Sorozat - S01E01.hun.srt"

# 5. Stilisztikai review — alapból Antigravity (SUBTR_REVIEW_PROVIDER), --provider-rel válthatsz
python subtr.py review "output\Sorozat - S01E01.hun.srt"
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_ANTIGRAVITY.txt + .json

# vagy Gemini API-val
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider gemini
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_GEMINI.txt + .json

# vagy Claude Code-dal
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider claude
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_CLAUDE.txt + .json

# vagy Codex CLI-vel
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider codex
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_CODEX.txt + .json

# vagy Grok CLI-vel
python subtr.py review "output\Sorozat - S01E01.hun.srt" --provider grok
# Kimenet: output\Sorozat - S01E01.hun_REVIEW_GROK.txt + .json

# 5b. Review-javaslatok alkalmazása (a riportokat összefésüli, deduplikálja,
#     találatonként y/n/e/q kérdéssel viszi át a fájlba, .bak mentéssel)
python subtr.py apply "output\Sorozat - S01E01.hun.srt"
# vagy 5c. Ugyanez kérdés nélkül, előre elkészített döntés-fájlból
# python subtr.py apply-auto "output\Sorozat - S01E01.hun.srt" decisions.json

# 6. (ajánlott) Szójegyzék bővítése a KÉSZ fordításból — a ténylegesen használt
#    magyar alakokat tanulja meg a következő epizódokhoz. Részletek: 3. fejezet
python subtr.py glossary "input\Sorozat - S01E01.eng.srt" "output\Sorozat - S01E01.hun.srt"

# 6/b. CSAK SDH-forrásnál (beszélőcímkék, hangjegyzetek): a lefordított jegyzetek
#      törlése egy külön .hun.clean.srt-be — részletek: addons\srt-preclean\README.md
# python addons\srt-preclean\postclean_srt.py "output\Sorozat - S01E01.hun.srt"

# 7. Szegmentálás — sorhossz-riport + automatikus tördelés (a review-javítások után);
#    a többi utómunka (Subtitle Edit, kézi lektorálás, MKV): 8. fejezet
python subtr.py resegment report "output\Sorozat - S01E01.hun.srt"
python subtr.py resegment reflow "output\Sorozat - S01E01.hun.srt" -o "output\Sorozat - S01E01.hun.reflow.srt"
```

A review parancs **öt providere** — Antigravity (alapérték), Gemini, Claude, Codex, Grok —
**független** egymástól: futtathatod csak az egyiket vagy többet, `--provider`-rel
váltva. A találatokat a `subtr.py apply` fésüli össze és viszi át
interaktívan; kézzel is javíthatsz a riportok alapján.

**Ajánlott: két review-kör.** Előbb az alapértelmezett Antigravity-review, utána
egy Claude-kör Opus modellel (`--provider claude --model opus`), és a két riport
találatait együtt nézd át — a lektorok más-más hibatípust vesznek észre. A mérést
és a számokat lásd a [*Review — opciók*](05-review.md#review--opciók) szakasz elején.

## Kontextus-átadás — fontos!

Minden fordító- és review-ág átadja a **TRANSLATION.md**-t és a
**glossary.json**-t system promptként a modellnek:

| Provider / feladat | Mechanizmus |
|--------|-------------|
| `translate --provider claude` | `--append-system-prompt-file` (Claude Code) |
| `translate --provider gemini` | `system_instruction` (Gemini API) |
| `translate --provider codex` | Codex `exec --output-schema` |
| `translate --provider grok` | Grok CLI `--json-schema` |
| `translate --provider antigravity` | Antigravity CLI `--json-schema` (prompt a stdin-en) |
| `review --provider claude` | `--append-system-prompt-file` (Claude Code) |
| `review --provider gemini` | `system_instruction` (Gemini API) |
| `review --provider codex` | Codex `exec --output-schema` |
| `review --provider grok` | Grok CLI `--json-schema` |
| `review --provider antigravity` | Antigravity CLI `--json-schema` (prompt a stdin-en) |

**Következmény:** ha bővíted a TRANSLATION.md-t (új szabály) vagy a glossary-t,
a változás a következő futáskor automatikusan érvényesül — a translate-nél
és a review-nál is. Külön beállítás nem kell.

## Workflow-skillek

A program három projekt-szintű skillt tartalmaz (`.claude/skills/`) — ezek Claude
Code-ban `/névvel` hívható, kódolt munkafolyamatok. Letöltés után azonnal működnek,
külön telepítés nélkül:

| Skill | Mit csinál |
|---|---|
| `/review-triage <hun.srt>` | A `_REVIEW_*.json` riportok minden találatát a forráshoz méri, kiszűri a no-opokat és hamis riasztásokat, `decisions.json`-t épít és a `subtr.py apply-auto`-val átvezeti a jóváhagyottakat |
| `/epizod <név>` | A fájlokból felismeri, hol tart egy epizód a pipeline-ban, és onnan viszi tovább a lépéseket a `steps.txt` szerint — a csapdákkal együtt (`--clean`, `.clean.srt` elleni verify, resegment-sorrend) |
| `/hardsub <hun.srt>` | Ha a videóban beégetett idegen felirat van: képkockákon megméri a helyét, a `.env`-be állítja (`HARDSUB_*`), az `addons/hardsub-cover`-rel dobozos ASS-t készít, próbaképeken ellenőrzi, majd alapértelmezett sávként az MKV-ba teszi |

A skillek csak **munkafolyamatot** kódolnak — a fordítási szabályok forrása
továbbra is a `TRANSLATION.md` és a `glossary.json`. Ugyanez a három skill
négy helyen él: `.claude/skills/`, `.codex/skills/`, `.grok/skills/` és
`.agents/skills/` (ez utóbbit az Antigravity CLI olvassa; `epizod`,
`review-triage`, `hardsub`). Ha az egyiket módosítod, a többit is igazítsd hozzá.

---

[← 1. Telepítés és mappaszerkezet](01-telepites.md) · [Tartalomjegyzék](README.md) · [3. Szójegyzék és megszólítási regiszter →](03-szojegyzek.md)
