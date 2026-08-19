"""
translate_parallel.py — Párhuzamos fordítás Claude Code-dal (optimalizált, multi-process safe)

OPTIMALIZÁCIÓK:
- Glossary + szabályok + CLAUDE.md a SYSTEM PROMPTBA (--append-system-prompt-file)
  → Claude Code prompt cache → 8 párhuzamos agent közül csak az 1. fizet teljes árat.
- Modell választható (--model), default: sonnet.
- Per-blokk prompt minimális (csak fájl útvonalak).
- --max-turns korlát (default: 20) → nincs futó-galopp.
- Tool lista szűkítve Read,Write-ra.
- Szekciószám ellenőrzés Python oldalon, nem foglal agent-fordulót.
  Eltérés esetén a hibás output törlődik, így a következő futás újrafordítja.

MULTI-PROCESS SAFE:
- A system prompt fájl neve a tartalom SHA256 hash-ét tartalmazza.
- Két párhuzamos Python process azonos tartalommal → ugyanazt a fájlt használja
  (atomi rename-mel írva, nincs race condition).
- Eltérő tartalom → eltérő fájl, nincs felülírás.
- A fájlt NEM töröljük futás végén (másik process használhatja);
  csak az 1 napnál régebbieket takarítjuk startup-kor.

Használat:
    python translate_parallel.py blocks/Sorozat_S01E01_eng
    python translate_parallel.py blocks/Sorozat_S01E01_eng --agents 4
    python translate_parallel.py blocks/Sorozat_S01E01_eng --agents 1 --block 003
    python translate_parallel.py blocks/Sorozat_S01E01_eng --model haiku
"""

import os
import sys
import glob
import json
import hashlib
import shutil
import subprocess
import argparse
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from glossary_categories import CATEGORIES
from translation_context import load_translation_context

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

SYS_PROMPT_PREFIX = ".translate_sys_prompt_"
SYS_PROMPT_MAX_AGE_DAYS = 1  # ennél régebbi sys prompt fájlokat takarítjuk


def get_all_blocks(blocks_dir: str) -> list[str]:
    pattern = os.path.join(blocks_dir, "*_block_*.srt")
    all_files = sorted(glob.glob(pattern))
    return [f for f in all_files if not f.endswith("_HUN.srt")]


def get_pending_blocks(blocks_dir: str) -> list[str]:
    pending = []
    for f in get_all_blocks(blocks_dir):
        hun_file = f[:-len(".srt")] + "_HUN.srt"
        if not os.path.isfile(hun_file):
            pending.append(f)
    return pending


def count_sections(filepath: str) -> int:
    """Strukturális számlálás: csak az a csupa-számjegy sor számít szekciónak,
    amit időbélyeg-sor követ. Így a csak számot tartalmazó felirat-SZÖVEG
    (pl. visszaszámlálás: "3") nem torzítja az ellenőrzést."""
    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            lines = f.read().split('\n')
        return sum(1 for i, line in enumerate(lines)
                   if re.match(r'^\d+$', line.strip())
                   and i + 1 < len(lines) and '-->' in lines[i + 1])
    except Exception:
        return 0


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


def build_system_prompt_file(claude_md: str, glossary: str) -> tuple[str, bool]:
    """
    Összeállítja a system prompt fájlt — tartalom-hash alapú névvel.
    Visszatér: (fájl útvonal, újonnan_készült)

    Két párhuzamos Python process azonos tartalommal ugyanazt a fájlt használja
    (atomi rename), eltérő tartalommal külön fájlt kap.
    """
    parts = []
    parts.append("""=== SZEREP ===
Profi felirat-fordító vagy. Angol SRT feliratokat fordítasz természetes,
beszélt magyar nyelvre. NEM tükörfordítasz.

=== KEMÉNY SZABÁLYOK ===
- A sorszámokat és időbélyegeket PONTOSAN másold át, NE generáld fejből!
- HTML tagek (<i>, </i>), kötőjeles párbeszéd (-), [megjegyzések], ♫ jelölés őrizve.
- Karakterneveket NE fordítsd le.
- Az output PONTOSAN ugyanannyi szekciót tartalmazzon, mint az input.
- Csak a kért output fájlt írd ki — semmi extra magyarázat, semmi visszajelzés.
- Tegezés/magázás: kövesd a sorozatkontextus Megszólítási regiszterét; ha nincs
  rá adat és a forrás jeleiből sem egyértelmű, fogalmazz úgy, hogy ne kelljen
  választani. Ne találj ki viszonyt.

=== FOLYAMAT ===
1. Olvasd be a megadott input SRT fájlt.
2. Fordítsd le a szöveget — sorszám + időbélyeg változatlanul.
3. Mentsd a megadott output fájlba.
4. Kész — ne írj összefoglalót, ne ellenőrizd újra.""")

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — KÖTELEZŐ HASZNÁLNI EZEKET A FORDÍTÁSOKAT ===\n"
            + glossary.strip()
        )

    content = "\n\n".join(parts)
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    sys_path = os.path.abspath(f"{SYS_PROMPT_PREFIX}{h}.txt")

    if os.path.isfile(sys_path):
        return sys_path, False

    # Atomi írás: tmp fájlba, majd rename
    tmp_path = sys_path + f".tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.replace(tmp_path, sys_path)  # atomi op
        return sys_path, True
    except Exception:
        # Rename sikertelen — talán másik process időközben létrehozta.
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        if os.path.isfile(sys_path):
            return sys_path, False  # másik process megírta — használhatjuk
        raise RuntimeError(f"Nem sikerült létrehozni a sys prompt fájlt: {sys_path}")


