# Translategemma alapú fordítási megoldás — jegyzetek

> Beszélgetés összefoglalója egy lehetséges alternatív megoldásról:
> Mac mini-n futó `translategemma:12b` (Ollama) használata Claude helyett/mellett.
> Dátum: 2026-04-20

---

## 1. Glossary átadása translategemma-nak

Az Ollama egy nyers LLM API — nincs CLAUDE.md-szerű automatikus kontextus.
A glossary-t **be kell szerkeszteni a promptba**. Három lehetőség:

### 1.a Modelfile (állandó system prompt, "leginkább claude-code-szerű")

```
FROM translategemma:12b
SYSTEM """Fordíts angolról magyarra. Szójegyzék:
- Your Highness = Fenséged
- Yi Gang = Yi Gang (ne fordítsd)
...
Szabályok: karakterneveket ne fordítsd, kötőjeles párbeszédet tartsd meg."""
PARAMETER temperature 0.3
```

Létrehozás: `ollama create sorozat-ford -f Modelfile`
→ minden híváskor beégetve jön a glossary.

### 1.b Per-request system prompt (API-n át)

```bash
curl http://mac-mini:11434/api/generate -d '{
  "model": "translategemma:12b",
  "system": "Glossary: ...",
  "prompt": "<SRT blokk>",
  "options": {"temperature": 0.3, "num_ctx": 8192}
}'
```

### 1.c Dinamikus injektálás (AJÁNLOTT SRT-hez)

Python wrapper a blokk fordítása előtt:
- kinyeri a blokkban előforduló glossary-kulcsokat (szűrt, releváns részhalmaz)
- csak azokat injektálja a system promptba → rövidebb kontextus, pontosabb találat

---

## 2. Translategemma korlátai

- **Gemma-alapú, nem erősen instruction-tuned** — komplex szabályrendszert
  (pl. "megházasodni vs. férjhez menni nemfüggő logika") rosszul tartja be.
  Rövid, deklaratív szabályok működnek; elágazó logika nem igazán.
- **Context window**: gemma2 alapon 8k, `num_ctx` paraméterrel állítható.
  Egész blokkot (150 sor SRT) elbír.
- **Formátum-megtartás (sorszám/időbélyeg)**: NEM garantált. Érdemes a szöveget
  *csak* átadni, a sorszám+időbélyeget Pythonból visszailleszteni.
- **Temperature 0.2–0.4** a konzisztenciához.
- **KÖTELEZŐ prompt-formátum** (hivatalos):
  `"You are a professional {SRC} ({CODE}) to {TGT} ({CODE}) translator..."`
  + **két üres sor** a fordítandó szöveg előtt. Ha nem tartod be, romlik a minőség.

---

## 3. Javasolt pipeline architektúra

```
Python script:
  1. SRT parse → csak szövegsorok
  2. releváns glossary-részhalmaz kinyerése
  3. Ollama API hívás (system=szabályok+glossary, prompt=szövegek)
  4. válasz vissza-merge-elése sorszám+időbélyeggel
```

Előny: a strukturális helyesség (sorszám, időzítés, szekciószám) **determinisztikus** marad,
a modell csak a fordítást csinálja.

---

## 4. Több szekción átívelő mondatok — a fő nehézség

### Stratégia 1: szekciónként küldés (NAIV — rossz)

Modell nem látja a kontextust → félrefordít; magyar szórend nem fér bele.

### Stratégia 2: teljes blokk egyben, számozott markerekkel (JÓ ALAP)

```
Fordítsd le. Tartsd meg a [N] jelöléseket, a magyar mondat
tördelése kövesse az angolt nagyjából arányosan:

[001] I wanted to tell you
[002] that I love you,
[003] but I was afraid.
```

Válasz:
```
[001] El akartam mondani,
[002] hogy szeretlek,
[003] de féltem.
```

Python a `[NNN]` markerek mentén szétbontja, visszailleszti az időbélyegekhez.

Promptban tördelési hint:
```
SYSTEM:
Minden [NNN] sort külön sorban fordíts le. A mondathatárok
maradjanak ugyanazokon a [NNN] helyeken, ahol az angolban vannak.
Ha a magyar szórend miatt nem fér bele, a VESSZŐ kerüljön
ugyanarra a szekcióra, ahol az angolban is volt.
Kötőjeles párbeszédnél ([001] - Yes. [002] - No.) a kötőjelet tartsd.
```

### Stratégia 3: mondat-összefűzés + arányos visszatördelés (nem ajánlott)

