"""
glossary_extract.py — Kifejezések kinyerése feliratpárból, interaktív jóváhagyással

Használat:
    python glossary_extract.py eredeti.eng.srt fordított.hun.srt
    python glossary_extract.py eredeti.eng.srt fordított.hun.srt --glossary glossary.json

Egy angol-magyar SRT párt Claude Code-dal elemez, kigyűjti a visszatérő
kifejezéseket (megszólítások, helyszínek, nevek, speciális fogalmak),
majd a konzolon egyesével jóváhagyhatod őket.
Csak az elfogadott kifejezések kerülnek a glossary.json-ba.
"""

import os
import sys
import json
import re
import argparse
import shutil
import subprocess

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


def find_claude_cli() -> str:
    """Claude CLI megkeresése."""
    found = shutil.which("claude")
    if found:
        return found
    # Tipikus Windows telepítési hely
    local_bin = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
    if os.path.isfile(local_bin):
        return local_bin
    npm_global = os.path.join(os.environ.get("APPDATA", ""), "npm", "claude.cmd")
    if os.path.isfile(npm_global):
        return npm_global
    return "claude"  # fallback, hadd kapja el a FileNotFoundError

CATEGORIES = ["honorifics", "place_names", "character_names", "special_terms", "phrases"]


def sanitize_inner_quotes(s: str) -> str:
    """Heurisztikusan kicseréli a JSON string értékek BELSEJÉBEN előforduló
    nem-escapelt ASCII " karaktereket magyar záró idézőjelre (").

    Egy ASCII " akkor tekinthető string-lezárónak, ha utána (whitespace-eket
    átugorva) , } ] : vagy fájlvég következik. Minden más esetben stray
    belső idézőjel — ezt cseréljük "-re, hogy a parser ne hasaljon el.
    """
    out = []
    in_string = False
    escape = False
    n = len(s)
    i = 0
    while i < n:
        c = s[i]
        if escape:
            out.append(c)
            escape = False
            i += 1
            continue
        if c == '\\':
            out.append(c)
            escape = True
            i += 1
            continue
        if c == '"':
            if not in_string:
                in_string = True
                out.append(c)
            else:
                j = i + 1
                while j < n and s[j] in ' \t\r\n':
                    j += 1
                if j >= n or s[j] in ',}]:':
                    in_string = False
                    out.append(c)
                else:
                    out.append('”')
            i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)

CATEGORY_LABELS = {
    "honorifics": "Megszólítás",
    "place_names": "Helyszín",
    "character_names": "Karakternév",
    "special_terms": "Speciális kifejezés",
    "phrases": "Kifejezés",
}


def load_glossary(path: str) -> dict:
    """Meglévő glossary betöltése vagy üres struktúra."""
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "meta": {"description": "Fordítási szójegyzék — kézzel validált kifejezések", "series": ""},
        "honorifics": [],
        "place_names": [],
        "character_names": [],
        "special_terms": [],
        "phrases": [],
    }


def save_glossary(path: str, data: dict):
    """Glossary mentése."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nSzójegyzék mentve: {path}")


def get_existing_terms(glossary: dict) -> set:
    """Meglévő EN kifejezések halmaza (kisbetűs) a duplikátumszűréshez."""
    terms = set()
    for cat in CATEGORIES:
        for entry in glossary.get(cat, []):
            terms.add(entry.get("en", "").lower())
    return terms


def extract_terms(eng_path: str, hun_path: str, existing_terms: set, timeout: int = 300) -> list[dict]:
    """Claude Code-dal kifejezések kinyerése a feliratpárból."""
    with open(eng_path, 'r', encoding='utf-8-sig') as f:
        eng_content = f.read()
    with open(hun_path, 'r', encoding='utf-8-sig') as f:
        hun_content = f.read()

    # Meglévő kifejezések listája a prompthoz
    existing_note = ""
    if existing_terms:
        existing_note = f"""
MÁR MEGLÉVŐ KIFEJEZÉSEK (ne javasold újra ezeket):
{', '.join(sorted(existing_terms))}
"""

    prompt = f"""Elemezd az alábbi angol-magyar feliratpárt és gyűjtsd ki a visszatérő, konzisztensen fordítandó kifejezéseket.

