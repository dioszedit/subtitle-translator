#!/usr/bin/env python3
"""
Fordítás ellenőrző script — Claude Code alapú review.
Az ÖSSZEFŰZÖTT hun.srt fájlt darabokra szedi, és minden darabot
Claude Code-dal átnézet, kifejezetten tükörfordítások és ragozási hibák
szempontjából. A talált hibákat egy riportba írja.

Használat:
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt"
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt" --chunk-size 100
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt" --model haiku
    python review_with_claude.py "output/Sorozat - S01E01.hun.srt" --model opus

Angol eredeti (kevesebb téves találat):
    Ha megtalálja a forrásnyelvi SRT-t, minden szekció mellé odaadja a
    modellnek a forrás eredetit is [FORRÁS] sorként — így a lektor a forráshoz
    tudja mérni a magyart, nem csak "gyanús" mondatokat keres.
    Automatikus keresés: a .hun.srt névből .eng.srt, az input/ mappában
    (ill. a hun fájl mellett). Kézi megadás / kikapcsolás:
        python review_with_claude.py "output/....hun.srt" --source "input/....eng.srt"
        python review_with_claude.py "output/....hun.srt" --no-source

    Csak egy konkrét chunk(tartomány) lefuttatása (pl. megszakítás utáni pótlás):
        python review_with_claude.py "output/...hun.srt" --start-chunk 9 --suffix _part2
        python review_with_claude.py "output/...hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

Modell:
    Alapértelmezett: sonnet
    --model haiku  : olcsóbb, gyorsabb
    --model opus   : alaposabb, drágább

Tartomány-paraméterek:
    --start-chunk N    Csak ettől a chunktól kezdje (1-alapú). Default: 1
    --end-chunk N      Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó
    --suffix _xxx      Riport fájlnév-utótag, hogy ne írja felül a meglévő
                       riportot. Pl. --suffix _part2 →
                       Sorozat - S01E01.hun_REVIEW_CLAUDE_part2.txt

Kimenet:
    output/Sorozat - S01E01.hun_REVIEW_CLAUDE.txt   (olvasható riport)
    output/Sorozat - S01E01.hun_REVIEW_CLAUDE.json  (apply_review.py bemenete)
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from glossary_categories import CATEGORIES
from translation_context import load_translation_context

DEFAULT_CHUNK_SIZE = 100  # Ennyi felirat kerül egy chunkba
TIMEOUT_PER_CHUNK = 600   # 10 perc chunkonként
SYS_PROMPT_PREFIX = ".review_claude_sys_prompt_"  # hash kerül utána


def parse_srt(filepath):
    """SRT blokkok beolvasása teljes szöveggel együtt (sorszám, időbélyeg, szöveg)."""
    content = Path(filepath).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            entries.append(block.strip())
    return entries


def parse_srt_by_index(filepath):
    """SRT beolvasása: {sorszám: (időbélyeg, szöveg egyben)} dict.

    A forrásnyelvi SRT-hez kell — az időbélyeg az igazítás-ellenőrzéshez,
    a szöveg a review kontextushoz.
    """
    content = Path(filepath).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries = {}
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            try:
                idx = int(lines[0].strip())
            except ValueError:
                continue
            entries[idx] = (lines[1].strip(),
                            " | ".join(l.strip() for l in lines[2:] if l.strip()))
    return entries


def check_source_alignment(entries, src_map):
    """Forrás/HU igazítás-ellenőrzés a párosítás előtt.

    Index-alapú a párosítás, ezért ha a magyar fájl újraszámozódott
    (pl. resegment --split), vagy a forrásban van plusz/hiányzó cue,
    MINDEN utána lévő szekció rossz forrás-sort kapna, és a lektor
    tömegesen jelentene hamis félrefordítást.
    Vissza: None ha rendben, különben rövid hibaleírás.
    """
    hun = {}
    for block in entries:
        lines = block.split("\n")
        if len(lines) >= 2:
            try:
                hun[int(lines[0].strip())] = lines[1].strip()
            except ValueError:
                continue
    if not hun or not src_map:
        return "nincs értékelhető szekció"
    if len(hun) != len(src_map):
        return f"cue-szám eltérés (magyar: {len(hun)}, forrás: {len(src_map)})"
    common = sorted(set(hun) & set(src_map))
    if len(common) < len(hun):
        return f"{len(hun) - len(common)} sorszámnak nincs forrás-párja"
    # Időbélyeg-szúrópróba: a pipeline 1:1 másolja az időbélyegeket, ezért
    # eltérés = elcsúszott/újraidőzített fájl.
    n = len(common)
    for idx in sorted({common[0], common[n // 4], common[n // 2],
                       common[3 * n // 4], common[-1]}):
        if hun[idx] != src_map[idx][0]:
            return (f"időbélyeg-eltérés a(z) #{idx} szekciónál "
                    f"(HU: {hun[idx]} / forrás: {src_map[idx][0]})")
    return None


def find_source_srt(hun_path: Path):
    """A forrásnyelvi SRT automatikus megkeresése a .hun.srt névből.

    A névcsere .eng.srt-t keres — ez az angol forrás konvenciója. Más
    forrásnyelvnél ezért nem talál semmit, és a hívónak kézzel kell
    megadnia a fájlt a --source kapcsolóval.
    """
    if ".hun." not in hun_path.name:
        return None
    src_name = hun_path.name.replace(".hun.", ".eng.")
    candidates = [
        Path("input") / src_name,
        hun_path.parent / src_name,
        hun_path.parent.parent / "input" / src_name,
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def attach_source(entries, src_map):
    """Minden magyar SRT-blokk után [FORRÁS] sor a forrásnyelvi eredetivel."""
    result = []
    matched = 0
    for block in entries:
        first = block.split("\n", 1)[0].strip()
        try:
            src = src_map.get(int(first))
        except ValueError:
            src = None
        if src and src[1]:
            result.append(f"{block}\n[FORRÁS] {src[1]}")
            matched += 1
        else:
            result.append(block)
    return result, matched


def chunk_entries(entries, chunk_size):
    """Entries felosztása chunkokra."""
    for i in range(0, len(entries), chunk_size):
        yield entries[i:i + chunk_size]


def load_claude_md() -> str:
    """Kompatibilitási név; a közös TRANSLATION.md-t tölti be."""
    return load_translation_context()


def load_glossary() -> str:
    if not os.path.isfile("glossary.json"):
        return ""
    with open("glossary.json", 'r', encoding='utf-8') as f:
        data = json.load(f)
    lines = []
    for category in CATEGORIES:
        for entry in data.get(category, []):
            en = entry.get("en", "")
            hu = entry.get("hu", "")
            ctx = entry.get("context", "")
            if en and hu:
                lines.append(f'  "{en}" = "{hu}"' + (f" ({ctx})" if ctx else ""))
    return "\n".join(lines) if lines else ""


def build_review_system_prompt(claude_md: str, glossary: str,
                               has_source: bool = False) -> str:
    parts = ["""=== SZEREP ===
