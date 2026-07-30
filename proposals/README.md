# Proposals — Fejlesztési irányok

Ebben a mappában a projekt **lehetséges jövőbeli irányai** vannak:
research jegyzetek, alternatív megoldások, tervezési dokumentumok.

> **Fontos:** ezek **NEM** committed roadmap-elemek vagy aktív TODO-k —
> csak fontolgatott opciók, amikre később vissza lehet térni.
> Ha aktív fejlesztésbe megy át valamelyik, kikerül innen és a fő
> README-ben kap helyet.

## Jelenlegi proposals

| Fájl | Téma | Státusz |
|------|------|---------|
| [translategemma_local.md](translategemma_local.md) | Lokális fordító Mac mini-n (ollama + `translategemma:12b`) — alternatíva a Claude API helyett | Research jegyzet |
| [desktop_gui_v1.md](desktop_gui_v1.md) | Cross-platform desktop GUI a teljes workflow-hoz (Windows + Mac) | Tervezés első kör, döntési pontok nyitva |
| [stilisztika_chat_prompt.md](stilisztika_chat_prompt.md) | Stilisztikai + CPS review prompt chat-AI-ba (ChatGPT, Claude.ai) — alternatíva a review_with_* scriptekhez | Használatra kész prompt |
| [deep_review_otletek_v1.md](deep_review_otletek_v1.md) | A 2026-07-13-i deep review be nem épített ötletei: review resume, glossary-check, pipeline.py, közös modul, költség-log | Fontolgatott opciók, javasolt sorrenddel. **#5 (költség-log) részben beépült:** a `gemini_quota.py` már hívásonként könyvel — a token/költség-dimenzió hiányzik belőle |

## Konvenciók

- **Verziózott fájlnevek** (`_v1.md`, `_v2.md`) — a régi verziókat NEM
  írjuk felül, hanem új verziót nyitunk; az evolúció így nyomon követhető.
  Új körnél a fájl tetején érdemes hivatkozni az előző verzióra.
- Ha új irány jön, új fájl + a fenti táblázathoz is bekerül egy sor.
- Ha egy proposal aktív fejlesztésbe megy át, **kikerül innen** és a fő
  `README.md`-ben kap helyet (változó: tervezésből → dokumentáció).
- A fájlnév mondjon valamit a tartalomról (pl. `translategemma_local`, nem
  csak `megoldas`); a verzió csak ott kell, ahol több kör is várható.
