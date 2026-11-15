# 6. Provider, modell és effort

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Provider, modell és effort .env-ből

A négy LLM-es parancs — `translate`, `review`, `glossary`, `register` — beállítása
funkciónként egy hármas. A kódban nincs beégetett provider vagy modellnév: minden
alapérték a `subtr/defaults.env` fájlban van, a `.env` azt írja felül, a parancssori
kapcsoló pedig mindkettőt.

| Env-kulcs | Hatás |
|---|---|
| `SUBTR_<FUNKCIÓ>_PROVIDER` | a funkció providere: `gemini`, `claude`, `codex`, `grok` vagy `antigravity` |
| `SUBTR_<FUNKCIÓ>_MODEL` | a modell ehhez a providerhez |
| `SUBTR_<FUNKCIÓ>_EFFORT` | gondolkodási szint: `low`, `medium`, `high`, `xhigh`, `max` |
| `SUBTR_<PROVIDER>_MODEL`, `SUBTR_<PROVIDER>_EFFORT` | tartalék arra az esetre, ha a funkciót **nem** a beállított providerével futtatod (pl. `--provider grok`) |

A `<FUNKCIÓ>` a `TRANSLATE`, `REVIEW`, `GLOSSARY` vagy `REGISTER`.

**Alapértékek** (`subtr/defaults.env`):

| Funkció | Provider | Modell | Effort |
|---|---|---|---|
| `translate` | claude | sonnet | – |
| `review` | antigravity | gemini-3.8-flash | high |
| `glossary` | claude | a CLI sajátja | – |
| `register` | gemini | gemini-3.8-flash | – |

**Feloldás** (az erősebb nyer):

- provider: `--provider` > `SUBTR_<FUNKCIÓ>_PROVIDER`
- modell: `--model` > `SUBTR_<FUNKCIÓ>_MODEL` > `SUBTR_<PROVIDER>_MODEL`
- effort: `--effort` > `SUBTR_<FUNKCIÓ>_EFFORT` > `SUBTR_<PROVIDER>_EFFORT`

Előbb a `.env` sorai döntenek ebben a sorrendben, és csak ha ott nincs találat, akkor
ugyanígy a `defaults.env` — a `.env` bármely sora (a provider-szintű is) erősebb az
alapértékeknél. Néhány szabály:

- **A funkció modell- és effort-sora a funkció provider-sorához tartozik.** Ha más
  providerrel futtatsz (`--provider`, vagy a `.env`-ben csak a providert írod át), a
  provider-szintű sorok lépnek be — a `sonnet` nem megy át a Groknak.
- **Az üres érték is beállítás.** Üres modellnél a provider CLI-je a saját
  alapértelmezésével fut (a Gemini API-nál a modell kötelező); üres effortnál nem megy
  át szint. Így kapcsolható ki például a review `high` effortja: `SUBTR_REVIEW_EFFORT=`.
- **Az effort** a Claude-ágon a CLI `--effort` kapcsolója, az Antigravity-ágon a
  modellnév utótagja (`gemini-3.8-flash` + `high` → `gemini-3.8-flash-high`; itt csak
  `low` / `medium` / `high`). A Gemini API, a Codex és a Grok ágán nincs hatása: a
  parancs figyelmeztet, és kihagyja.
- **Nincs néma visszaesés.** Ismeretlen provider, elgépelt effort vagy a Gemini-ágon
  hiányzó modell hibával megállítja a parancsot.

Hogy egy mappából éppen mi futna, és melyik érték honnan jön:

```powershell
python subtr.py config                    # a négy funkció hármasa, forrással
python subtr.py config --provider grok    # mi lenne --provider grok mellett
```

**Példa `.env`:**
```bash
# Fordítás: Claude Opus, közepes gondolkodással
SUBTR_TRANSLATE_PROVIDER=claude
SUBTR_TRANSLATE_MODEL=opus
SUBTR_TRANSLATE_EFFORT=medium

# Review: Gemini API az Antigravity helyett
SUBTR_REVIEW_PROVIDER=gemini
SUBTR_REVIEW_MODEL=gemini-3.8-flash

# Ha néha Grokkal futtatsz valamit (--provider grok)
SUBTR_GROK_MODEL=grok-4.6
```