Magyar fordítás lektor vagy. Angolból magyarra fordított SRT feliratokat
nézel át, és STÍLUS / NYELVTANI hibákat keresel.

=== AMIT KERESEL ===
1. Tükörfordítások (pl. "framed me" → "kereteztek be" helyett "tőrbe csaltak")
2. Helytelen igeragozás (pl. ikes igék, "tetszesz" helyett "tetszel")
3. Nemhez kötött kifejezések hibái (pl. "férjhez megy" férfiról; alapból
   semleges forma kell, csak ha BIZTOSAN ismert a beszélő/alany neme)
4. Természetellenes, angolos magyar nyelvezet
5. Rossz szórend, helytelen határozott/határozatlan ragozás

=== AMIT NE JELENTS ===
- Helyesírás apróságok (azokat a helyesírás-ellenőrző elkapja)
- Stilisztikai ízlésváltozatok, ha az adott fordítás is helyes
- HTML tagek, időbélyegek, sorszámok
- A szójegyzékben (lent) szereplő fordításokat NE javasold átírni —
  ezek a sorozat kötelező, jóváhagyott fordításai
- Karakterneveket NE javasold lefordítani (a szójegyzékben szerepelnek)"""]

    if has_source:
        parts.append("""=== FORRÁSNYELVI EREDETI ===
