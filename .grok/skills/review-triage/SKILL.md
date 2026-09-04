---
name: review-triage
description: Review-javaslatok átvizsgálása és alkalmazása — a _REVIEW_*.json riportok minden találatát a forráshoz méri, kiszűri a no-opokat és hamis riasztásokat, decisions.json-t épít, és a subtr.py apply-auto-val átvezeti a jóváhagyottakat. Akkor használd, ha a felhasználó a review-találatok javítását, átvezetését vagy átnézését kéri.
argument-hint: <hun.srt útvonal>
---

# Review-triage — javaslatok megítélése és átvezetése

A review-modellek javaslatainak jelentős része téves (mért adat 10 részen: ~13%
no-op, plusz nem létező szóalakok és hamis tegezés/magázás-riasztások). Ezért a
javaslatok NEM vezethetők át szűrés nélkül — minden találatot egyesével a
forrásnyelvi eredetihez kell mérni. Ez a skill ezt a triage-folyamatot írja le.

A fordítási szabályok forrása a projekt gyökerében lévő **TRANSLATION.md**
(különösen a "Tegezés/magázás" és a "Gyakori hibák" szakasz), a sorozat-specifikus
**TRANSLATION.local.md** (itt van a *Megszólítási regiszter*, ami eldönti, ki kit tegez
vagy magáz) és a **glossary.json** — ítélet előtt olvasd be mind a hármat. A szabályokat
NE innen idézd, hanem onnan.

## 1. Bemenetek összegyűjtése

1. **A magyar SRT**: az argumentumban kapott `hun.srt` (ha nincs argumentum,
   keresd az `output/` legfrissebb `.hun.srt` fájlját, és erősíttesd meg).
2. **Riportok**: a hun.srt mellett `<stem>_REVIEW_CLAUDE*.json`,
   `<stem>_REVIEW_GEMINI*.json`, `<stem>_REVIEW_CODEX*.json` és
   `<stem>_REVIEW_GROK*.json` (ha egy riportnak .json és .txt változata is van,
   a .json a kanonikus). Ha EGYIK sincs → állj meg, és mondd meg, hogy előbb
   review-t kell futtatni
   (`py subtr.py review [--provider claude|codex|grok]`).
3. **Forrás SRT**: a hun.srt nevéből a `.hun.` tag helyére a forrásnyelv kódja
   (`.eng.`, `.ger.`, … — bármelyik ismert kód), keresés az `input/`-ban és a
   hun.srt mellett. Ha nem található (a fájlnév nem követi a konvenciót),
   kérdezd meg a felhasználót, melyik fájl a forrás — forrás nélkül csak
   óvatosabb triage lehetséges, és ezt jelezd is az összegzésben.

## 2. Aktuális állapot beolvasása

Olvasd be a hun.srt-t szekciónként (sorszám → szöveg). A riportok `eredeti`
mezője elavulhatott (a fájl azóta módosulhatott) — az ítélethez és a
decisions.json-hoz MINDIG a fájl AKTUÁLIS szövege kell.

## 3. Minden találat megítélése

A riportok találatait szekciószám szerint fésüld össze. Találatonként:

| Helyzet | Döntés |
|---|---|
| javaslat == aktuális szöveg (whitespace-normalizáltan) | **no-op** — eldob, számol |
| a riport `eredeti`-je ≠ aktuális szöveg | már javítva vagy elcsúszott — **kihagy** |
| nem létező magyar szóalak a javaslatban | **eldob** |
| a javaslat ellentmond a glossary.json-nak | **eldob** (a glossary kötelező) |
| tegezés/magázás-riasztás, amit a *Megszólítási regiszter* alátámaszt | **elfogad** — a regiszter kötelező, a fordító tévedett |
| tegezés/magázás-riasztás indoklás nélkül (a `hiba` mező nem nevez meg regiszter-sort, forrás-jelet vagy ütköző sorszámot) | **eldob** |
| a `hiba` hivatkozik valamire (regiszter-sor, glossary-bejegyzés, szabály), de az ott NINCS úgy | **eldob** — a hivatkozást is ellenőrizd, ne csak a javaslatot |
| a riport a *Megszólítási regiszter* `kivétel:` sorával ütközik | **eldob** — a jelölt kilépés szándékos |
| egyéb tegezés/magázás-riasztás | a forrás + a jelenet kontextusa alapján ítélj (ki beszél kihez); kétes esetben **eldob** |
| a javaslat mást mond, mint a forrás | **eldob** — a "javítás" nem lehet hűtlenebb az eredetinél |
| jó irányú, de pontatlan javaslat | **átírva elfogad** — a végleges szöveget te adod meg |
| mindkét lektor ugyanazt javasolja | magasabb bizalom, de a forrás-ellenőrzés akkor is kötelező |