**Régi változónevek.** A korábbi `SUBTR_DEFAULT_PROVIDER`,
`SUBTR_<PROVIDER>_MODEL_<FUNKCIÓ>` és `SUBTR_<PROVIDER>_EFFORT_<FUNKCIÓ>` megszűnt: ha a
`.env`-ben ilyen sor van, a parancs megáll, és megnevezi az új nevet.

| Régi | Új |
|---|---|
| `SUBTR_DEFAULT_PROVIDER=x` | funkciónként `SUBTR_<FUNKCIÓ>_PROVIDER=x` |
| `SUBTR_CLAUDE_MODEL_TRANSLATE=opus` | `SUBTR_TRANSLATE_PROVIDER=claude` + `SUBTR_TRANSLATE_MODEL=opus` |
| `SUBTR_CLAUDE_EFFORT_GLOSSARY=low` | `SUBTR_GLOSSARY_PROVIDER=claude` + `SUBTR_GLOSSARY_EFFORT=low` |
| `SUBTR_<PROVIDER>_MODEL`, `SUBTR_<PROVIDER>_EFFORT` | megmaradt, de már csak provider-váltáskor érvényes |

### Claude — ajánlott modell és effort

A Claude-ág a Claude Code CLI **aliasait** adja át (`haiku`, `sonnet`, `opus`),
és a CLI ezeket mindig a legfrissebb modellre oldja fel — 2026 szeptemberében az
`opus` a Claude Opus 5.5-öt, a `sonnet` a Claude Sonnet 5-öt jelenti. A
`defaults.env` fordító modellje a `sonnet`; ezen szándékosan nem változtatunk, mert az Opus
tokenenként kétszer annyiba kerül (API-áron 4 / 20 USD vs. 2 / 10 USD millió
bemeneti / kimeneti tokenenként), előfizetésnél pedig gyorsabban fogyasztja a
keretet.

**Ajánlás: az Opus fordítson, minden más maradjon olcsóbb.** A fordításnál
számít a legtöbbet a minőség (regiszter, nevek, hosszú kontextus), és egy jobb
első fordítás kevesebb review-kört és javítást jelent. A glossary és a register
rövid, egyszeri hívás.

A `SUBTR_GLOSSARY_MODEL` sort érdemes kitölteni: a `defaults.env`-ben üres, így
beállítás nélkül a Claude Code **saját mentett alapértelmezése** fut, ami könnyen
éppen a legdrágább modell.

A második költségkar a **gondolkodási szint** (`--effort`). Ha nincs megadva, a
Claude Code a saját alapértelmezésével fut, ami modellenként más, és magasabb
lehet, mint amire egy jól specifikált fordítási feladatnak szüksége van — a
minőséget itt a `TRANSLATION.md`, a regiszter és a szójegyzék adja, nem a
modell hosszú töprengése.

```bash
SUBTR_TRANSLATE_PROVIDER=claude
SUBTR_TRANSLATE_MODEL=opus           # a fordítás: Opus 5.5
SUBTR_TRANSLATE_EFFORT=medium        # közepes gondolkodás

SUBTR_GLOSSARY_PROVIDER=claude
SUBTR_GLOSSARY_MODEL=sonnet          # a szójegyzék-javaslat: Sonnet 5 …
SUBTR_GLOSSARY_EFFORT=low            # … alacsony szinten

SUBTR_CLAUDE_MODEL=sonnet            # ha a review-t / registert --provider claude-dal futtatod
SUBTR_CLAUDE_EFFORT=medium
```

Ez kiindulópont, nem mért optimum. Érdemes egy epizódon kipróbálni: ha a
review sok regiszter- vagy név-hibát talál, a fordításnál emeld `high`-ra
(`SUBTR_TRANSLATE_EFFORT=high`); ha tiszta, maradhat `medium`, vagy
kipróbálható a `low` is. A `--agents` szám a költséget nem, csak a
futásidőt és a párhuzamos terhelést befolyásolja.

---

[← 5. Review és javítás](05-review.md) · [Tartalomjegyzék](README.md) · [7. Gemini: modellek, limitek, kvóta →](07-gemini-kvota.md)
