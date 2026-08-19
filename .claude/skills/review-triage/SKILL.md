---
name: review-triage
description: Review-javaslatok átvizsgálása és alkalmazása — a _REVIEW_*.json riportok minden találatát a forráshoz méri, kiszűri a no-opokat és hamis riasztásokat, decisions.json-t épít, és az apply_review_auto.py-jal átvezeti a jóváhagyottakat. Akkor használd, ha a felhasználó a review-találatok javítását, átvezetését vagy átnézését kéri.
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
2. **Riportok**: a hun.srt mellett `<stem>_REVIEW_CLAUDE*.json` és
   `<stem>_REVIEW_GEMINI*.json` (ha egy riportnak .json és .txt változata is van,
   a .json a kanonikus). Ha EGYIK sincs → állj meg, és mondd meg, hogy előbb
   review-t kell futtatni (`review_with_claude.py` / `review_with_gemini.py`).
3. **Forrás SRT**: a hun.srt nevéből `.hun.` → `.eng.` csere, keresés az
   `input/`-ban és a hun.srt mellett. Ha nem található (pl. nem angol a forrás),
   kérdezd meg a felhasználót, melyik fájl a forrás — forrás nélkül csak
   óvatosabb triage lehetséges, és ezt jelezd is az összegzésben.

## 2. Aktuális állapot beolvasása

Olvasd be a hun.srt-t szekciónként (sorszám → szöveg). A riportok `eredeti`
mezője elavulhatott (a fájl azóta módosulhatott) — az ítélethez és a
decisions.json-hoz MINDIG a fájl AKTUÁLIS szövege kell.

## 3. Minden találat megítélése

A két riport találatait szekciószám szerint fésüld össze. Találatonként:

| Helyzet | Döntés |
|---|---|
| javaslat == aktuális szöveg (whitespace-normalizáltan) | **no-op** — eldob, számol |
| a riport `eredeti`-je ≠ aktuális szöveg | már javítva vagy elcsúszott — **kihagy** |
| nem létező magyar szóalak a javaslatban | **eldob** |
| a javaslat ellentmond a glossary.json-nak | **eldob** (a glossary kötelező) |
| tegezés/magázás-riasztás, amit a *Megszólítási regiszter* alátámaszt | **elfogad** — a regiszter kötelező, a fordító tévedett |
| tegezés/magázás-riasztás indoklás nélkül (a `hiba` mező nem nevez meg regiszter-sort, forrás-jelet vagy ütköző sorszámot) | **eldob** |
| egyéb tegezés/magázás-riasztás | a forrás + a jelenet kontextusa alapján ítélj (ki beszél kihez); kétes esetben **eldob** |
| a javaslat mást mond, mint a forrás | **eldob** — a "javítás" nem lehet hűtlenebb az eredetinél |
| jó irányú, de pontatlan javaslat | **átírva elfogad** — a végleges szöveget te adod meg |
| mindkét lektor ugyanazt javasolja | magasabb bizalom, de a forrás-ellenőrzés akkor is kötelező |

Kétely esetén az eldobás a biztonságos irány: egy kihagyott jó javítás olcsóbb,
mint egy átvezetett rossz.

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
py apply_review_auto.py "<hun.srt>" "<decisions.json>" --dry-run
```

Mutasd meg a felhasználónak az összegzést: hány javaslat érkezett a riportokból,
ebből mennyi lett elfogadva / no-opként eldobva / hamisként eldobva / átírva —
kategóriánként darabszámmal és 1-2 példával. Jóváhagyás UTÁN futtasd `--dry-run`
nélkül. (Az első íráskor a script .bak mentést készít.)

Ha a dry-run "ELTÉRÉS" sorokat jelez, az a 3. lépés hibája (rossz `eredeti`
került a fájlba) — javítsd a decisions.json-t, ne `--ignore-drift`-tel törd át.

## 6. Zárójelentés

Az alkalmazás után: mennyi ment át, mi lett eldobva és MIÉRT (kategóriánként),
és emlékeztető, hogy a resegment (`resegment_srt.py report/reflow`) csak EZUTÁN
következik.