A legtöbb szekció után egy [FORRÁS] sor áll: ez a FORRÁSNYELVI EREDETI, amiből
a magyar fordítás készült. Ez a viszonyítási alap:
- Jelezd, ha a magyar mást mond, mint a forrás (félrefordítás,
  kimaradt/hozzáköltött tartalom, tagadás/idő/szám/személy eltérés).
- NE jelents hibát, ha a forrás igazolja a magyar megoldást —
  ami forrás nélkül furcsának tűnne, a forrás ismeretében gyakran helyes.
- A [FORRÁS] sor csak kontextus: az idézett "eredeti" szöveg MINDIG a magyar
  legyen, a [FORRÁS] sort ne idézd bele és ne javasold módosítani.""")

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — EZEK A FORDÍTÁSOK HELYESEK, NE JAVASOLJ MÁST! ===\n"
            + glossary.strip()
        )

    return "\n\n".join(parts)


def write_sys_prompt_file(content: str) -> str:
    """Sys prompt mentése tartalom-hash alapú névvel — két párhuzamos futás
    azonos tartalommal ugyanazt a fájlt használja, eltérővel külön fájlt
    (mint a translate_parallel.py). A régi (más hash-ű) fájlokat kitakarítja,
    hogy ne halmozódjanak a repo gyökerében."""
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    path = os.path.abspath(f"{SYS_PROMPT_PREFIX}{h}.txt")
    for stale in glob.glob(f"{SYS_PROMPT_PREFIX}*.txt"):
        if os.path.abspath(stale) != path:
            try:
                os.remove(stale)
            except OSError:
                pass
    if os.path.isfile(path):
        return path
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def review_chunk(chunk_text, chunk_num, total_chunks, sys_prompt_path,
                 model="sonnet", timeout=TIMEOUT_PER_CHUNK,
                 claude_bin="claude"):
    """Egy chunk átnézetése Claude Code-dal.

    Vissza: (stdout, None) siker esetén, (None, hibaüzenet) hibánál.
    A kimenet JSON tömb — a korábbi szabadszöveges formátum ("NINCS HIBA"
    jelzőszöveg) törékeny volt: ha a modell valós találatok UTÁN írta oda,
    minden találat elveszett.
    A prompt STDIN-en megy át, nem argumentumként: Windows-on a parancssor
    32 KB-os limitje nagy chunkoknál (főleg a [FORRÁS] sorokkal) elhasalna.
    """
    prompt = f"""Lektoráld az alábbi SRT felirat blokkot a system promptban
megadott szabályok szerint. A válaszod KIZÁRÓLAG egy JSON tömb legyen,
minden hibához egy objektum, pontosan ezekkel a kulcsokkal:

[{{"sorszam": 12, "eredeti": "az eredeti magyar szöveg", "hiba": "rövid leírás", "javaslat": "javított magyar változat"}}]

Ha nincs hiba ebben a chunkban, üres tömböt adj vissza: []
Semmilyen egyéb szöveget, magyarázatot vagy markdown-kerítést ne írj.

