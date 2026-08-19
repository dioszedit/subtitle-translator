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
| [deep_review_otletek_v2.md](deep_review_otletek_v2.md) | A még nyitott fejlesztési ötletek (review resume, glossary-check, `subtr run` orchestrator, költség-log, GUI-újratervezés) a subtr-es világra igazítva | Fontolgatott opciók, javasolt sorrenddel |
| [translategemma_local.md](translategemma_local.md) | Lokális fordító Mac mini-n (ollama + `translategemma:12b`) — alternatíva a felhős providerek mellett | Research jegyzet. Ha megvalósul, a természetes alakja egy `subtr/providers/ollama.py` adapter |
| [stilisztika_chat_prompt.md](stilisztika_chat_prompt.md) | Stilisztikai + CPS review prompt chat-AI-ba (ChatGPT, Claude.ai) — alternatíva a `subtr.py review` parancshoz | Használatra kész prompt |

## Archívum

Az [archive/](archive/) mappában a lezárt vagy elavult körök vannak —
történeti dokumentumok, nem frissülnek:

| Fájl | Miért került ide |
|------|------|
| [archive/deep_review_otletek_v1.md](archive/deep_review_otletek_v1.md) | A #1 (közös modul) megvalósult a `subtr/` csomag-refaktorral, a #4 (egyparancsos pipeline) részben a `subtr.py` CLI-vel; a nyitott tételek a v2-ben élnek tovább |
| [archive/desktop_gui_v1.md](archive/desktop_gui_v1.md) | A törölt gyökér-scriptek subprocess-hívására épült; egy jövőbeli GUI-nak a `subtr.tasks` API az alapja (lásd v2 #5) |

## Konvenciók

- **Verziózott fájlnevek** (`_v1.md`, `_v2.md`) — a régi verziókat NEM
  írjuk felül, hanem új verziót nyitunk; az evolúció így nyomon követhető.
  Új körnél a fájl tetején érdemes hivatkozni az előző verzióra.
- Ha új irány jön, új fájl + a fenti táblázathoz is bekerül egy sor.
- Ha egy proposal megvalósult vagy az alapja elavult, az **archive/**
  mappába kerül — ott marad történeti dokumentumként, nem frissül.
- Ha egy proposal aktív fejlesztésbe megy át, **kikerül innen** és a fő
  `README.md`-ben kap helyet (változó: tervezésből → dokumentáció).
- A fájlnév mondjon valamit a tartalomról (pl. `translategemma_local`, nem
  csak `megoldas`); a verzió csak ott kell, ahol több kör is várható.
