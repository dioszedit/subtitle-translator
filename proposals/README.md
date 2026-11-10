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
| [deep_review_otletek_v3.md](deep_review_otletek_v3.md) | A még nyitott fejlesztési ötletek: review folytatása megszakadás után, szójegyzék-ellenőrzés a `verify`-ban, költség-kimutatás, hiányzó alap-szótárak (`ja-common`, `ko-sageuk`), GUI-újratervezés | Fontolgatott opciók, javasolt sorrenddel |

## Archívum

Az [archive/](archive/) mappában a lezárt vagy elavult körök vannak —
történeti dokumentumok, nem frissülnek:

| Fájl | Miért került ide |
|------|------|
| [archive/deep_review_otletek_v1.md](archive/deep_review_otletek_v1.md) | A #1 (közös modul) megvalósult a `subtr/` csomag-refaktorral, a #4 (egyparancsos pipeline) részben a `subtr.py` CLI-vel; a nyitott tételek a v2-ben élnek tovább |
| [archive/desktop_gui_v1.md](archive/desktop_gui_v1.md) | A törölt gyökér-scriptek subprocess-hívására épült; egy jövőbeli GUI-nak a `subtr.tasks` API az alapja (lásd v2 #5) |
| [archive/deep_review_otletek_v2.md](archive/deep_review_otletek_v2.md) | A nyitott tételek a v3-ban élnek tovább; a `subtr run` végigvivő parancs kikerült (az `epizod` skill váltotta ki) |
| [archive/alap_szotarak.md](archive/alap_szotarak.md) | Megvalósult (2026-10): `glossaries/`, futáskori összefésülés, `subtr.py bases`; a terv és a magyar forráskutatás. A nyitott alapok (`ja-common`, `ko-sageuk`) a v3-ban |
| [archive/antigravity_provider.md](archive/antigravity_provider.md) | Megvalósult: `--provider antigravity` (`subtr/providers/antigravity_cli.py`); a terv és a felderítés eredményei |

## Konvenciók

- **Verziózott fájlnevek** (`_v1.md`, `_v2.md`) — a régi verziókat NEM
  írjuk felül, hanem új verziót nyitunk; az evolúció így nyomon követhető.
  Új körnél a fájl tetején érdemes hivatkozni az előző verzióra.
- Ha új irány jön, új fájl + a fenti táblázathoz is bekerül egy sor.
- Ha egy proposal megvalósult vagy az alapja elavult, az **archive/**
  mappába kerül — ott marad történeti dokumentumként, nem frissül.
- Ha egy proposal aktív fejlesztésbe megy át, **kikerül innen** és a fő
  `README.md`-ben kap helyet (változó: tervezésből → dokumentáció).
- A fájlnév mondjon valamit a tartalomról (pl. `antigravity_provider`, nem
  csak `megoldas`); a verzió csak ott kell, ahol több kör is várható.
