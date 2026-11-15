# 9. Tippek

[Kezdőlap](../README.md) · [Tartalomjegyzék](README.md)

## Tippek

- **Agent szám:** 3 az ajánlott. Gemininél `--agents 10` fölött 429 rate limit jöhet
  (a parancs figyelmeztet is); Claude-nál/Codexnél a CLI-folyamatok száma a korlát.
- **Blokk méret:** 150 az alapértelmezett. Ha sok a hiba, csökkentsd 100-ra.
- **TRANSLATION.md:** Minél részletesebb az aktuális sorozat adatai rész, annál jobb
  a fordítás minősége (karakter-háttér, formalitás-szintek, kontextus).
- **Megszólítási regiszter:** a tegezés/magázás az angol forrásból nem derül ki
  megbízhatóan, a magyar viszont megköveteli a döntést. A `TRANSLATION.local.md`
  *Megszólítási regisztere* (ki kit tegez / magáz) minden blokk promptjába bekerül,
  ezért ez az egyetlen eszköz, ami a **párhuzamosan futó blokkok között** egységes
  formát tud tartani. Minden epizód előtt frissítsd — egy elavult regiszter rosszabb,
  mint a hiányzó: magabiztosan rossz formát kényszerít. A döntési eljárást a
  `TRANSLATION.md` *Tegezés/magázás* szakasza írja le. Kézzel írod, de a
  `subtr.py register` felkínál egy első változatot (lásd: [3. fejezet](03-szojegyzek.md#megszólítási-regiszter-kinyerése-subtrpy-register--opcionális)).
- **Checkpoint:** mind az öt fordító-ág fájl-alapú checkpointtal fut (újraindításkor
  csak a hiányzó blokkokat fordítja; a szekció-eltéréses blokk outputja
  törlődik, így az is újramegy). A review is folytatható: a kész chunkok
  részeredmény-fájlba (`.partial`) mentődnek, ugyanaz a parancs újra csak a
  hiányzókat futtatja (lásd [*Megszakadt vagy hiányos review*](05-review.md#megszakadt-vagy-hiányos-review)). A `subtr.py merge`
  `--force` kapcsolóval hiányzó blokkok mellett is összefűz (a hiányt listázza).
- **Részleges megtagadás:** ha az agent szerkezetileg ép fájlt ír, de egyes cue-k
  helyére placeholdert tesz (`[DAL]`, `[SONG]`, `[TODO]`, üres szöveg ott, ahol a
  forrásban volt), a blokk `warning`-gal törlődik és újrafutáskor újramegy — a
  hiányos fordítás nem kerül a merge-be. A részletes ok (az érintett cue-k és az
  agent válasza) a projekt gyökerében lévő **`.translate.log`**-ban van
  (gitignore-olt, 2 MB fölött `.translate.log.1`-re forog).
- **Fordító finomhangolás:** `subtr.py translate --provider claude --timeout <mp>` (default
  900), `--max-turns <n>` (default 20, futó-galopp elleni plafon),
  `--no-cleanup` (régi sys-prompt fájlok megtartása); `subtr.py glossary
  --timeout <mp>` (default 300).
- **Review-k összevetése:** ugyanazon a fájlon futtathatsz több review-t —
  a két modell más-más típusú hibákat talál (Claude inkább kontextus,
  Gemini inkább morfológia / ikes igék).
- **Review modell-választás — tapasztalati javaslat:** kezdetben Claude
  Opus-szal (`subtr.py review --provider claude`) review-oztam, ami minőségileg jó,
  de drága. Később átálltam a Gemini API-ra (`subtr.py review --provider gemini`; ma az alapérték
  már az Antigravity), és nem
  bántam meg — töredék költséggel hasonló minőséget ad a felirat-review
  feladathoz. Ha most kezdesz, érdemes Gemini-vel próbálkozni elsőként.
  A jelenlegi default a `gemini-3.8-flash`; ha a napi kvótád szűkös, a
  `--model gemini-3.5-flash-lite` a bevált olcsó alternatíva (a korábbi
  default a `gemini-3.1-flash-lite` volt, azzal is használható a pipeline).
- **Gemini napi limit:** ingyenes szinten a `-lite` modellek bőkezűek, a
  nem-lite modellek viszont tapasztalat szerint napi ~20 kérésnél elfogynak —
  **modellenként külön**, ezért modellváltással aznap tovább lehet dolgozni.
  (Nagyságrend: egy ~400 szekciós rész review-ja 4-5 kérés.) Hogy hol tartasz:
  `python subtr.py quota`. Ha egy hosszú futás közben fogyna el, a review megáll,
  hiányos riportot ír a kész részből, és később ugyanazzal a paranccsal
  folytatható (lásd [*Megszakadt vagy hiányos review*](05-review.md#megszakadt-vagy-hiányos-review)).
- **Prompt cache:** a `subtr.py translate --provider claude` a system promptot tartalom-hash
  alapján fájlba menti, így a párhuzamos agent-ek és az ismételt futások is
  cache-hit-tel indulhatnak — drasztikus költségcsökkenés.

---

[← 8. Utómunka](08-utomunka.md) · [Tartalomjegyzék](README.md) · [10. Fejlesztés és háttér →](10-fejlesztes.md)
