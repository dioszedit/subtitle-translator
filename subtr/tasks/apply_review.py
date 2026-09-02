#!/usr/bin/env python3
"""
subtr.py apply — Review riportok összefésülése és interaktív alkalmazása.

A `subtr.py review` riportjait (bármelyik provider) beolvassa, szekciószám szerint összefésüli és deduplikálja, majd találatonként
megkérdezi, alkalmazza-e a javaslatot a magyar SRT-re. Az eredetiről .bak
mentés készül az első íráskor.

Használat:
    python subtr.py apply "output/Sorozat - S01E01.hun.srt"
        → automatikusan megkeresi a _REVIEW_CLAUDE / _REVIEW_GEMINI /
          _REVIEW_CODEX / _REVIEW_GROK riportokat (.json/.txt) a fájl mellett

    python subtr.py apply "output/....hun.srt" riport1.json riport2.txt
        → csak a megadott riportokat használja

    python subtr.py apply "output/....hun.srt" --dry-run
        → csak listázza az összefésült találatokat, nem módosít

Interaktív parancsok találatonként:
    y      javaslat alkalmazása (több variánsnál az 1. — számmal választhatsz)
    1..9   az adott sorszámú variáns alkalmazása
    e      kézi szerkesztés (a | jel sortörést jelent)
    n      kihagyás
    q      kilépés — az addig alkalmazott javítások mentésre kerülnek

A .txt riportok formátumát is érti (régebbi futások), de a .json a kanonikus.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from subtr.srt import parse_blocks_with_index as parse_srt_blocks

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

TXT_FINDING_RE = re.compile(
    r'^#(\d+):\s*"(.*)"\s*\n'
    r'\s*→ HIBA:\s*(.*)\s*\n'
    r'\s*→ JAVASLAT:\s*(.*)\s*$',
    re.MULTILINE)


def load_json_report(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    reviewer = data.get("reviewer", Path(path).stem)
    out = []
    for f in data.get("findings", []):
        try:
            sorszam = int(f["sorszam"])
        except (KeyError, ValueError, TypeError):
            continue
        out.append({"sorszam": sorszam, "eredeti": f.get("eredeti", ""),
                    "hiba": f.get("hiba", ""), "javaslat": f.get("javaslat", ""),
                    "reviewer": reviewer})
    return out


def load_txt_report(path):
    content = Path(path).read_text(encoding="utf-8")
    name = Path(path).stem
    reviewer = ("claude" if "CLAUDE" in name.upper()
                else "gemini" if "GEMINI" in name.upper()
                else "codex" if "CODEX" in name.upper()
                else "grok" if "GROK" in name.upper() else name)
    out = []
    for m in TXT_FINDING_RE.finditer(content):
        out.append({"sorszam": int(m.group(1)), "eredeti": m.group(2),
                    "hiba": m.group(3), "javaslat": m.group(4),
                    "reviewer": reviewer})
    return out


def find_reports(srt_path: Path):
    """A hun.srt mellett lévő review riportok automatikus megkeresése.
    Ha ugyanahhoz a riporthoz .json és .txt is van, csak a .json-t használjuk."""
    stem = srt_path.stem
    found = []
    for pattern in (f"{stem}_REVIEW_CLAUDE*", f"{stem}_REVIEW_GEMINI*",
                    f"{stem}_REVIEW_CODEX*", f"{stem}_REVIEW_GROK*"):
        for p in sorted(srt_path.parent.glob(pattern)):
            if p.suffix not in (".json", ".txt"):
                continue
            if p.suffix == ".txt" and p.with_suffix(".json").exists():
                continue
            found.append(p)
    return found


def merge_findings(findings):
    """Szekciószám szerint csoportosít; az azonos javaslatokat összevonja
    (a reviewerek nevét megőrizve), az eltérőket variánsként listázza."""
    by_num = {}
    for f in findings:
        variants = by_num.setdefault(f["sorszam"], [])
        norm = " ".join(f["javaslat"].split())
        for v in variants:
            if " ".join(v["javaslat"].split()) == norm:
                if f["reviewer"] not in v["reviewers"]:
                    v["reviewers"].append(f["reviewer"])
                break
        else:
            variants.append({"eredeti": f["eredeti"], "hiba": f["hiba"],
                             "javaslat": f["javaslat"],
                             "reviewers": [f["reviewer"]]})
    return dict(sorted(by_num.items()))


def block_text(block):
    """Egy SRT-blokk szövegrésze (fejléc nélkül)."""
    lines = block.split("\n")
    return "\n".join(lines[2:]) if len(lines) >= 3 else ""


def apply_to_block(block, new_text):
    """A blokk szövegének cseréje, fejléc (sorszám + időbélyeg) érintetlen."""
    lines = block.split("\n")
    return "\n".join(lines[:2] + new_text.split("\n"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Review riportok interaktív alkalmazása a magyar SRT-re")
    parser.add_argument("srt_file", help="A magyar (hun.srt) fájl")
    parser.add_argument("reports", nargs="*",
                        help="Riport fájlok (.json/.txt). Üresen: automatikus keresés.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Csak listázás, nem módosít semmit")
    args = parser.parse_args(argv)

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    report_paths = ([Path(r) for r in args.reports] if args.reports
                    else find_reports(srt_path))
    if not report_paths:
        print("Nem találtam review riportot a fájl mellett.")
        print(f"  Keresett minták: {srt_path.stem}_REVIEW_CLAUDE* / _REVIEW_GEMINI* / _REVIEW_CODEX* / _REVIEW_GROK* (.json/.txt)")
        sys.exit(1)

    findings = []
    for rp in report_paths:
        if not rp.exists():
            print(f"HIBA: Riport nem található: {rp}")
            sys.exit(1)
        loaded = (load_json_report(rp) if rp.suffix == ".json"
                  else load_txt_report(rp))
        print(f"Riport: {rp.name} — {len(loaded)} találat")
        findings.extend(loaded)

    merged = merge_findings(findings)
    total_variants = sum(len(v) for v in merged.values())
    print(f"Összefésülve: {len(merged)} szekció, {total_variants} javaslat "
          f"({len(findings) - total_variants} duplikátum összevonva)\n")

    if not merged:
        print("Nincs alkalmazható találat.")
        return

    blocks, index = parse_srt_blocks(srt_path)

    if args.dry_run:
        for num, variants in merged.items():
            current = block_text(blocks[index[num]]) if num in index else "(nincs ilyen szekció!)"
            print(f"#{num}: {current!r}")
            for k, v in enumerate(variants, 1):
                who = "+".join(v["reviewers"])
                print(f"  {k}. [{who}] {v['hiba']}")
                print(f"     → {v['javaslat']!r}")
        print("\n--dry-run: nem módosítottam semmit.")
        return

    applied = skipped = 0
    backed_up = False
    quit_requested = False

    for num, variants in merged.items():
        if quit_requested:
            break
        if num not in index:
            print(f"#{num}: NINCS ilyen szekció a fájlban — kihagyva "
                  f"(a riport másik fájlhoz készült?)\n")
            skipped += 1
            continue
        bi = index[num]
        current = block_text(blocks[bi])

        print("=" * 60)
        print(f"#{num} — jelenlegi szöveg:")
        print(f"  {current}")
        for k, v in enumerate(variants, 1):
            who = "+".join(v["reviewers"])
            print(f"  {k}. javaslat [{who}] — {v['hiba']}")
            print(f"     {v['javaslat']}")
        drift = all(" ".join(v["eredeti"].split()) != " ".join(current.split())
                    for v in variants if v["eredeti"])
        if drift and any(v["eredeti"] for v in variants):
            print("  FIGYELEM: a szöveg időközben változott (már javítva?)")

        while True:
            choice = input(f"Alkalmazod? [y/1-{len(variants)}/e/n/q] ").strip().lower()
            if choice in ("y", "i"):
                choice = "1"
            if choice.isdigit() and 1 <= int(choice) <= len(variants):
                new_text = variants[int(choice) - 1]["javaslat"]
            elif choice == "e":
                raw = input("Új szöveg (| = sortörés): ").strip()
                if not raw:
                    continue
                new_text = raw.replace("|", "\n")
            elif choice == "n":
                skipped += 1
                break
            elif choice == "q":
                quit_requested = True
                break
            else:
                continue
            if choice not in ("n", "q"):
                if not backed_up:
                    shutil.copy2(srt_path, srt_path.with_suffix(srt_path.suffix + ".bak"))
                    backed_up = True
                blocks[bi] = apply_to_block(blocks[bi], new_text)
                applied += 1
            break
        print()

    if applied:
        srt_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        print(f"Mentve: {srt_path} (backup: {srt_path.name}.bak)")
    print(f"Alkalmazva: {applied}, kihagyva: {skipped}, összesen: {len(merged)} szekció")

