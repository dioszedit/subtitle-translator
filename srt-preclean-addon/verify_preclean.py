#!/usr/bin/env python3
"""
Fordítás UTÁNI ellenőrző — a lefordított (összefűzött) SRT-t veti össze a
tisztított forrással, és jelzi a tipikus hibákat.

(Korábbi neve verify_srt.py volt — átnevezve, mert a projekt gyökerében
lévő, MÁSIK verify_srt.py-vel azonos néven és argumentum-formával futott,
és rossz mappából indítva észrevétlenül a másik ellenőrzés futott le.)

Ellenőrzi:
  1. Ugyanannyi felirat van-e a fordításban, mint a forrásban.
  2. A sorszám + időbélyeg 1:1 egyezik-e (a fordításnál SOHA nem szabad
     fejből generálni — mindig a forrásból kell másolni).
  3. A sorszámozás 1..N-ig folytonos-e.
  4. FIGYELMEZTETÉSKÉNT: maradt-e szögletes/kerek zárójeles sor a
     fordításban (a --keep mintát és a címkártyát kivéve). Ez NEM hiba:
     a CLAUDE.md szerint a [megjegyzések] lefordítva megmaradnak, és a
     sorozatcím-kártya kötelezően két zárójeles sor.

Használat:
  python verify_preclean.py <forrás.clean.srt> <kész_fordítás.srt>
  python verify_preclean.py forrás.clean.srt kesz.hu.srt --keep "DOCTOR ON THE EDGE"

Kilépési kód: 0 ha minden rendben, 1 ha bármelyik ellenőrzés hibát talált
(a zárójel-figyelmeztetés nem számít hibának).
"""

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def parse(path: Path):
    subs = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8-sig").strip()):
        lines = block.split("\n")
        if len(lines) < 2:
            continue
        ts_idx = 1 if "-->" in lines[1] else (0 if lines and "-->" in lines[0] else None)
        if ts_idx is None:
            continue
        idx = lines[ts_idx - 1].strip() if ts_idx == 1 else ""
        subs.append((idx, lines[ts_idx].strip(), "\n".join(lines[ts_idx + 1:])))
    return subs


def main():
    ap = argparse.ArgumentParser(description="SRT fordítás-ellenőrző")
    ap.add_argument("source", help="Tisztított forrás SRT (.clean.srt)")
    ap.add_argument("translation", help="Kész, összefűzött fordítás SRT")
    ap.add_argument("--keep", action="append", default=[], help="Zárójel-ellenőrzésnél kihagyandó minta (regex)")
    args = ap.parse_args()

    src = parse(Path(args.source))
    tr = parse(Path(args.translation))
    keep_res = [re.compile(k) for k in args.keep]
    problems = 0

    print(f"Forrás: {len(src)} felirat | Fordítás: {len(tr)} felirat")
    if len(src) != len(tr):
        print(f"  ✗ ELTÉRŐ feliratszám ({len(src)} vs {len(tr)})")
        problems += 1
    else:
        print("  ✓ Azonos feliratszám")

    ts_err = 0
    for i, (s, t) in enumerate(zip(src, tr), 1):
        if s[1] != t[1]:
            if ts_err < 10:
                print(f"  ✗ Időbélyeg eltérés #{i}: forrás [{s[1]}] vs fordítás [{t[1]}]")
            ts_err += 1
    if ts_err:
        print(f"  ✗ Összes időbélyeg-eltérés: {ts_err}")
        problems += 1
    else:
        print("  ✓ Időbélyegek 1:1 egyeznek")

    seq_err = [i for i, (idx, _, _) in enumerate(tr, 1) if idx and idx != str(i)]
    if seq_err:
        print(f"  ✗ Nem folytonos sorszámozás {len(seq_err)} helyen (első: #{seq_err[0]})")
        problems += 1
    else:
        print("  ✓ Sorszámozás folytonos (1..N)")

    # Zárójeles sorok — csak FIGYELMEZTETÉS, nem hiba: a CLAUDE.md szerint a
    # [megjegyzések] lefordítva megmaradnak, és a címkártya (két, teljes
    # egészében zárójeles sor) kötelező formátum. Átnézésre listázzuk.
    brk = 0
    for idx, _, body in tr:
        lines = [l for l in body.split("\n") if l.strip()]
        # címkártya: minden sor teljes egészében [zárójeles] → szándékos
        if len(lines) >= 2 and all(re.fullmatch(r"\[[^\]]*\]", l.strip()) for l in lines):
            continue
        for line in lines:
            if any(kr.search(line) for kr in keep_res):
                continue
            if re.search(r"\[[^\]]*\]|\([^)]*\)", line):
                if brk < 10:
                    print(f"  ⚠ Zárójeles sor #{idx}: {line}")
                brk += 1
    if brk:
        print(f"  ⚠ Összesen {brk} zárójeles sor — nézd át, szándékosak-e")
        print(f"    (A [megjegyzés]-fordítások és a címkártya jogosak, nem hibák.)")
    else:
        print("  ✓ Nincs zárójeles sor")

    print("\n" + ("MINDEN RENDBEN ✓" if problems == 0 else f"{problems} HIBACSOPORT — javítás szükséges ✗"))
    if problems == 0 and brk:
        print(f"({brk} zárójel-figyelmeztetés — nem hiba)")
    sys.exit(0 if problems == 0 else 1)


if __name__ == "__main__":
    main()
