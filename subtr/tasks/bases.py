"""Alap-szótárak (glossaries/) kezelése: listázás, sorozatból alapba emelés, ütközés-ellenőrzés.

    py subtr.py bases list
    py subtr.py bases promote "Marquis" "Marchioness" --to zh-historical [--from <sorozat>/glossary.json]
    py subtr.py bases check [--glossary glossary.json]

A `promote` a REPÓ `glossaries/` mappájába írjon: a sorozat-mappákban lévő
`glossaries/` csak másolat, amit a következő kód-szinkron felülír. Ezért a
parancsot a repo gyökeréből érdemes futtatni, a sorozat glossaryját `--from`
kapcsolóval megadva — ha mégis másolatba írna, figyelmeztet.
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys

from subtr import glossary as g
from subtr.config import GLOSSARIES_DIR, GLOSSARY_PATH


def _bases_dir_for(glossary_path: str) -> str:
    return os.path.join(os.path.dirname(glossary_path), GLOSSARIES_DIR)


def _in_git_repo(path: str) -> bool:
    path = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def _write_json(path: str, data: dict) -> None:
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _count(data: dict) -> int:
    return sum(len(data.get(c, []) or []) for c in g.CATEGORIES)


# ── list ────────────────────────────────────────────────────────────────────

def cmd_list(args) -> int:
    directory = _bases_dir_for(args.glossary)
    index = g.load_index(directory)
    used = g.base_ids(g.load(args.glossary)) if os.path.isfile(args.glossary) else []
    print(f"Alap-szótárak ({directory}):")
    listed = set()
    for base in index:
        base_id = base["id"]
        listed.add(base_id)
        data = g.load_base(base_id, directory) if os.path.isfile(
            os.path.join(directory, base_id + ".json")) else None
        count = f"{_count(data):4} bejegyzés" if data else "   — még nincs fájl"
        mark = "  ← ez a sorozat használja" if base_id in used else ""
        print(f"  {base_id:<14} {count}  {base.get('title', '')}{mark}")
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        base_id = os.path.splitext(os.path.basename(path))[0]
        if base_id != "index" and base_id not in listed:
            print(f"  {base_id:<14} (nincs az index.json-ban)")
    print(f"\nA sorozat ({args.glossary}) meta.bases: {', '.join(used) or '—'}")
    return 0


# ── promote ─────────────────────────────────────────────────────────────────

def promote(project: dict, base: dict, terms: list[str], context: str | None = None,
            replace: bool = False, keep: bool = False):
    """A `terms` bejegyzéseit a projektből az alapba másolja (azonos kategóriába).

    Visszaad: (áthelyezett bejegyzések listája, hibaüzenetek listája). A dict-eket
    helyben módosítja; íráshoz a hívó felel.
    """
    moved, errors = [], []
    base_keys = {g.normalize_for_match(e.get("en", "")): (c, i)
                 for c in g.CATEGORIES for i, e in enumerate(base.get(c, []) or [])}
    for term in terms:
        key = g.normalize_for_match(term)
        found = None
        for category in g.CATEGORIES:
            for i, entry in enumerate(project.get(category, []) or []):
                if g.normalize_for_match(entry.get("en", "")) == key:
                    found = (category, i, entry)
                    break
            if found:
                break
        if not found:
            errors.append(f"„{term}” nincs a sorozat glossaryjában")
            continue
        category, index, entry = found
        new_entry = {"en": entry["en"], "hu": entry["hu"],
                     "context": context if context is not None else entry.get("context", "")}
        if key in base_keys:
            if not replace:
                bc, bi = base_keys[key]
                errors.append(f"„{term}” már szerepel az alapban "
                              f"(= „{base[bc][bi].get('hu')}”) — felülírás: --replace")
                continue
            bc, bi = base_keys[key]
            base[bc][bi] = new_entry
        else:
            base.setdefault(category, []).append(new_entry)
            base_keys[key] = (category, len(base[category]) - 1)
        if not keep:
            project[category].pop(index)
        moved.append((category, new_entry))
    return moved, errors


def cmd_promote(args) -> int:
    if not g.BASE_ID_RE.match(args.to):
        print(f"HIBA: érvénytelen alap-azonosító: {args.to!r}")
        return 1
    if not os.path.isfile(args.glossary):
        print(f"HIBA: nincs ilyen szójegyzék: {args.glossary}")
        return 1
    directory = args.bases_dir or GLOSSARIES_DIR
    base_path = os.path.join(directory, args.to + ".json")
    if not os.path.isfile(base_path):
        print(f"HIBA: nincs ilyen alap: {base_path} (új alaphoz előbb hozd létre, és vedd fel az index.json-ba)")
        return 1
    if not _in_git_repo(directory):
        print(f"FIGYELEM: a(z) {directory} nem verziókövetett — valószínűleg egy sorozat-mappa\n"
              f"  MÁSOLATA, amit a következő kód-szinkron felülír. A repo gyökeréből futtasd:\n"
              f"  py subtr.py bases promote ... --from \"<sorozat>/glossary.json\"")
        if not args.force:
            print("  Ha mégis ide akarsz írni: --force")
            return 1

    with open(args.glossary, encoding="utf-8-sig") as f:
        project = json.load(f)
    with open(base_path, encoding="utf-8-sig") as f:
        base = json.load(f)

    moved, errors = promote(project, base, args.terms, args.context, args.replace, args.keep)
    for err in errors:
        print(f"HIBA: {err}")
    if not moved:
        return 1

    print(f"Az alapba ({args.to}) kerülne — a repo NYILVÁNOS, a context ne tartalmazzon"
          f" sorozat- vagy szereplőnevet:")
    for category, entry in moved:
        print(f"  [{category}] \"{entry['en']}\" = \"{entry['hu']}\"")
        print(f"      context: {entry['context'] or '—'}")
    if args.dry_run:
        print("\n--dry-run: semmi nem módosult.")
        return 0
    if not args.yes:
        try:
            answer = input("\nMehet? [i/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("i", "igen", "y", "yes"):
            print("Megszakítva, semmi nem módosult.")
            return 1

    _write_json(base_path, base)
    print(f"Mentve: {base_path} (+ .bak)")
    if not args.keep:
        _write_json(args.glossary, project)
        print(f"Kivéve a sorozatból: {args.glossary} (+ .bak) — mostantól az alapból jön.")
    print("Ne felejtsd: commit a repóban, majd kód-szinkron a sorozat-mappákba.")
    return 1 if errors else 0


# ── check ───────────────────────────────────────────────────────────────────

def _cues(path: str) -> dict:
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        content = f.read()
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.split("\n")
        if len(lines) >= 3 and lines[0].strip().isdigit():
            out[int(lines[0])] = " ".join(lines[2:])
    return out


def _translated_pairs(project_dir: str) -> list[tuple[str, str]]:
    """(forrás-SRT, kész magyar SRT) párok a sorozat-mappából, 1:1 cue-számmal."""
    pairs, seen = [], set()
    candidates = sorted(glob.glob(os.path.join(project_dir, "output", "*.hun.srt"))
                        + glob.glob(os.path.join(project_dir, "Season 01", "*.hun.srt")))
    for hun in candidates:
        stem = os.path.basename(hun)[:-len(".hun.srt")]
        if stem in seen:
            continue
        sources = [p for p in glob.glob(os.path.join(project_dir, "input", stem + ".*.srt"))
                   if ".hun." not in p and ".clean." not in p]
        if sources:
            seen.add(stem)
            pairs.append((sources[0], hun))
    return pairs


def check(project: dict, directory: str, project_dir: str, limit: int = 20) -> dict:
    """Az alapok és a sorozat viszonya: egyezés, felülírás, eltérés a kész fordításokban."""
    project_map = {g.normalize_for_match(e.get("en", "")): e.get("hu", "")
                   for c in g.CATEGORIES for e in project.get(c, []) or []}
    same, overridden, new = [], [], []
    for base_id in g.base_ids(project):
        data = g.load_base(base_id, directory) or {}
        for c in g.CATEGORIES:
            for e in data.get(c, []) or []:
                key = g.normalize_for_match(e.get("en", ""))
                if key in project_map:
                    if project_map[key].strip().lower() == e.get("hu", "").strip().lower():
                        same.append((base_id, e))
                    else:
                        overridden.append((base_id, e, project_map[key]))
                else:
                    new.append((base_id, e))

    mismatches = []
    pairs = _translated_pairs(project_dir)
    for src, hun in pairs:
        source, target = _cues(src), _cues(hun)
        if len(source) != len(target):
            continue
        for base_id, e in new:
            pe = g.term_pattern(g.normalize_for_match(e["en"]).strip(), False)
            ph = g.term_pattern(g.normalize_for_match(e["hu"]).strip(), True)
            if not pe or not ph:
                continue
            for n, text in source.items():
                if pe.search(g.normalize_for_match(text)) and \
                        not ph.search(g.normalize_for_match(target.get(n, ""))):
                    mismatches.append((base_id, e, os.path.basename(hun), n, target.get(n, "")))
    return {"same": same, "overridden": overridden, "new": new,
            "pairs": len(pairs), "mismatches": mismatches}


def cmd_check(args) -> int:
    if not os.path.isfile(args.glossary):
        print(f"HIBA: nincs ilyen szójegyzék: {args.glossary}")
        return 1
    project = g.load(args.glossary)
    if not g.base_ids(project):
        print("A sorozat nem használ alap-szótárt (meta.bases üres).")
        return 0
    result = check(project, _bases_dir_for(args.glossary),
                   os.path.dirname(os.path.abspath(args.glossary)))
    print(f"Alapok: {', '.join(g.base_ids(project))}")
    print(f"  a sorozatban szó szerint azonos (törölhető a sorozatból): {len(result['same'])}")
    print(f"  a sorozat felülírja: {len(result['overridden'])}")
    for base_id, e, hu in result["overridden"][:args.limit]:
        print(f"    {e['en']}: alap „{e['hu']}” ({base_id}) → sorozat „{hu}”")
    print(f"  csak az alapból jön: {len(result['new'])}")
    mism = result["mismatches"]
    print(f"\nKész fordítások összevetve: {result['pairs']} rész — "
          f"{len(mism)} helyen más magyar alak áll, mint az alapé:")
    by_term = {}
    for base_id, e, file, n, text in mism:
        by_term.setdefault((e["en"], e["hu"], base_id), []).append((file, n, text))
    for (en, hu, base_id), hits in sorted(by_term.items(), key=lambda x: -len(x[1]))[:args.limit]:
        file, n, text = hits[0]
        print(f"  {en} = {hu} ({base_id}): {len(hits)}× — pl. {file} #{n}: „{text[:70]}”")
    if mism:
        print("\nNem minden eltérés hiba (ragozás, összetétel, más jelentés) — ahol a sorozat\n"
              "következetesen mást használ, vedd fel felülírásként a sorozat glossaryjába.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Alap-szótárak (glossaries/): listázás, sorozatból alapba emelés, ütközés-ellenőrzés.")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="Alapok és a sorozat választása")
    p_list.add_argument("--glossary", default=GLOSSARY_PATH)

    p_prom = sub.add_parser("promote", help="Terminus(ok) a sorozat glossaryjából az alapba")
    p_prom.add_argument("terms", nargs="+", help="Az „en” alak(ok), ahogy a glossaryban áll")
    p_prom.add_argument("--to", required=True, help="Cél-alap azonosítója (pl. zh-historical)")
    p_prom.add_argument("--from", dest="glossary", default=GLOSSARY_PATH,
                        help="A sorozat glossary.json-ja (default: ./glossary.json)")
    p_prom.add_argument("--bases-dir", default=None,
                        help=f"Az alapok mappája (default: ./{GLOSSARIES_DIR} — a repo gyökeréből futtatva a repóé)")
    p_prom.add_argument("--context", default=None,
                        help="Új, általános context (a sorozat-specifikus helyett); minden terminusra")
    p_prom.add_argument("--replace", action="store_true", help="Az alap meglévő bejegyzését felülírja")
    p_prom.add_argument("--keep", action="store_true", help="A sorozat glossaryjában is maradjon")
    p_prom.add_argument("--dry-run", action="store_true", help="Csak kiírja, mi történne")
    p_prom.add_argument("--yes", action="store_true", help="Ne kérdezzen")
    p_prom.add_argument("--force", action="store_true",
                        help="Nem verziókövetett (sorozat-mappabeli) alapba is írjon")

    p_check = sub.add_parser("check", help="Alap ↔ sorozat ↔ kész fordítások ütközései")
    p_check.add_argument("--glossary", default=GLOSSARY_PATH)
    p_check.add_argument("--limit", type=int, default=20, help="Legfeljebb ennyi sor kategóriánként")

    args = parser.parse_args(argv)
    if args.cmd is None:
        args = parser.parse_args(["list"])
    handler = {"list": cmd_list, "promote": cmd_promote, "check": cmd_check}[args.cmd]
    sys.exit(handler(args))


if __name__ == "__main__":
    main()