KATEGÓRIÁK:
- honorifics: megszólítások, rangok, címek (pl. Your Highness, General, My Lord)
- place_names: helyszínek, tartományok, paloták
- character_names: karakternevek (a helyes írásmód, NEM fordítás)
- special_terms: kulturális/speciális kifejezések (pl. spiritual root, cultivation, gisaeng)
- phrases: visszatérő kifejezések, amelyeknek konzisztens fordítása fontos
{existing_note}
FONTOS:
- Csak olyan kifejezéseket adj, amelyek TÖBBSZÖR előfordulnak vagy fontosak a konzisztencia szempontjából
- A "hu" mezőben azt a fordítást add, amit a magyar feliratban TÉNYLEGESEN használtunk
- Ne adj triviális szavakat (pl. "yes" = "igen")
- Maximum 30-40 kifejezést adj

JSON SZINTAKTIKAI SZABÁLY (KRITIKUS):
- A JSON string értékek BELSEJÉBEN SOHA ne használj ASCII " (U+0022) karaktert, mert az lezárja a stringet és a parser elhasal.
- Ha a magyar/angol szövegben idézőjel kell (pl. egy nevet idézel), KIZÁRÓLAG a magyar tipográfiai idézőjeleket használd: nyitó „ (U+201E) és záró " (U+201D).
- Példa HELYES: {{"en":"Shim Coffee House","hu":"„Shim” Kávéház","context":"kávézó neve"}}
- Példa HIBÁS:  {{"en":"Shim Coffee House","hu":"„Shim\" Kávéház",...}} — a value belsejében " (ASCII) lezárja a stringet.
- Aposztrófként se ASCII '-t, hanem ' (U+2019) karaktert használj, ha kell.

Válaszolj KIZÁRÓLAG egy JSON tömbbel, semmi más szöveget NE írj:
[{{"en": "angol kifejezés", "hu": "magyar fordítás", "category": "honorifics|place_names|character_names|special_terms|phrases", "context": "rövid megjegyzés"}}]

ANGOL FELIRAT:
{eng_content[:15000]}