def cleanup_stale_sys_prompts(max_age_days: int = SYS_PROMPT_MAX_AGE_DAYS):
    """Régebbi sys prompt fájlok törlése — biztonsági takarítás."""
    cutoff = time.time() - max_age_days * 86400
    pattern = f"{SYS_PROMPT_PREFIX}*.txt"
    for f in glob.glob(pattern):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
        except Exception:
            pass


def safe_remove(filepath: str):
    """Fájl biztonságos törlése — Windows-on kezeli a fájl-zárolást."""
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except PermissionError:
        time.sleep(2)
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
        except PermissionError:
            print(f"  [!] Nem sikerült törölni (zárolva): {os.path.basename(filepath)}")
            print(f"      Töröld kézzel, majd futtasd újra a scriptet.")


def find_claude() -> str | None:
    """A claude CLI feloldása. A shutil.which Windows-on az npm-es claude.cmd
    shimet is megtalálja — a puszta ["claude", ...] subprocess hívás ott
    FileNotFoundError-t adna, hiába működik a terminálból."""
    return shutil.which("claude")


def kill_process_tree(proc: subprocess.Popen):
    """Timeout után a TELJES folyamatfát leöljük. Windows-on a claude.cmd
    shim alatt futó node process árvaként túlélné a sima kill-t, és utólag
    (a törlés UTÁN) még kiírhatná a _HUN fájlt — amit a resume aztán
    késznek látna."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def translate_block(block_path: str, sys_prompt_path: str, model: str,
                    timeout: int = 900, max_turns: int = 20,
                    claude_bin: str = "claude") -> dict:
    output_path = block_path[:-len(".srt")] + "_HUN.srt"
    block_name = os.path.basename(block_path)
    result = {"block": block_name, "status": "unknown", "message": ""}

    print(f"[START] {block_name}")

    prompt = (
        f"Input fájl:  {os.path.abspath(block_path)}\n"
        f"Output fájl: {os.path.abspath(output_path)}\n"
        f"Fordítsd le a system promptban megadott szabályok szerint."
    )

    cmd = [
        claude_bin, "-p", prompt,
        "--append-system-prompt-file", sys_prompt_path,
        "--allowedTools", "Read,Write",
        "--model", model,
        "--max-turns", str(max_turns),
    ]

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8'
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_process_tree(proc)
            result["status"] = "fail"
            result["message"] = f"Timeout ({timeout // 60} perc)"
            safe_remove(output_path)
            return result
        if proc.returncode != 0:
            result["status"] = "fail"
            combined = ((stderr or "") + "\n" + (stdout or "")).strip().splitlines()
            tail = [l for l in combined if l.strip()][-3:]
            result["message"] = f"Claude Code hiba (exit {proc.returncode}): {' | '.join(tail)}"
            safe_remove(output_path)
            return result
    except FileNotFoundError:
        result["status"] = "fail"
        result["message"] = "A 'claude' parancs nem található! Telepítve van a Claude Code?"
        return result
    except Exception as e:
        result["status"] = "fail"
        result["message"] = str(e)
        safe_remove(output_path)
        return result

    if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
        in_count = count_sections(block_path)
        out_count = count_sections(output_path)
        if in_count == out_count:
            result["status"] = "ok"
            result["message"] = f"{out_count} szekció"
        else:
            # A hibás outputot töröljük, különben a resume késznek látná,
            # és a szekció-eltérés csendben végleges állapottá válna.
            result["status"] = "warning"
            result["message"] = (f"Szekciószám eltérés! Input: {in_count}, "
                                 f"Output: {out_count} — output törölve, "
                                 f"újrafutáskor újrafordítjuk")
            safe_remove(output_path)
    else:
        result["status"] = "fail"
        result["message"] = "Üres vagy hiányzó output"
        safe_remove(output_path)

    return result


def main():
    parser = argparse.ArgumentParser(description="Párhuzamos SRT fordítás Claude Code-dal (multi-process safe)")
    parser.add_argument("blocks_dir", help="Blokkok mappája (split_srt.py outputja)")
    parser.add_argument("--agents", type=int, default=3,
                        help="Párhuzamos agent-ek száma (alapértelmezett: 3)")
    parser.add_argument("--block", type=str, default=None,
                        help="Csak egy konkrét blokk fordítása (pl. 003 vagy 3 — auto zero-pad)")
    parser.add_argument("--timeout", type=int, default=900,
                        help="Timeout blokkonként másodpercben (alapértelmezett: 900 = 15 perc)")
    parser.add_argument("--model", type=str, default="sonnet",
                        choices=["haiku", "sonnet", "opus"],
                        help="Claude modell (alapértelmezett: sonnet)")
    parser.add_argument("--max-turns", type=int, default=20,
                        help="Maximum agent fordulók blokkonként (alapértelmezett: 20)")
    parser.add_argument("--no-cleanup", action="store_true",
                        help="Ne takarítsa ki a régi sys prompt fájlokat startup-kor")
    args = parser.parse_args()

    if not os.path.isdir(args.blocks_dir):
        print(f"HIBA: Nem találom a mappát: {args.blocks_dir}")
        sys.exit(1)

    claude_bin = find_claude()
    if not claude_bin:
        print("HIBA: A 'claude' parancs nem található a PATH-on!")
        print("      Telepítés: npm install -g @anthropic-ai/claude-code")
        sys.exit(1)

    if not args.no_cleanup:
        cleanup_stale_sys_prompts()

    all_blocks = get_all_blocks(args.blocks_dir)
    total = len(all_blocks)

    if args.block:
        # Auto zero-pad: --block 3 -> 003 (a fájlnév pattern _block_NNN_ formátumú).
        # Csak numerikus inputot pad-elünk, alfanumerikust változatlanul hagyjuk.
        block_id = args.block.zfill(3) if args.block.isdigit() else args.block
        pending = [b for b in all_blocks if f"_block_{block_id}_" in b]
        if not pending:
            print(f"HIBA: Nem találom a {args.block} (={block_id}) számú blokkot!")
            sys.exit(1)
        for b in pending:
            hun = b[:-len(".srt")] + "_HUN.srt"
            if os.path.isfile(hun):
                os.remove(hun)
                print(f"Korábbi fordítás törölve: {os.path.basename(hun)}")
    else:
        pending = get_pending_blocks(args.blocks_dir)

    # Tényleges lemez-állapot — figyelembe veszi az imént törölt --block HUN fájlt
    done = total - len(get_pending_blocks(args.blocks_dir))

    claude_md = load_claude_md()
    glossary = load_glossary()
    sys_prompt_path, newly_created = build_system_prompt_file(claude_md, glossary)
    sys_prompt_size = os.path.getsize(sys_prompt_path)

    print("=" * 50)
    print("  Fordítási állapot")
    print("=" * 50)
    print(f"  Összes blokk:   {total}")
    print(f"  Kész:           {done}")
    print(f"  Fordítandó:     {len(pending)}")
    print(f"  Agent-ek:       {args.agents}")
    print(f"  Modell:         {args.model}")
    print(f"  Max turns:      {args.max_turns}")
    print(f"  Timeout:        {args.timeout // 60} perc / blokk")
    print(f"  System prompt:  {sys_prompt_size} byte ({'új fájl' if newly_created else 'meglévő — másik process is használhatja'})")
    print(f"     fájl:        {os.path.basename(sys_prompt_path)}")
    if claude_md:
        print(f"     - CLAUDE.md betöltve ({len(claude_md)} char)")
    else:
        print("     - FIGYELEM: CLAUDE.md nem található a munkakönyvtárban —")
        print("       sorozat-kontextus NÉLKÜL fordítok! (rossz mappából futtatod?)")
    if glossary:
        print(f"     - glossary.json betöltve ({len(glossary)} char)")
    else:
        print("     - FIGYELEM: glossary.json nem található — szójegyzék nélkül fordítok")
    print("=" * 50)

    if not pending:
        print("\nMinden blokk le van fordítva!")
        return

    print(f"\nFordítandó blokkok:")
    for p in pending:
        print(f"  - {os.path.basename(p)}")
    print()

    results = []
    with ThreadPoolExecutor(max_workers=args.agents) as executor:
        futures = {
            executor.submit(
                translate_block, block, sys_prompt_path,
                args.model, args.timeout, args.max_turns, claude_bin
            ): block
            for block in pending
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status_icon = {"ok": "✓", "warning": "⚠", "fail": "✗"}.get(result["status"], "?")
            print(f"  [{status_icon}] {result['block']} — {result['message']}")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    warn_count = sum(1 for r in results if r["status"] == "warning")
    fail_count = sum(1 for r in results if r["status"] == "fail")

    print()
    print("=" * 50)
    print("  Végeredmény")
    print("=" * 50)
    print(f"  Sikeres:    {ok_count}")
    if warn_count:
        print(f"  Figyelem:   {warn_count} (szekció-eltérés — output törölve)")
    if fail_count:
        print(f"  Sikertelen: {fail_count}")
    if warn_count or fail_count:
        print(f"\n  A sikertelen/eltérő blokkok újrafordításához futtasd újra ezt a scriptet.")
    print("=" * 50)
    # A sys prompt fájlt NEM töröljük — másik process még használhatja,
    # és a következő futás cache hit-tel indulhat. 1 nap után úgyis takarítva lesz.


if __name__ == "__main__":
    main()
