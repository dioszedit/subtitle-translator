#!/usr/bin/env python3
"""
Fordítás UTÁNI SDH-tisztító — a kész magyar feliratból eltávolítja a
lefordított beszélőcímkéket és hangjegyzeteket ([Anna], [sóhajt],
[nyílik az ajtó]).

Miért utólag: a fordító így látja, ki beszél (nem, tegezés/magázás), és a
verify / review / triage / glossary végig 1:1-ben fut az eredeti forrással.
A bemenetet SOHA nem írja felül: a tisztított változat külön fájlba megy
(alapból <alap>.hun.clean.srt ugyanabba a mappába), így az 1:1-es példány
megmarad, és a review / triage később is újrafuttatható rajta.

CSAK SDH-forrásból készült fordításon futtasd! Nem SDH forrásnál a [...]
képi szöveg (helyszín, hír, SMS), azt meg kell tartani. Védelem: ha a
fájlban alig van beszélőcímke vagy sor végi hangjegyzet, a szkript nem ír
semmit (felülbírálás: --force).

Mit csinál:
  1. Minden [...] és (...) szegmenst töröl a szövegsorokból, KIVÉVE a
     sorozatcím-kártyát (a TRANSLATION.local.md Title / Hungarian title
     mezőiből és a glossary.json meta.series-éből ismeri fel) és a --keep
     mintás sorokat.
  2. A csak jegyzetből álló sort elhagyja; ha egy kétsoros párbeszédből így
     egy sor marad, a párbeszéd-kötőjelet is leveszi.
  3. A teljesen üressé vált feliratot eldobja, és 1..N-ig újraszámoz.
     Az időbélyegek változatlanok.

Használat:
  python postclean_srt.py "output/Sorozat - S01E01.hun.srt"             (-> output/Sorozat - S01E01.hun.clean.srt)
  python postclean_srt.py kesz.hun.srt -o tiszta.hun.srt
  python postclean_srt.py kesz.hun.srt --keep "^\\[Szöul"                (többször megadható)
  python postclean_srt.py kesz.hun.srt --dry-run                         (csak kiírja, mit tenne)

Kilépési kód: 0 siker, 1 hiba (hiányzó fájl, nem SDH-nak tűnő bemenet,
a kimenet a bemenettel azonos).
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

NOTE_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")
DASH_RE = re.compile(r"^(\s*[-–—]\s*)")
# Formázó tag, ami a jegyzet törlése után üresen maradhat (<i></i>, {\an8})
EMPTY_FMT_RE = re.compile(r"^(?:</?[ibu]>|\{\\an\d\}|\s)*$", re.IGNORECASE)
FMT_PREFIX = r"(?:\s*[-–—])?\s*(?:\{\\an\d\})?(?:<[ibu]>)?\s*"
# Beszélőcímke: a sor elején álló jegyzet, amit valódi szöveg követ ([Anna] Szia!)
LEAD_LABEL_RE = re.compile(rf"^{FMT_PREFIX}\[[^\]]+\]\s*(?:</?[ibu]>)?\s*[^\s\[\]<]", re.IGNORECASE)
# Sor végi hangjegyzet valódi szöveg után (Hadd... [sóhajt])
TRAIL_NOTE_RE = re.compile(r"[^\s\[\]][^\[\]]*\[[^\]]+\]\s*(?:</[ibu]>)?\s*$", re.IGNORECASE)
# SDH-nak akkor számít, ha a feliratok legalább ekkora hányadában (és legalább
# ennyi helyen) van beszélőcímke vagy sor végi jegyzet. Nem SDH forrásnál a
# zárójel képi szöveg, az jellemzően egész sort foglal el.
SDH_MIN_COUNT = 5
SDH_MIN_RATIO = 0.02


def series_titles(project_dir: Path) -> set[str]:
    """A sorozatcím-kártya lehetséges szövegei (kisbetűsítve)."""
    titles = set()
    local = project_dir / "TRANSLATION.local.md"
    if local.exists():
        for line in local.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"\s*(?:Title|Hungarian title)\s*:\s*(.+)", line, re.IGNORECASE)
            if not m or "TODO" in m.group(1):
                continue
            # "Spring Breeze (2026) (봄바람)" -> a latin és a natív cím is
            value = m.group(1)
            parts = [re.sub(r"\s*\([^)]*\)", "", value)] + re.findall(r"\(([^)]*)\)", value)
            for t in parts:
                t = t.strip()
                if t and not t.startswith("[") and not re.fullmatch(r"\d{4}", t):
                    titles.add(t.casefold())
    gl = project_dir / "glossary.json"
    if gl.exists():
        try:
            series = json.loads(gl.read_text(encoding="utf-8-sig")).get("meta", {}).get("series")
            if series:
                titles.add(series.strip().casefold())
        except (json.JSONDecodeError, AttributeError):
            pass
    return titles


def is_kept(line: str, titles: set[str], keep_res) -> bool:
    if any(kr.search(line) for kr in keep_res):
        return True
    m = re.fullmatch(r"\s*(?:\{\\an\d\})?(?:<i>)?\[([^\]]*)\](?:</i>)?\s*", line)
    return bool(m and m.group(1).strip().casefold() in titles)


def clean_line(line: str) -> str:
    m = DASH_RE.match(line)
    dash = m.group(1) if m else ""
    rest = line[len(dash):]
    rest = NOTE_RE.sub("", rest)
    rest = re.sub(r"(?<=\S) {2,}", " ", rest).strip()
    rest = re.sub(r"^((?:\{\\an\d\})?<[ibu]>)\s+", r"\1", rest)
    rest = re.sub(r"\s+(</[ibu]>)$", r"\1", rest)
    if EMPTY_FMT_RE.match(rest):
        return ""
    return dash + rest


def parse_srt(txt: str):
    """SRT -> [(timestamp, [szövegsorok]), ...] — a sorszámot eldobjuk."""
    out = []
    for block in re.split(r"\n\s*\n", txt.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        first = 1 if len(lines) > 1 and "-->" in lines[1] else (0 if "-->" in lines[0] else None)
        if first is None:
            continue
        out.append((lines[first], lines[first + 1:]))
    return out


def sdh_evidence(subs) -> int:
    """Hány feliratban van beszélőcímke vagy sor végi hangjegyzet."""
    return sum(
        1 for _, text in subs
        if any(LEAD_LABEL_RE.search(ln) or TRAIL_NOTE_RE.search(ln) for ln in text))


def looks_like_sdh(subs) -> bool:
    n = sdh_evidence(subs)
    return n >= SDH_MIN_COUNT and n >= SDH_MIN_RATIO * len(subs)


def postclean(subs, titles, keep_res):
    kept, dropped, changed = [], [], 0
    for ts, text in subs:
        new, removed = [], False
        for ln in text:
            if is_kept(ln, titles, keep_res):
                new.append(ln)
                continue
            c = clean_line(ln)
            if not c.strip(" -–—"):
                removed = True
                continue
            if c != ln:
                changed += 1
            new.append(c)
        if removed and len(new) == 1:
            new = [DASH_RE.sub("", new[0])]
        if not new:
            dropped.append((ts, text))
            continue
        kept.append((ts, new))
    return kept, dropped, changed


def default_output(src: Path) -> Path:
    """X.hun.srt -> X.hun.clean.srt (a preclean .eng.clean.srt-jének párja)."""
    return src.with_name(src.stem + ".clean" + src.suffix)


def render(kept) -> str:
    return "\n\n".join(f"{i}\n{ts}\n" + "\n".join(t) for i, (ts, t) in enumerate(kept, 1)) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fordítás utáni SDH-tisztító (beszélőcímkék, hangjegyzetek)")
    ap.add_argument("srt_file", help="Kész magyar SRT (pl. output/X.hun.srt)")
    ap.add_argument("-o", "--output", help="Kimeneti fájl (default: <alap>.hun.clean.srt a bemenet mellett)")
    ap.add_argument("--keep", action="append", default=[], metavar="MINTA",
                    help="Soha ne tisztítsa az ezt (regex) tartalmazó sort. Többször megadható.")
    ap.add_argument("--project-dir", default=".", help="A TRANSLATION.local.md / glossary.json mappája (default: .)")
    ap.add_argument("--force", action="store_true",
                    help="Akkor is fusson, ha a bemenet nem tűnik SDH-forrásból készültnek")
    ap.add_argument("--dry-run", action="store_true", help="Csak kiírja, mit tenne")
    args = ap.parse_args(argv)

    src = Path(args.srt_file)
    if not src.exists():
        print(f"HIBA: nincs ilyen fájl: {src}")
        return 1
    out = Path(args.output) if args.output else default_output(src)
    if out.resolve() == src.resolve():
        print("HIBA: a kimenet nem lehet azonos a bemenettel — az 1:1-es példány kell a review-hoz.")
        return 1

    subs = parse_srt(src.read_text(encoding="utf-8-sig"))
    evidence = sdh_evidence(subs)
    if not looks_like_sdh(subs) and not args.force:
        print(f"HIBA: a fájl nem tűnik SDH-forrásból készültnek (beszélőcímke / sor végi "
              f"jegyzet {evidence} feliratban a {len(subs)}-ből). Nem SDH forrásnál a [...] "
              f"képi szöveg, azt nem szabad törölni. Ha mégis biztos vagy benne: --force")
        return 1

    titles = series_titles(Path(args.project_dir))
    keep_res = [re.compile(k) for k in args.keep]
    kept, dropped, changed = postclean(subs, titles, keep_res)

    print(f"Sorozatcím-kártya (megtartva): {', '.join(sorted(titles)) or '—'}")
    print(f"Feliratok: {len(subs)} -> {len(kept)} (eldobott csak-jegyzet: {len(dropped)}), módosított sor: {changed}")
    for ts, text in dropped:
        print(f"  eldobva  {ts.split(' --> ')[0]}  {' / '.join(text)}")
    rounds = sorted({m.group(0) for _, t in subs for ln in t for m in re.finditer(r"\([^)]*\)", ln)})
    if rounds:
        print("Kerek zárójeles szegmensek (ezek is törlődnek — ellenőrizd, jegyzetek-e):")
        for r in rounds:
            print(f"  {r}")
    leftover = [(i, ln) for i, (_, t) in enumerate(kept, 1) for ln in t if "[" in ln or "(" in ln]
    if leftover:
        print("Megmaradt zárójeles sorok (címkártya / --keep):")
        for i, ln in leftover:
            print(f"  #{i}: {ln}")
    if args.dry_run:
        return 0

    out.write_text(render(kept), encoding="utf-8")
    print(f"Kiírva: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
