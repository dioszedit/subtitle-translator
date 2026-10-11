"""Alap-szótárak (glossaries/) kezelése: listázás, sorozatból alapba emelés, ütközés-ellenőrzés.

    py subtr.py bases list
    py subtr.py bases promote "Grand Tutor" --to zh-historical [--from <sorozat>/glossary.json]
    py subtr.py bases check [--glossary glossary.json]

A `promote` a REPÓ `glossaries/` mappájába írjon: a sorozat-mappákban lévő
`glossaries/` csak másolat, amit a következő kód-szinkron felülír. Ezért a
parancsot a repo gyökeréből érdemes futtatni, a sorozat glossaryját `--from`
kapcsolóval megadva — ha mégis másolatba írna, figyelmeztet.
"""

import argparse
import json
import os
import sys

from subtr import config
from subtr import glossary as g
from subtr.config import GLOSSARIES_DIR, GLOSSARY_PATH
from subtr.srt import parse_by_index


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


def _read_json(path: str):
    """(adat, hiba) — a hiba olvasható szöveg, ha a fájl nem olvasható / nem objektum."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)
    if not isinstance(data, dict):
        return None, "a gyökér nem JSON-objektum"
    return data, None


# ── list ────────────────────────────────────────────────────────────────────

def cmd_list(args) -> int:
    directory = _bases_dir_for(args.glossary)
    index = g.load_index(directory)
    used = []
    if os.path.isfile(args.glossary):
        data, err = _read_json(args.glossary)
        if err:
            print(f"HIBA: {args.glossary}: {err}")
            return 1
        used = g.base_ids(data)
    print(f"Alap-szótárak ({directory}):")
    listed = set()
    for base in index:
        base_id = base["id"]
        listed.add(base_id)
        path = os.path.join(directory, base_id + ".json")
        if not os.path.isfile(path):
            count = "   — még nincs fájl"
        else:
            data, err = _read_json(path)
            count = f"   HIBÁS FÁJL: {err}" if err else f"{g.count_entries(data):4} bejegyzés"
        mark = "  ← ez a sorozat használja" if base_id in used else ""
        print(f"  {base_id:<14} {count}  {base.get('title', '')}{mark}")
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            base_id, ext = os.path.splitext(name)
            if ext == ".json" and base_id != "index" and base_id not in listed:
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
    base_keys = {g.match_key(e): (c, i)
                 for c in g.CATEGORIES for i, e in enumerate(base.get(c, []) or [])}
    for term in terms:
        key = g.normalize_for_match(term).strip()
        found = None
        for category in g.CATEGORIES:
            for i, entry in enumerate(project.get(category, []) or []):
                if g.match_key(entry) == key:
                    found = (category, i, entry)
                    break
            if found:
                break
        if not found:
            errors.append(f"„{term}” nincs a sorozat glossaryjában")
            continue
        category, index, entry = found
        new_entry = {"en": entry["en"].strip(), "hu": entry["hu"],
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


def _upsert(base: dict, category: str, entry: dict) -> None:
    """A bejegyzés felvétele vagy cseréje (az `en` kulcs szerint) az alapban."""
    key = g.match_key(entry)
    for c in g.CATEGORIES:
        for i, e in enumerate(base.get(c, []) or []):
            if g.match_key(e) == key:
                base[c][i] = entry
                return
    base.setdefault(category, []).append(entry)


def _removal_blockers(project: dict, base_id: str, directory: str, entry: dict,
                      copy_ok: bool) -> list[str]:
    """Miért NEM vehető ki ez a terminus a sorozatból (különben elveszne / megváltozna)."""
    if base_id not in g.base_ids(project):
        return [f"a sorozat nem használja a(z) {base_id} alapot (meta.bases: "
                f"{', '.join(g.base_ids(project)) or '—'})"]
    if not copy_ok:
        return [f"a sorozat-mappában nincs (olvasható) glossaries/{base_id}.json — a következő "
                f"kód-szinkronig a terminus eltűnne a promptból"]
    # Egy erősebb (később felsorolt) alap ugyanarra az en-re mást ad → kivéve az érvényesülne.
    ids = g.base_ids(project)
    for other in ids[ids.index(base_id) + 1:]:
        data = g.load_base(other, directory) or {}
        for c in g.CATEGORIES:
            for e in data.get(c, []) or []:
                if g.match_key(e) == g.match_key(entry) and \
                        e.get("hu", "").strip().lower() != entry["hu"].strip().lower():
                    return [f"a később felsorolt {other} alap „{e.get('hu')}”-t ad — kivéve az érvényesülne"]
    return []


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

    project, err = _read_json(args.glossary)
    base, err2 = _read_json(base_path)
    if err or err2:
        print(f"HIBA: {args.glossary if err else base_path}: {err or err2}")
        return 1

    moved, errors = promote(project, base, args.terms, args.context, args.replace, keep=True)
    for msg in errors:
        print(f"HIBA: {msg}")
    if not moved:
        return 1

    # A sorozat-mappa saját glossaries/-másolata: a promote azt is frissíti, különben
    # a kivett terminus a következő kód-szinkronig eltűnne a sorozatból.
    series_dir = _bases_dir_for(args.glossary)
    series_copy = os.path.join(series_dir, args.to + ".json")
    copy_target = None
    if os.path.isfile(series_copy) and \
            os.path.realpath(series_copy) != os.path.realpath(base_path):
        copy_target = series_copy

    # Ha a sorozat ugyanabból a mappából olvassa az alapot, amit most írunk, az is „másolat”.
    same_dir = os.path.realpath(series_dir) == os.path.realpath(directory)
    copy_ok = same_dir or copy_target is not None and _read_json(copy_target)[0] is not None
    to_remove = []
    if not args.keep:
        for _, entry in moved:
            blockers = _removal_blockers(project, args.to, series_dir, entry, copy_ok)
            if blockers:
                print(f"„{entry['en']}” a sorozatban MARAD: {blockers[0]}")
            else:
                to_remove.append(entry["en"])
    if to_remove:
        promote(project, {}, to_remove, keep=False)   # kivétel a sorozatból

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

    g.write_json_atomic(base_path, base)
    print(f"Mentve: {base_path} (+ .bak)")
    if copy_target:
        copy, _ = _read_json(copy_target)
        if copy is not None:
            for category, entry in moved:
                _upsert(copy, category, entry)
            g.write_json_atomic(copy_target, copy)
            print(f"A sorozat alap-másolata is frissítve: {copy_target}")
    if to_remove:
        g.write_json_atomic(args.glossary, project)
        print(f"Kivéve a sorozatból: {', '.join(to_remove)} ({args.glossary}, + .bak) — "
              "mostantól az alapból jön. Figyelem: az alap-bejegyzés szóhatárral illeszt "
              "(a sorozaté részszóval is), ezért ragozott angol alakra ritkábban kerül a promptba.")
    print("Ne felejtsd: commit a repóban, majd kód-szinkron a sorozat-mappákba.")
    return 1 if errors else 0


# ── check ───────────────────────────────────────────────────────────────────

def _source_for(hun_path: str) -> str | None:
    """A kész magyar SRT forrása — ugyanaz a keresés, mint a review-é."""
    from pathlib import Path
    from subtr.tasks.review import find_source_srt
    found = find_source_srt(Path(hun_path), "eng")
    return str(found) if found else None


def _translated_pairs(project_dir: str) -> list[tuple[str, str]]:
    """(forrás-SRT, kész magyar SRT) párok; az output/ elsőbbséget élvez a Season 01/-gyel szemben."""
    pairs, seen = [], set()
    for sub in ("output", "Season 01"):
        folder = os.path.join(project_dir, sub)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".hun.srt"):
                continue
            stem = name[:-len(".hun.srt")]
            source = _source_for(os.path.join(folder, name))
            if stem not in seen and source:
                seen.add(stem)
                pairs.append((source, os.path.join(folder, name)))
    return pairs


def check(project: dict, directory: str, project_dir: str) -> dict:
    """Az alapok és a sorozat viszonya — az ÖSSZEFÉSÜLT (érvényes) alap szerint.

    same:       a sorozat bejegyzése megegyezik azzal, amit az alap adna (törölhető)
    overridden: a sorozat mást ad, mint az érvényes alap-bejegyzés
    new:        csak az alapból jön
    mismatches: a kész fordításokban a `new` terminus helyén más magyar alak áll
    """
    only_bases = g.with_bases({"meta": project.get("meta") or {}}, directory)
    effective = {g.match_key(e): e for c in g.CATEGORIES for e in only_bases.get(c, [])}
    project_map = {g.match_key(e): e.get("hu", "") for c in g.CATEGORIES
                   for e in project.get(c, []) or []}
    same, overridden, new = [], [], []
    for key, e in effective.items():
        base_id = e["_source"].split(":", 1)[1]
        if key in project_map:
            if project_map[key].strip().lower() == e.get("hu", "").strip().lower():
                same.append((base_id, e))
            else:
                overridden.append((base_id, e, project_map[key]))
        else:
            new.append((base_id, e))

    # Ugyanaz az illesztés, mint a promptba szűrésnél (glossary._occurs): az
    # egyszavas nagybetűs címek kis/nagybetű-érzékenyen.
    patterns = []
    for base_id, e in new:
        cs = g._case_sensitive_key(e["en"].strip())
        pe = g.term_pattern(g.normalize_for_match(e["en"], keep_case=cs).strip(), False, cs)
        ph = g.term_pattern(g.normalize_for_match(e["hu"]).strip(), True)
        if pe and ph:
            patterns.append((base_id, e, pe, ph, cs))

    mismatches, compared, skipped = [], [], []
    for src, hun in _translated_pairs(project_dir):
        source, target = parse_by_index(src), parse_by_index(hun)
        if set(source) != set(target):
            skipped.append(os.path.basename(hun))
            continue
        compared.append(os.path.basename(hun))
        src_norm = {n: g.normalize_for_match(text) for n, (_, text) in source.items()}
        src_case = {n: g.normalize_for_match(text, keep_case=True) for n, (_, text) in source.items()}
        whole, whole_case = "\n".join(src_norm.values()), "\n".join(src_case.values())
        for base_id, e, pe, ph, cs in patterns:
            texts = src_case if cs else src_norm
            if not pe.search(whole_case if cs else whole):
                continue
            for n, text in texts.items():
                if pe.search(text):
                    hu_text = target[n][1]
                    if not ph.search(g.normalize_for_match(hu_text)):
                        mismatches.append((base_id, e, os.path.basename(hun), n, hu_text))
    return {"same": same, "overridden": overridden, "new": new,
            "compared": compared, "skipped": skipped, "mismatches": mismatches}


def cmd_check(args) -> int:
    if not os.path.isfile(args.glossary):
        print(f"HIBA: nincs ilyen szójegyzék: {args.glossary}")
        return 1
    project, err = _read_json(args.glossary)
    if err:
        print(f"HIBA: {args.glossary}: {err}")
        return 1
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
    print(f"\nKész fordítások: {len(result['compared'])} rész összevetve — "
          f"{len(mism)} helyen más magyar alak áll, mint az alapé.")
    if result["skipped"]:
        print(f"  KIHAGYVA {len(result['skipped'])} rész (a sorszámok eltérnek a forrásétól — "
              f"resegment / SDH-tisztítás után): {', '.join(result['skipped'][:5])}"
              + (" …" if len(result["skipped"]) > 5 else ""))
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
