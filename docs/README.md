# Dokumentáció — tartalomjegyzék

[Kezdőlap](../README.md)

A fejezetek sorban olvasva végigvezetnek a telepítéstől az utómunkáig; mindegyik alján „előző / következő” link van. Egy konkrét kérdéshez a lenti alfejezet-listából ugorj közvetlenül.

1. **[Telepítés és mappaszerkezet](01-telepites.md)** — előfeltételek, letöltés, új sorozat indítása, frissítés új verzióra, a mappák szerepe
   - [Előfeltételek](01-telepites.md#előfeltételek)
   - [Telepítés](01-telepites.md#telepítés)
      - [Új gépen — letöltés GitHub-ról](01-telepites.md#új-gépen--letöltés-github-ról)
      - [Új projekt indítása](01-telepites.md#új-projekt-indítása)
      - [Meglévő fordítás átvétele (vtt-import)](01-telepites.md#meglévő-fordítás-átvétele-vtt-import)
      - [Frissítés új verzióra](01-telepites.md#frissítés-új-verzióra)
   - [Mappaszerkezet](01-telepites.md#mappaszerkezet)
2. **[Az első epizód — a teljes folyamat](02-elso-epizod.md)** — egy epizód lépésről lépésre, a szabályok átadása a modellnek, workflow-skillek
   - [Használat (PowerShell)](02-elso-epizod.md#használat-powershell)
      - [Teljes folyamat (egy epizód)](02-elso-epizod.md#teljes-folyamat-egy-epizód)
   - [Kontextus-átadás — fontos!](02-elso-epizod.md#kontextus-átadás--fontos)
   - [Workflow-skillek](02-elso-epizod.md#workflow-skillek)
3. **[Szójegyzék és megszólítási regiszter](03-szojegyzek.md)** — a fordítás előtti lépések: glossary, alap-szótárak, a tegezés/magázás kinyerése
   - [Szójegyzék bővítése](03-szojegyzek.md#szójegyzék-bővítése)
      - [Biztos / bizonytalan javaslatok](03-szojegyzek.md#biztos--bizonytalan-javaslatok)
      - [Amit a kinyerő lát](03-szojegyzek.md#amit-a-kinyerő-lát)
      - [Alap-szótárak (glossaries/)](03-szojegyzek.md#alap-szótárak-glossaries)
   - [Megszólítási regiszter kinyerése (subtr.py register) — opcionális](03-szojegyzek.md#megszólítási-regiszter-kinyerése-subtrpy-register--opcionális)
4. **[Fordítás](04-forditas.md)** — forrásnyelv, a fordító providerek és kapcsolóik
   - [Forrásnyelv](04-forditas.md#forrásnyelv)
      - [Hogyan derül ki a forrásnyelv?](04-forditas.md#hogyan-derül-ki-a-forrásnyelv)
      - [Miért számít ez a tegezés/magázásnál?](04-forditas.md#miért-számít-ez-a-tegezésmagázásnál)
      - [A regiszter forrása lehet MÁS, mint a fordításé](04-forditas.md#a-regiszter-forrása-lehet-más-mint-a-fordításé)
   - [Más forrásnyelv (nem angol forrásból)](04-forditas.md#más-forrásnyelv-nem-angol-forrásból)
   - [Fordítás — opciók](04-forditas.md#fordítás--opciók)
      - [Claude Code fordító (subtr.py translate --provider claude)](04-forditas.md#claude-code-fordító-subtrpy-translate---provider-claude)
      - [Gemini API fordító (subtr.py translate --provider gemini) — alternatíva](04-forditas.md#gemini-api-fordító-subtrpy-translate---provider-gemini--alternatíva)
      - [Codex fordító (subtr.py translate --provider codex) — alternatíva](04-forditas.md#codex-fordító-subtrpy-translate---provider-codex--alternatíva)
      - [Grok fordító (subtr.py translate --provider grok) — alternatíva](04-forditas.md#grok-fordító-subtrpy-translate---provider-grok--alternatíva)
      - [Antigravity fordító (subtr.py translate --provider antigravity) — alternatíva](04-forditas.md#antigravity-fordító-subtrpy-translate---provider-antigravity--alternatíva)
5. **[Review és javítás](05-review.md)** — a review providerei, megszakadt review folytatása, a javaslatok alkalmazása
   - [Review — opciók](05-review.md#review--opciók)
      - [Antigravity review (subtr.py review — az alapérték)](05-review.md#antigravity-review-subtrpy-review--az-alapérték)
      - [Claude review (subtr.py review --provider claude)](05-review.md#claude-review-subtrpy-review---provider-claude)
      - [Gemini review (subtr.py review --provider gemini)](05-review.md#gemini-review-subtrpy-review---provider-gemini)
      - [Grok review (subtr.py review --provider grok)](05-review.md#grok-review-subtrpy-review---provider-grok)
      - [Codex review (subtr.py review --provider codex)](05-review.md#codex-review-subtrpy-review---provider-codex)
      - [Megszakadt vagy hiányos review](05-review.md#megszakadt-vagy-hiányos-review)
      - [Review-javaslatok alkalmazása (subtr.py apply)](05-review.md#review-javaslatok-alkalmazása-subtrpy-apply)
      - [Nem interaktív alkalmazás (subtr.py apply-auto)](05-review.md#nem-interaktív-alkalmazás-subtrpy-apply-auto)
6. **[Provider, modell és effort](06-providerek.md)** — melyik funkció melyik modellel fusson, .env-beállítások
   - [Provider, modell és effort .env-ből](06-providerek.md#provider-modell-és-effort-env-ből)
      - [Claude — ajánlott modell és effort](06-providerek.md#claude--ajánlott-modell-és-effort)
7. **[Gemini: modellek, limitek, kvóta](07-gemini-kvota.md)** — modellválasztás, Free tier és saját limitek, napi kvóta, modellváltás
   - [Gemini modellek — mit érdemes választani](07-gemini-kvota.md#gemini-modellek--mit-érdemes-választani)
   - [Gemini-modellek, limitek, kivezetések (subtr.py models)](07-gemini-kvota.md#gemini-modellek-limitek-kivezetések-subtrpy-models)
      - [A program a Free tier limitjeivel érkezik](07-gemini-kvota.md#a-program-a-free-tier-limitjeivel-érkezik)
      - [Saját limitek beállítása](07-gemini-kvota.md#saját-limitek-beállítása)
      - [Napi limitnél modellváltás](07-gemini-kvota.md#napi-limitnél-modellváltás)
      - [Ha a programot fejleszted: a beépített adat frissítése](07-gemini-kvota.md#ha-a-programot-fejleszted-a-beépített-adat-frissítése)
   - [Gemini kvóta — mennyi hívás van még ma? (subtr.py quota)](07-gemini-kvota.md#gemini-kvóta--mennyi-hívás-van-még-ma-subtrpy-quota)
8. **[Utómunka](08-utomunka.md)** — review-hibák, sorhossz-szegmentálás, Subtitle Edit, kézi lektorálás, MKV
   - [Utómunka — a review után](08-utomunka.md#utómunka--a-review-után)
      - [1. Review-hibák javítása](08-utomunka.md#1-review-hibák-javítása)
      - [2. Automatikus szegmentálás — subtr.py resegment](08-utomunka.md#2-automatikus-szegmentálás--subtrpy-resegment)
      - [3. Technikai javítás Subtitle Edit-tel](08-utomunka.md#3-technikai-javítás-subtitle-edit-tel)
      - [4. Végső kézi lektorálás](08-utomunka.md#4-végső-kézi-lektorálás)
      - [Opcionális: a kész felirat az MKV-ba](08-utomunka.md#opcionális-a-kész-felirat-az-mkv-ba)
9. **[Tippek](09-tippek.md)** — gyakorlati tanácsok
   - [Tippek](09-tippek.md#tippek)
10. **[Fejlesztés és háttér](10-fejlesztes.md)** — fejlesztőknek: tesztek, commit előtti szűrő; mindenkinek: hogyan készült
   - [Fejlesztés](10-fejlesztes.md#fejlesztés)
      - [Fejlesztői beállítás egy új clone-ban](10-fejlesztes.md#fejlesztői-beállítás-egy-új-clone-ban)
      - [Commit előtti szűrő — jogvédett tartalom és titok](10-fejlesztes.md#commit-előtti-szűrő--jogvédett-tartalom-és-titok)
   - [Hogyan készült — AI-asszisztált fejlesztés](10-fejlesztes.md#hogyan-készült--ai-asszisztált-fejlesztés)

## Hivatkozott dokumentumok

- `TRANSLATION.md` — közös fordítási szabályok és sorozat-kontekstus
- `CLAUDE.md` — Claude Code belépési pont a közös szabályzathoz
- `steps.txt` — gyors parancs-cheatsheet
- `resegment_srt.md` — a szegmentáló eszköz (`subtr.py resegment`) részletes leírása
- `proposals/` — fejlesztési irányok, alternatívák, tervezési dokumentumok
  (lásd: [`proposals/README.md`](../proposals/README.md))
- `addons/` — opcionális segédscriptek (lásd: [`addons/README.md`](../addons/README.md))
- `LICENSE` — MIT licenc