MAGYAR FELIRAT:
{hun_content[:15000]}"""

    claude_cmd = find_claude_cli()
    print(f"Claude Code elemzi a feliratpárt... ({claude_cmd})")
    try:
        proc = subprocess.run(
            [claude_cmd, "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding='utf-8'
        )

        if proc.returncode != 0:
            print(f"HIBA: Claude Code hiba (exit code: {proc.returncode})")
            print(f"  stderr: {proc.stderr[:500]}" if proc.stderr else "")
            return []

        raw = proc.stdout.strip()

        # JSON kinyerése — több stratégia
        candidates = []
        json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', raw, re.DOTALL)
        if json_match:
            candidates.append(json_match.group(1))
        # Mohó: első '['-tól utolsó ']'-ig
        first = raw.find('[')
        last = raw.rfind(']')
        if first != -1 and last != -1 and last > first:
            candidates.append(raw[first:last+1])
        candidates.append(raw)

        suggestions = None
        last_err = None
        for cand in candidates:
            for variant in (cand, sanitize_inner_quotes(cand)):
                try:
                    suggestions = json.loads(variant)
                    break
                except json.JSONDecodeError as e:
                    last_err = e
                    continue
            if suggestions is not None:
                break

        if suggestions is None:
            # Debug dump
            debug_path = ".glossary_extract_debug.txt"
            with open(debug_path, 'w', encoding='utf-8') as df:
                df.write(raw)
            print(f"HIBA: JSON parse hiba: {last_err}")
            print(f"  Nyers válasz mentve: {debug_path}")
            print(f"  Válasz hossza: {len(raw)} karakter")
            print(f"  Első 300 karakter:\n  {raw[:300]!r}")
            return []

        # Validáció
        valid = []
        for s in suggestions:
            if all(k in s for k in ("en", "hu", "category")):
                if s["category"] in CATEGORIES:
                    if s["en"].lower() not in existing_terms:
                        valid.append(s)

        return valid

    except subprocess.TimeoutExpired:
        print(f"HIBA: Timeout ({timeout} mp)")
        return []
    except FileNotFoundError:
        print(f"HIBA: A 'claude' parancs nem található! (keresett: {claude_cmd})")
        print("  Megoldás: telepítsd a Claude Code CLI-t, vagy add hozzá a PATH-hoz.")
        print(f"  Tipp: ellenőrizd, hogy létezik-e: {os.path.join(os.path.expanduser('~'), '.local', 'bin', 'claude.exe')}")
        return []


def interactive_review(suggestions: list[dict]) -> list[dict]:
    """Interaktív jóváhagyás a konzolon."""
    if not suggestions:
        print("\nNincs új javaslat.")
        return []

    print(f"\n{'=' * 55}")
    print(f"  {len(suggestions)} új kifejezés javaslat")
    print(f"{'=' * 55}")
    print("  y = elfogad  |  n = elutasít  |  e = szerkeszt  |  q = kilép")
    print(f"{'=' * 55}\n")

    approved = []
    for i, s in enumerate(suggestions):
        cat_label = CATEGORY_LABELS.get(s["category"], s["category"])
        context = s.get("context", "")
        ctx_str = f"  ({context})" if context else ""

        print(f"[{i+1}/{len(suggestions)}] [{cat_label}]")
        print(f"  EN: {s['en']}")
        print(f"  HU: {s['hu']}{ctx_str}")

        while True:
            choice = input("  Döntés (y/n/e/q): ").strip().lower()
            if choice == 'y':
                approved.append(s)
                print("  → Elfogadva")
                break
            elif choice == 'n':
                print("  → Elutasítva")
                break
            elif choice == 'e':
                new_hu = input(f"  Új magyar fordítás [{s['hu']}]: ").strip()
                if new_hu:
                    s['hu'] = new_hu
                new_ctx = input(f"  Új kontextus [{context}]: ").strip()
                if new_ctx:
                    s['context'] = new_ctx
                new_cat = input(f"  Új kategória [{s['category']}]: ").strip()
                if new_cat and new_cat in CATEGORIES:
                    s['category'] = new_cat
                approved.append(s)
                print("  → Elfogadva (szerkesztve)")
                break
            elif choice == 'q':
                print("\n  Jóváhagyás megszakítva.")
                return approved
            else:
                print("  Ismeretlen válasz. Használj: y / n / e / q")
        print()

    return approved


def merge_into_glossary(glossary: dict, approved: list[dict]) -> int:
    """Elfogadott kifejezések beillesztése a glossary-ba. Visszaadja a hozzáadottak számát."""
    added = 0
    for entry in approved:
        cat = entry["category"]
        if cat not in CATEGORIES:
            continue

        # Duplikátum ellenőrzés
        existing_en = {e.get("en", "").lower() for e in glossary.get(cat, [])}
        if entry["en"].lower() in existing_en:
            continue

        glossary[cat].append({
            "en": entry["en"],
            "hu": entry["hu"],
            "context": entry.get("context", ""),
        })
        added += 1

    return added


def main():
    parser = argparse.ArgumentParser(description="Kifejezések kinyerése feliratpárból")
    parser.add_argument("eng_srt", help="Eredeti angol SRT fájl")
    parser.add_argument("hun_srt", help="Fordított magyar SRT fájl")
    parser.add_argument("--glossary", type=str, default="glossary.json",
                        help="Szójegyzék fájl útvonala (alapértelmezett: glossary.json)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Claude Code timeout másodpercben (alapértelmezett: 300)")
    args = parser.parse_args()

    for path in [args.eng_srt, args.hun_srt]:
        if not os.path.isfile(path):
            print(f"HIBA: Nem találom a fájlt: {path}")
            sys.exit(1)

    print("=" * 55)
    print("  Glossary Extract — Kifejezés kinyerés")
    print("=" * 55)
    print(f"  Angol:      {args.eng_srt}")
    print(f"  Magyar:     {args.hun_srt}")
    print(f"  Szójegyzék: {args.glossary}")
    print("=" * 55)
    print()

    # Meglévő glossary betöltése
    glossary = load_glossary(args.glossary)
    existing_terms = get_existing_terms(glossary)
    if existing_terms:
        print(f"Meglévő kifejezések: {len(existing_terms)}")

    # Kinyerés
    suggestions = extract_terms(args.eng_srt, args.hun_srt, existing_terms, args.timeout)

    if not suggestions:
        print("Nem találtam új kifejezést.")
        return

    print(f"\n{len(suggestions)} új kifejezés javaslat érkezett.")

    # Interaktív jóváhagyás
    approved = interactive_review(suggestions)

    if not approved:
        print("\nNem lett elfogadva egyetlen kifejezés sem.")
        return

    # Beillesztés
    added = merge_into_glossary(glossary, approved)
    save_glossary(args.glossary, glossary)

    print(f"\n{'=' * 55}")
    print(f"  Eredmény: {added} új kifejezés hozzáadva")
    total = sum(len(glossary.get(cat, [])) for cat in CATEGORIES)
    print(f"  Összesen a szójegyzékben: {total}")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