Kétely esetén az eldobás a biztonságos irány: egy kihagyott jó javítás olcsóbb,
mint egy átvezetett rossz.

### Tegezés/magázás: a találat SWEEP-TRIGGER, nem egysoros javítás

A lektorok egy rendszerszintű regiszterhibának jellemzően csak a töredékét
jelzik (mért eset: egy jelenet 9 tegező sorából 3-at). Ha csak a jelzett
sorokat vezeted át, a jelenet FÉLIG marad átállítva — ez rosszabb, mint bármelyik
véglet. Ezért egy elfogadott regiszter-találat után:

1. Nézd végig az ADOTT KARAKTERPÁR összes sorát a jelenetben (és ha az epizód
   más pontján is beszélnek, ott is), ne csak a jelzetteket.
2. A hiányzókat vedd fel a decisions.json-ba, és az összegzésben KÜLÖN jelöld
   őket „riporton kívüli, konzisztencia" tételként — a felhasználó vétózhat.
3. Előbb tisztázd, **ki beszél kihez**. A leggyakoribb néma hiba nem a
   formalitás félreolvasása, hanem a téves beszélő-hozzárendelés: az így
   keletkezett javítás konzisztensnek látszik, tehát magától nem bukik ki.
   Ha a videó visz eredeti nyelvű feliratsávot (`addons/mkv-subs`), annak a
   beszélőcímkéi (`（緑）`, `（伸子）`) és formalitás-alakjai (keigo, beszédszint)
   egy lépésben eldöntik mindkettőt — érdemes ezt megnézni, mielőtt regiszter-
   ügyben döntesz.
4. Ne „javítsd ki" a jelölt kivételt: ha egy szereplő egy jelenet erejéig
   szándékosan lép ki a regiszteréből, az megtartandó. Ha ilyet találsz, és a
   `TRANSLATION.local.md`-ben nincs `kivétel:` sora, javasold a felvételét.

## 4. decisions.json írása

A hun.srt mellé, `<stem>_decisions.json` néven, CSAK az elfogadott (esetleg
átírt) javaslatokkal:

```json
[
  {"sorszam": 12, "eredeti": "<a fájl AKTUÁLIS szövege>", "javaslat": "<a végleges magyar szöveg>"}
]
```

- Az `eredeti` a fájl JELENLEGI szövege (drift-védelem az apply-nál), NEM a riporté.
- Többsoros szöveg `\n`-nel.
- A sorszámhoz nem nyúlsz, időbélyeget a döntés-fájl nem tartalmaz.

## 5. Dry-run → jóváhagyás → alkalmazás

```powershell
py subtr.py apply-auto "<hun.srt>" "<decisions.json>" --dry-run
```

Mutasd meg a felhasználónak az összegzést: hány javaslat érkezett a riportokból,
ebből mennyi lett elfogadva / no-opként eldobva / hamisként eldobva / átírva —
kategóriánként darabszámmal és 1-2 példával. Jóváhagyás UTÁN futtasd `--dry-run`
nélkül. (Az első íráskor a script .bak mentést készít.)

Ha a dry-run "ELTÉRÉS" sorokat jelez, az a 3. lépés hibája (rossz `eredeti`
került a fájlba) — javítsd a decisions.json-t, ne `--ignore-drift`-tel törd át.

## 6. Zárójelentés

Az alkalmazás után: mennyi ment át, mi lett eldobva és MIÉRT (kategóriánként),
és emlékeztető, hogy a resegment (`subtr.py resegment report/reflow`) csak EZUTÁN
következik.
