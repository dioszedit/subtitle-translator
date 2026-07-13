# resegment_srt — felirat-újraszegmentáló és QA eszköz

Determinisztikus, **függőség nélküli** (csak Python 3 stdlib) eszköz, ami a
fordítás UTÁN egy menetben rendezi a felirat **szegmentálását**: minden sor a
karakter-plafon alatt marad, mondat-/tagmondat-határon törve, az időzítés
érintése nélkül. A projekt utómunka-lépése (`README.md` → *Utómunka* / 2. lépés);
kiegészíti a `verify_srt.py`-t (az a CPS-t jelzi, de sorhosszt/tördelést nem).

## Miért van rá szükség

Két feliratforrás mérése (medián) jól mutatja, hogy **ellentétes kényszert**
optimalizálnak — egyik sem teljesíti egyszerre mindkét szabályt:

| Metrika | Angol SRT rip | AI-fordítás (VTT) |
|---|---|---|
| CPS (olvasási sebesség) | ~15–16 | ~11–13 ✅ |
| Cue-k > 17 CPS | 37–45% ❌ | 14–18% ✅ |
| Sorok > 42 karakter | 0% ✅ | 5–8% ❌ |

Az AI-fordítás jó CPS-ű és ép mondatú, de néha **túllépi a sorhosszt**. Ez az
eszköz pont ezt javítja automatikusan (kockázat nélkül), a maradékot pedig jelzi.

## Használat

```bash
# 1) QA-riport (csak olvasás): mit kell javítani?
python resegment_srt.py report "output/…hun.srt"

# 2) Sorhossz-tisztítás (időzítést NEM változtat) -> új fájlba
python resegment_srt.py reflow "output/…hun.srt" -o "output/…hun.reflow.srt"
#    …vagy helyben:  --in-place    …vagy stdout-ra: (elhagyva -o / --in-place)

# 3) Ha kell: a 2 sorba nem férő cue-k idő-arányos bontása (cue-számot változtat)
python resegment_srt.py reflow "output/…hun.srt" --split -o "…split.srt"
```

Paraméterek (alapérték): `--max-chars 42`, `--max-lines 2`, `--target-cps 17`,
`--min-dur 1.0`, `--max-dur 7.0`, `--min-gap 0.08`, `--lang hu`.

## Módok

- **report** — cue-nkénti CPS/sorhossz/rés metrika + flag-ek (`CPS`, `LINE`,
  `LINES`, `SHORT`, `LONG`, `GAP`) és összegzés. Ez a QA-kapu és a verifikáció
  alapja is. A ~0-s (láncolt, érintkező) réseket NEM jelzi hibának, csak a
  villódzás-kockázatos kis réseket és az átfedéseket.
- **reflow** (biztonságos alapművelet) — a plafont sértő cue-kat
  kiegyensúlyozott ≤`max-lines` sorra tördeli, mondat-/tagmondat-határon.
  Idempotens; a már megfelelő cue-kat érintetlenül hagyja; a `szám + időbélyeg`
  sorok **bitre változatlanok**; `<i>…</i>` és `- ` párbeszédjelek megőrizve.
  Amit ≤`max-lines` sorba nem lehet betördelni, azt **flag-eli** (nem rontja el).
- **--split** (opcionális) — a flag-elt, egyszereplős, túl hosszú cue-kat több
  egymást követő cue-ra bontja, az időt a karakterszámmal arányosan osztva
  (`min-dur`/`min-gap` védelemmel; ha az idő ehhez kevés, a cue-t inkább
  egyben hagyja, átfedő/érvénytelen időzítést sosem ír ki). Cue-számot
  változtat, ezért külön kapcsoló.

## Töréspont-logika (a lényeg)

Ha egy sor > `max-chars`, olyan szóköz-töréspontot választ, ahol **mindkét sor
belefér**, és a "badness" minimális, ezzel a prioritással:
1. erős központozás után (`. ! ? … ; :`) · 2. vessző után ·
3. kötőszó **előtt** (`és, de, hogy, mert, ha, aki, ami, ahol …` — nyelvmodulból) ·
4. a felezőponthoz legközelebb (kiegyensúlyozott sorok).
Kerüli: névelő (`a, az, egy`) sorvégen; szám elszakítása; 1–2 karakteres csonka sor.

## Általánosítás más nyelvre / csatornára

- **Más nyelv:** vedd fel a scripten belüli `LANG` szótárba a kulcsot
  (`conj`, `articles` halmaz), és add meg `--lang xx`. A `generic` nyelv üres
  listákkal is működik (marad a központozás + felezőpont heurisztika).
- **Más plafon:** mind CLI-flag (pl. Netflix 42, mások 37/39/40).
- **Pipeline:** `fordítás → review → resegment (report + reflow) → Subtitle Edit
  (CPS/időzítés) → végső kézi lektorálás`. A `report` a kézi lépés elé tett QA-kapu.

## Kapcsolódó, általánosítható technika

Eltérően szegmentált források (angol felirat ↔ AI-fordítás ↔ teljes szövegkönyv)
**cue-index szerint nem** rendezhetők össze — **időbélyeg-átfedéssel** igen. Ez
teszi lehetővé a fordítás visszaellenőrzését az angol forráshoz
(megszólítás/nem/kontextus). A szövegkönyv, ha van, a puszta feliratból nem
látszó kontextust (ki beszél, kihez, milyen nemben) adja meg — a legtöbb
szemantikai hiba forrása enélkül.
