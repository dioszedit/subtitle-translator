# Feliratfordítás — közös szabályzat

Ez a fájl szolgáltatófüggetlen: Claude, Gemini és Codex fordítási/review folyamatok egyaránt ezt használják.

## Aktuális sorozat adatai

> Minden új sorozatnál töltsd ki ezt a részt a gitignore-os
> `TRANSLATION.local.md` fájlban. A helyi fájl tartalma automatikusan a közös
> szabályzat végéhez kerül, ezért nem kerülhet bele érzékeny vagy publikálni
> nem kívánt adat.

```text
Title: [Cím] ([eredeti cím])
Hungarian title: [Magyar cím]
Country: [Ország]
Episodes: [epizódszám]
Genres: [műfajok]
Synopsis: [2–4 mondat a történetről]
Cast:
  - [Név] — [szerep és viszonyok]
Special terms:
  - [forráskifejezés] = [jóváhagyott magyar megfelelő]
Previous episodes: [eddigi történet, ha releváns]
```

## Kötelező fordítási szabályok

1. Csak a szöveget fordítsd angolról természetes, beszélt magyarra; ne tükörfordíts.
2. A sorszám és időbélyeg 1:1 maradjon. A Python pipeline ezt szerkezetileg védi.
3. Őrizd meg a HTML tageket (`<i>`, `</i>`, `<b>`, `</b>`), a kötőjeles párbeszédet, a `♫` jelet és a sortöréseket, amikor a szöveg megkívánja.
4. A szögletes zárójeles megjegyzéseket fordítsd le. Karakternevet ne fordíts le.
5. Az angol "episode" mindig „rész”: „1. rész”, „a következő rész”, sosem „epizód”.
6. A tegezés/magázás a jelenet kontextusából következzen; kétes esetben ne találj ki biztos viszonyt.
7. A `glossary.json` jóváhagyott fordításai kötelezőek.

### Házasodás és nem

- A `get married` alapból semleges: „megházasodni” vagy „összeházasodni”. Csak biztos férfinál „megnősülni”, biztos nőnél „férjhez menni”.
- Az „I’ll marry you” / „Marry me” esetén a beszélő neme dönt: férfi → „Feleségül veszlek” / „Légy a feleségem”; nő → „Hozzád megyek” / „Légy a férjem”. Kétes helyzetben semleges: „Összeházasodunk” / „Házasodjunk össze”.
- Harmadik személyben férfi valakit „feleségül akar venni”, nő valakihez „hozzá akar menni”.

### Címkártya

Sorozatcím címkártyán mindig két sorban szerepeljen:

```
[Magyar cím]
[Original Title]
```

### Gyakori hibák

| Hiba | Megoldás |
|---|---|
| Tükörfordítás | Természetes magyar megfogalmazás |
| Karakternév lefordítása | A név írásmódját őrizd meg |
| „tetszesz nekem” | „tetszel nekem” |
| `framed me` → „kereteztek be” | Kontextustól függően „tőrbe csaltak”, „rám kentek valamit” |
| `stalker` angolul marad | „zaklató”, „üldöző”, „leselkedő” |
| `What brings you here?` jelen időben | „Mi hozott ma ide?” / magázva „Mi hozta ma ide?” |
