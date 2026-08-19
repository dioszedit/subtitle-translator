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
Megszólítási regiszter:   (frissítendő MINDEN epizód előtt)
  - [A] → [B]: MAGÁZ | TEGEZ  ([viszony, pl. beosztott→főnök])
  - [A] ↔ [B]: TEGEZ  ([kölcsönös viszony])
  - alapértelmezés idegenekkel: MAGÁZ
  - váltás: [A] ↔ [B] TEGEZ a(z) [N]. rész [cue-tartomány vagy jelenet] után
Special terms:
  - [forráskifejezés] = [jóváhagyott magyar megfelelő]
Previous episodes: [eddigi történet, ha releváns]
```

A *Megszólítási regiszterben* a `→` egyirányú viszonyt jelöl (aszimmetrikus: pl. a főnök
tegez, a beosztott magáz), a `↔` kölcsönöset. Kis szereplőket nem kell felsorolni, azokat
az alapértelmezés fedi. A `váltás` sor **jelenet-granularitású**: epizódon belüli
tegeződésre váltásnál a cue-tartomány (pl. „a 312. felirat után") az egyetlen támpont,
amiből a blokkonként dolgozó fordító tudja, melyik oldalon van — epizód-szintű jelölés itt
nem elég. A megszólítások konkrét magyar alakját a `glossary.json` `honorifics`
bejegyzései rögzítik; a regiszter azokra épül, nem melléjük.

A regisztert kézzel írod. Ha első változatot szeretnél a forrásfeliratból, a
`register_extract.py` felkínál egyet (opcionális lépés, interaktív jóváhagyással).

## Kötelező fordítási szabályok

1. Csak a szöveget fordítsd angolról természetes, beszélt magyarra; ne tükörfordíts.
2. A sorszám és időbélyeg 1:1 maradjon. A Python pipeline ezt szerkezetileg védi.
3. Őrizd meg a HTML tageket (`<i>`, `</i>`, `<b>`, `</b>`), a kötőjeles párbeszédet, a `♫` jelet és a sortöréseket, amikor a szöveg megkívánja.
4. A szögletes zárójeles megjegyzéseket fordítsd le. Karakternevet ne fordíts le.
5. Az angol "episode" mindig „rész”: „1. rész”, „a következő rész”, sosem „epizód”.
6. A tegezés/magázás a *Megszólítási regiszterből*, ennek hiányában a jelenet kontextusából következzen; kétes esetben ne találj ki biztos viszonyt. Részletes eljárás: *Tegezés/magázás* szakasz.
7. A `glossary.json` jóváhagyott fordításai kötelezőek.

### Tegezés/magázás

A forrásnyelv (angol) nem jelöli a formalitást, a magyar viszont megköveteli a döntést.
Ezért a sorrend kötött — ne ugorj lépést:

1. **Regiszter először.** Ha a szereplőpár szerepel a *Megszólítási regiszterben*, az
   kötelező — akkor is, ha az adott sor önmagában mást sugallna.
2. **Formalitás-jelek a forrásban.** Regiszter hiányában a forrásszöveg explicit
   formalitás-jeleiből indulj ki: megszólítási forma, rang/titulus, udvariassági
   fordulatok, névhasználat. A konkrét jeleket lásd a következő két alszakaszban.
3. **Kétes eset → kerüld ki a döntést.** A magyar sokszor megengedi, hogy a mondat ne
   döntsön: főnévi igenév („Bejöhetek?” → „Szabad?”), többes szám első személy
   („Indulunk?”), személytelen szerkezet, felkiáltás, megszólítás nélküli mondat.
   Példa: *„Are you coming?”* → ne „Jössz?” és ne „Jön?”, hanem „Indulunk?” / „Mehetünk?”.
   Ez az elsődleges stratégia, nem a végszükség.
4. **Ha a kikerülés erőltetett lenne**, a jelenet legvalószínűbb viszonya szerint dönts,
   és a jeleneten belül maradj következetes. Az epizód egészére vonatkozó konzisztenciát a
   regiszter biztosítja — a fordító csak a saját blokkját látja, ezért ott, ahol tartós
   viszonyról van szó, a regisztert kell bővíteni, nem a jelenetből következtetni.

#### Formalitás-jelek angol forrásban

> Ez az alszakasz a forrásnyelvhez kötött. Más forrásnyelvnél cseréld a saját nyelved
> tipikus jeleire — ugyanúgy, ahogy a *Gyakori hibák* angol mintáit.

- **Magázás felé:** `sir` / `ma'am`; `Mr.` / `Ms.` + vezetéknév; titulus + név
  (`Director` / `Manager` / `Professor` / `Chairman Kang`); emelt regiszterű fordulatok
  (`may I`, `would you mind`, `I apologize`); első találkozás; hivatalos helyszín.
- **Tegezés felé:** keresztnév vagy becenév önmagában; `hey`, `dude`; szleng; káromkodás;
  családtag fiatalabb felé; gyerekek egymás közt.

#### Az eredeti nyelvből átvett megszólítások

> Ez az alszakasz a forrás*kultúrához* kötött, nem az angol nyelvhez: ezek a jelek akkor is
> jelen lehetnek, ha a felirat angol. Nem ázsiai eredetinél elhagyható.

`-ssi`, `-nim`, `sunbae`, `hyung` / `unnie` / `oppa` / `noona`, `senpai`, `-san` / `-sama`.
Ezek erősebb jelek bármelyik angol fordulatnál, mert az eredeti nyelv formalitását őrzik.

Fontos árnyalat: a `hyung` / `oppa` típusú megszólítás **közeli, de aszimmetrikus**
viszonyt jelöl — a fiatalabb gyakran mégis udvarias formában beszél. Ezekből tehát nem
következik automatikusan a tegezés.

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
