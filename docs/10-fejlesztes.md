# 10. Fejlesztés és háttér

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Fejlesztés

Ez a szakasz annak szól, aki **a kódhoz nyúl** — javít, bővít, forkol. Sima
használathoz (fordítás, review) egyik beállítás sem kell, az [1. Telepítés](01-telepites.md) fejezet elég.

### Fejlesztői beállítás egy új clone-ban

```bash
pip install -e .                          # a csomag és a három futásidejű függőség
git config core.hooksPath .githooks       # a commit előtti szűrő bekapcsolása (lent)
pytest                                    # a tests/ mappa, ~450 teszt, néhány másodperc
```

A tesztek nem hívnak külső API-t vagy CLI-t — a providereket és a TMDB-hívást
mockolják, API-kulcs nélkül is futnak. Az `addons/` scriptjeinek nincs külső
függősége.

### Commit előtti szűrő — jogvédett tartalom és titok

A repo nyilvános, és a fejlesztés közben kéznél vannak valódi feliratok,
sorozat-adatok és API-kulcsok — ezek könnyen belecsúsznak egy tesztfixture-be
vagy egy doksi-példába. Ezért van egy pre-commit hook, ami a **stage-elt**
fájlokat átnézi, mielőtt a commit létrejön (`scripts/check_copyright.py`). A
fenti `git config core.hooksPath .githooks` kapcsolja be; a hook a repóval
együtt verziózott, tehát egy fork is örökli.

Mit fog meg — csak determinisztikus szabályokkal, LLM nélkül:

- **tiltott útvonal**: `.env`, `TRANSLATION.local.md`, az `input/` `output/`
  `blocks/` tartalma, felirat- és médiafájlok, review-riportok — akkor is, ha
  `git add -f`-fel kerültek be;
- **titok**: API-kulcs minták és kitöltött `*_API_KEY=` sorok (a placeholder
  rendben van);
- **felirat-tömeg**: túl sok SRT-időbélyeg vagy ♪-sor egy fájlban — egy-két cue
  tesztfixture-nek jó, egy teljes blokk nem;
- **sorozat-terminus**: az aktuális sorozat címei és szereplői **automatikusan** a
  `TRANSLATION.local.md`-ből és a `glossary.json`-ból, plusz a gitignore-olt
  `.copyright-blocklist` sorai (korábbi sorozatok; sablon:
  `.copyright-blocklist.example`). Egész szóra, kis-/nagybetű nélkül, fájlnévben is.

```bash
python3 scripts/check_copyright.py --terms   # mit keres most
python3 scripts/check_copyright.py --all     # az egész verziózott fa átvizsgálása
SKIP_COPYRIGHT_CHECK=1 git commit …          # hamis riasztásnál egyszeri kihagyás
```

Amit **nem** tud: a felirat mondatait mint mondatokat nem ismeri fel. Ha egy
valódi feliratsort másolsz egy tesztbe cím és szereplőnév nélkül, azt csak te
veszed észre — ezért a fixture-ök kitalált szövegek.

## Hogyan készült — AI-asszisztált fejlesztés

**Ez a projekt kódjának túlnyomó része AI-asszisztensekkel készült**, emberi
irányítás, tesztelés és jóváhagyás mellett. Ezt fontosnak tartom kiírni, mert
befolyásolja, hogyan érdemes a kódhoz viszonyulni.

- **[Claude Code](https://claude.com/claude-code)** — a fejlesztés zöme: a
  `subtr/` csomag, a CLI, a promptok, a tesztek és ez a dokumentáció is.
- **Codex CLI** — főleg a Codex-providerhez (`subtr/providers/codex_cli.py`)
  kapcsolódó részek, illetve egy-egy második vélemény a review-körökben.
- **Grok Build** (a Grok CLI agentikus fejlesztői módja) — a Grok-provider
  (`subtr/providers/grok_cli.py`), a beépítése a négy feladatba és a
  `.grok/skills/` munkafolyamat-skillek. A provider deep review-ja és az abból
  következő javítások már Claude Code-dal készültek.

Az AI-val írt commitok `Co-Authored-By` sorral vannak megjelölve, így a
`git log`-ból utólag is látszik, mi hogyan készült.

Amit ez a gyakorlatban jelent:

- **A kód működik, de nem „iparilag auditált".** Van teszt-lefedettség
  (`pytest`), a pipeline több sorozaton végigfutott élesben — de ez egy hobbi
  projekt, nem egy review-boardon átment termék. Ha éles környezetben
  használnád, olvasd át, amit futtatsz.
- **Az API-hívások pénzbe kerülnek.** A fordítás és a review a te kulcsoddal,
  a te kvótádból fut. A `subtr.py quota` parancs segít nyomon követni.
- **A fordítás maga is LLM-kimenet**, tehát hibázhat. Az [*Utómunka*](08-utomunka.md) és a
  [*Tippek*](09-tippek.md) fejezet pont arról szólnak, hogy ezt hogyan kapd el — a kézi
  lektorálási kör nem opcionális dísz, hanem a folyamat része.

---

[← 9. Tippek](09-tippek.md) · [Tartalomjegyzék](README.md)