Pszeudokód:
```python
group = ["I wanted to tell you", "that I love you,", "but I was afraid."]
original_lengths = [20, 16, 18]  # karakter-arányok
hu = translate(" ".join(group))  # "El akartam mondani, hogy szeretlek, de féltem."
# Tördeld vissza az eredeti arány szerint, mondathatárt (vessző) preferálva
```

**Problémák a 3. stratégiával:**

1. **Visszatördelés algoritmikusan nehéz** — nincs 1:1 szó-megfeleltetés,
   karakter/szó/vessző-alapú vágás mind másként hibázik.
2. **Szórendváltás → torz tördelés** — magyar gyakran elölre hozza azt, ami
   angolban hátul van ("A zaj miatt nem tudtam aludni").
3. **Időzítés-tartalom aszinkron** — ha a magyar más sorrendben mondja el, a
   felirat nem lesz szinkronban a beszéddel.
4. **Rövid szekciók elvesznek** — 1 másodperces szekcióba fél szó kerülhet.
5. **Párbeszéd-csoportosítás** — a pont/kérdőjel alapú gruppolás összekeverheti
   a külön beszélők megszólalásait; kötőjelet kell figyelni.
6. **Hibahalmozódás** — csoportosítás → fordítás → visszatördelés, mindegyikben hibaarány.
7. **Debug-olhatatlan** — nem derül ki, melyik lépés rontotta el.

**Mikor éri meg mégis a 3. stratégia:**
- hosszú monológok (természetes folyás > pontos szinkron)
- dalszöveg (úgyis művészi fordítás)
- ha a 2. stratégia mérhetően rosszabb

**Gyakorlati ajánlás:** maradj 2. stratégiánál; csak problémás csoportokra
alkalmazz 3.-at (hibrid megközelítés, lektor-lépéssel azonosítva).

---

## 5. Magyar ikes igék kezelése translategemma-val

**Konkrét publikus info nincs** — sem benchmark, sem közösségi teszt nem található.

### Amit tudunk

- Hungarian támogatott (`hu` / `hu-HU`), 55 nyelv egyike
- Gemma 3-alapú, 4B / 12B / 27B
- A Gemma-család általában gyenge a magyar morfológiai finomságokban
- Méret (12B vs 27B) nem garancia — ez **adat-, nem méretkérdés**

### Várható hibaminták (Gemma-család általánosan)

1. **E/2 alak a leggyakoribb hiba**: "tetszesz" vs. helyes "tetszel",
   "eszesz" vs. "eszel". Köznyelvi nem-ikes ragozást húz rá.
2. **Felszólító mód**: "egyél" vs. "eddél", "igyál" vs. "iddál" — keveri.
3. **Feltételes E/1**: "enném" vs. "ennék" — ikes szabály szerint "-m", random.
4. **E/3 általában jó** ("tetszik neked?").

### Tesztelési javaslat

~20 mondatos tesztkészlet ikes edge case-ekkel:
- "I like you" → "tetszel nekem" (E/2 ikes — fő hibapont)
- "Eat something!" → "Egyél valamit!" (felszólító)
- "I would eat" → "Ennék" (feltételes E/1)
- "Does it suit you?" → "Tetszik neked?" (E/3 kontroll)

Ha >20% hibás:

- **Post-processing szótár** (legajánlottabb): Python regex-ekkel javítani a
  gyakori hibákat. Ikes igék listája véges (~20–30 gyakori), kezelhető.
  A CLAUDE.md-ben szereplő "tetszel nekem" szabály ilyen javítási lista alapja.
- **System promptba explicit szabály**: kevésbé megbízható, Gemma nem tartja
  be szigorúan.
- **Claude fallback kritikus mondatoknál**: ikes-gyanús minta detektálásakor
  átküldeni erősebb modellnek.

---

## 6. Következtetés — mikor térj vissza ehhez

**Translategemma:12b előnyei**
- offline, ingyenes, korlátlan
- Mac mini-n lokálisan fut
- glossary beégethető Modelfile-lal

**Hátrányai a Claude-hoz képest**
- gyengébb magyar morfológia (ikes igék, nemfüggő formák)
- komplex szabályrendszert nem tart be (nem-alapú "megházasodni" logika)
- formátum-megtartás nem garantált → Python-os védőháló kell
- összetett kontextus (visszaemlékezések, karakterviszonyok) nehézkes

**Hibrid munkamenet lenne ideális**
- egyszerű blokkok → translategemma (gyors, ingyen)
- bonyolult blokkok / dalszöveg / ikes-gyanús → Claude fallback
- post-processing minden esetben (ikes-javító szótár, formátum-validáció)

---

## Hivatkozások

- https://ollama.com/library/translategemma
- https://github.com/dwain-barnes/local-translator
- https://en.wikipedia.org/wiki/Hungarian_verbs