SRT BLOKK ({chunk_num}/{total_chunks}):
{chunk_text}
"""

    try:
        proc = subprocess.run(
            [claude_bin, "-p",
             "--append-system-prompt-file", sys_prompt_path,
             "--allowedTools", "",
             "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8"
        )
        if proc.returncode != 0:
            return None, f"[HIBA a chunkban {chunk_num}]: exit code {proc.returncode}\n{proc.stderr}"
        return proc.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return None, f"[TIMEOUT a chunkban {chunk_num} ({timeout // 60} perc)]"
    except FileNotFoundError:
        print("HIBA: A 'claude' parancs nem található!")
        sys.exit(1)


def parse_json_findings(result):
    """A modell válaszából kinyeri a hibalistát (JSON tömb).

    Vissza: lista (üres = nincs hiba), vagy None, ha a válasz nem
    értelmezhető — azt a hívó hibás chunkként kezeli, a nyers szöveg
    megőrzésével, hogy találat ne veszhessen el.
    """
    m = re.search(r"\[.*\]", result, re.S)
    if not m:
        # üres tömb szigorúan: "[]" akkor is, ha a regex nem fogja meg
        return [] if result.strip() in ("[]", "") else None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    findings = []
    for item in data:
        if not isinstance(item, dict) or "javaslat" not in item:
            continue
        try:
            sorszam = int(str(item.get("sorszam", "")).strip())
        except ValueError:
            continue
        findings.append({
            "sorszam": sorszam,
            "eredeti": str(item.get("eredeti", "")),
            "hiba": str(item.get("hiba", "")),
            "javaslat": str(item.get("javaslat", "")),
        })
    return findings


def format_findings(findings, chunk_num, total):
    """A JSON-találatokból szöveges riport-blokk (a régi formátumban)."""
    if not findings:
        return None
    lines = [f"--- Chunk {chunk_num}/{total} ---"]
    for err in findings:
        lines.append(f'#{err["sorszam"]}: "{err["eredeti"]}"')
        lines.append(f"  → HIBA: {err['hiba']}")
        lines.append(f"  → JAVASLAT: {err['javaslat']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Magyar fordítás review Claude-dal")
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Feliratok chunkonként (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--model", type=str, default="sonnet",
                        choices=["haiku", "sonnet", "opus"],
                        help="Claude modell (default: sonnet)")
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="Csak ettől a chunktól kezdje (1-alapú). Default: 1")
    parser.add_argument("--end-chunk", type=int, default=None,
                        help="Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó")
    parser.add_argument("--suffix", type=str, default="",
                        help="Riport fájl utótag, pl. '_part2' → _REVIEW_CLAUDE_part2.txt")
    parser.add_argument("--source", "--english", type=str, default=None,
                        help="Forrásnyelvi SRT (default: automatikus keresés "
                             "a .hun.srt névből az input/ mappában, .eng.srt-t "
                             "keresve). Bármilyen forrásnyelvhez használható — "
                             "nem angol forrásnál kötelező kézzel megadni. "
                             "A --english a kapcsoló régi neve.")
    parser.add_argument("--no-source", "--no-english", action="store_true",
                        help="Forrásnyelvi SRT kihagyása akkor is, ha megtalálható")
    args = parser.parse_args()

    if args.chunk_size < 1:
        print(f"HIBA: --chunk-size legalább 1 legyen (kaptam: {args.chunk_size})")
        sys.exit(1)
    if args.source and args.no_source:
        print("HIBA: --source és --no-source együtt nem használható.")
        sys.exit(1)

    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("HIBA: A 'claude' parancs nem található a PATH-on!")
        print("      Telepítés: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    entries = parse_srt(srt_path)
    print(f"Beolvasva: {len(entries)} felirat szekció")

    # Forrásnyelvi SRT párosítása (kevesebb téves találat)
    has_source = False
    if not args.no_source:
        src_path = Path(args.source) if args.source else find_source_srt(srt_path)
        if args.source and not src_path.is_file():
            print(f"HIBA: forrás SRT nem található: {src_path}")
            sys.exit(1)
        if src_path:
            src_map = parse_srt_by_index(src_path)
            problem = check_source_alignment(entries, src_map)
            if problem and not args.source:
                print(f"Forrás: {src_path} — KIHAGYVA, igazítási hiba: {problem}")
                print("  Elcsúszott párosítás tömeges hamis találatot adna.")
                print("  Kényszerítés (saját felelősségre): --source \"" + str(src_path) + "\"")
            else:
                if problem:
                    print(f"FIGYELEM: igazítási hiba ({problem}), de a --source "
                          "explicit, ezért párosítok. Az eredményt fenntartással kezeld!")
                entries, matched = attach_source(entries, src_map)
                has_source = matched > 0
                print(f"Forrás: {src_path} ({matched}/{len(entries)} szekció párosítva)")
        else:
            print("Forrás: nem található (review csak a magyar alapján).")
            print("  Nem angol forrásnál add meg kézzel: --source \"input/....srt\"")

    chunks = list(chunk_entries(entries, args.chunk_size))
    total_chunks = len(chunks)
    print(f"Chunkok: {total_chunks} db (chunkonként {args.chunk_size} felirat)")
    print(f"Modell: {args.model}")

    # Kontextus betöltése + system prompt fájl
    claude_md = load_claude_md()
    glossary = load_glossary()
    sys_prompt_content = build_review_system_prompt(claude_md, glossary, has_source)
    sys_prompt_path = write_sys_prompt_file(sys_prompt_content)
    print(f"System prompt: {len(sys_prompt_content)} char "
          f"(CLAUDE.md: {len(claude_md)} char, glossary: {len(glossary)} char)")

    # Chunk-tartomány
    start = max(1, args.start_chunk)
    end = args.end_chunk if args.end_chunk is not None else total_chunks
    end = min(end, total_chunks)
    if start > end:
        print(f"HIBA: --start-chunk ({start}) nagyobb mint --end-chunk ({end}).")
        sys.exit(1)
    if start > 1 or end < total_chunks:
        print(f"Tartomány: {start}–{end}")
    print()

    # Output riport fájl
    report_path = srt_path.with_name(srt_path.stem + f"_REVIEW_CLAUDE{args.suffix}.txt")
    json_path = srt_path.with_name(srt_path.stem + f"_REVIEW_CLAUDE{args.suffix}.json")

    # Felülírás-védelem: rész-tartomány futtatása suffix nélkül letörölné
    # a korábbi teljes riportot (pl. chunk 1-8 találatai vesznének el).
    if (start > 1 or end < total_chunks) and not args.suffix and report_path.exists():
        print(f"HIBA: Létező riport ({report_path.name}) + rész-tartomány futtatás.")
        print("      A futás felülírná a teljes korábbi riportot!")
        print("      Adj meg --suffix _part2 (vagy hasonló) utótagot.")
        sys.exit(1)

    all_findings = []
    json_findings = []
    error_chunks = []

    for i in range(start, end + 1):
        chunk = chunks[i - 1]
        chunk_text = "\n\n".join(chunk)
        print(f"[{i}/{total_chunks}] Ellenőrzés folyamatban...")

        result, err_msg = review_chunk(chunk_text, i, total_chunks,
                                       sys_prompt_path, args.model,
                                       claude_bin=claude_bin)

        if err_msg:
            error_chunks.append(f"--- Chunk {i}/{total_chunks} ---\n{err_msg}\n")
            print(f"  {err_msg.splitlines()[0]}")
            continue

        findings = parse_json_findings(result)
        if findings is None:
            # Nem értelmezhető válasz — a nyers szöveget megőrizzük, hogy
            # esetleges találat ne veszhessen el.
            error_chunks.append(
                f"--- Chunk {i}/{total_chunks} ---\n"
                f"[Nem JSON válasz — nyers kimenet megőrizve:]\n{result}\n")
            print("  Nem JSON válasz — nyers kimenet a riport hibás-chunk részében")
            continue

        block = format_findings(findings, i, total_chunks)
        if block:
            all_findings.append(block)
        for err in findings:
            json_findings.append({**err, "chunk": i})

    # Riport mentése
    sections = []
    if all_findings:
        sections.append("\n".join(all_findings))
    if error_chunks:
        sections.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(error_chunks))

    if sections:
        report_content = (
            f"Review riport (Claude): {srt_path.name}\n"
            f"Modell: {args.model}\n"
            f"{'=' * 60}\n\n"
            + "\n\n".join(sections)
        )
        report_path.write_text(report_content, encoding="utf-8")
        print(f"\nRiport mentve: {report_path}")
        print(f"Találatok: {len(all_findings)} chunkban, hibás chunkok: {len(error_chunks)}")
    else:
        print("\nNincs hiba egyik chunkban sem!")

    # Gépi feldolgozáshoz (apply_review.py): JSON riport is
    if json_findings:
        json_path.write_text(json.dumps({
            "source": srt_path.name,
            "reviewer": "claude",
            "model": args.model,
            "findings": json_findings,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON riport mentve: {json_path}")


if __name__ == "__main__":
    main()
