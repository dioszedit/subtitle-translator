#!/usr/bin/env python3
"""
register_extract.py — Megszólítási regiszter kinyerése a forrásfeliratból.

OPCIONÁLIS lépés: a regisztert kézzel is megírhatod a TRANSLATION.local.md-ben,
ez a script csak felkínál egy első változatot, illetve továbbvezeti a meglévőt.

Mit csinál:
  - Végigolvassa egy vagy több epizód forrásnyelvi SRT-jét, és kigyűjti, melyik
    szereplő melyiket tegezi / magázza (a magyar tegezés/magázás a forrásból
    nem derül ki közvetlenül — a script a formalitás-jelekből következtet:
    megszólítások, rangok, honorifikumok, névhasználat, udvariassági fordulatok).
  - Több epizódnál összefésül: ha ugyanaz a pár az egyik részben magázódik, a
    másikban tegeződik, azt VÁLTÁS-jelöltként hozza fel, nem csendben felülírja.
  - A meglévő regisztert figyelembe veszi: a változatlan sorokat nem bántja,
    az ütközőket megkérdezi.
  - Az egyértelmű sorokat magától elfogadja, a bizonytalanoknál kérdez.

Használat:
    python register_extract.py "input/Sorozat - S01E01.eng.srt"
    python register_extract.py "input/S01E01.eng.srt" "input/S01E02.eng.srt"
    python register_extract.py "input/S01E01.eng.srt" --provider codex
    python register_extract.py "input/S01E01.eng.srt" --dry-run

Provider:
    --provider gemini   Gemini API (default) — .env-ben GEMINI_API_KEY,
                        pip install google-genai python-dotenv pydantic
    --provider claude   Claude Code CLI (`claude` parancs)
    --provider codex    Codex CLI (`codex` parancs)

Kimenet:
    A TRANSLATION.local.md "Megszólítási regiszter:" szakasza (előző állapot:
    TRANSLATION.local.md.bak). A pár-sorokat a script kezeli; az egyéb sorokat
    (alapértelmezés, váltás, megjegyzések) érintetlenül átmenti.
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from subtr import config
from subtr.providers.codex_cli import CodexRunError, find_codex, run_codex_json
from subtr.providers.claude_cli import extract_json, find_claude as find_claude_cli, run_prompt
from subtr.context import load_translation_context

LOCAL_FILE_DEFAULT = "TRANSLATION.local.md"
SECTION_HEADER = "Megszólítási regiszter:"
GEMINI_MODEL_DEFAULT = "gemini-3.6-flash"
FORMS = ("MAGÁZ", "TEGEZ")
MIN_EVIDENCE = 2   # ennyi idézhető bizonyíték alatt a sor bizonytalan

ARROW_ONE, ARROW_BOTH = "→", "↔"

# A pár-sorok mintája a TRANSLATION.local.md-ben
PAIR_RE = re.compile(
    r"^\s*-\s*(?P<a>[^:]+?)\s*(?P<arrow>→|->|↔|<->)\s*(?P<b>[^:]+?)\s*:\s*"
    r"(?P<form>MAGÁZ|TEGEZ)\s*(?:\((?P<note>.*)\))?\s*$"
)

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "string"},
                    "mutual": {"type": "boolean"},
                    "form": {"type": "string", "enum": list(FORMS)},
                    "confidence": {"type": "string", "enum": ["biztos", "bizonytalan"]},
                    "relation": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["a", "b", "mutual", "form", "confidence", "relation", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["relations"],
    "additionalProperties": False,
}


# ────────────────────────────────────────────────────────────────────────────
# SRT beolvasás
# ────────────────────────────────────────────────────────────────────────────

def srt_dialogue(path: str) -> str:
    """Az SRT-ből '#sorszám szöveg' sorok — időbélyeg nélkül, hogy a prompt
    rövidebb legyen. A beszélőcímkék ([Anna], (Hagi)) SZÁNDÉKOSAN maradnak:
    ezek az elsődleges támpont ahhoz, hogy ki beszél kihez."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    out = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [l.strip() for l in block.strip().split("\n") if l.strip()]
        if len(lines) >= 3 and lines[0].isdigit():
            text = " ".join(lines[2:])
            if text:
                out.append(f"#{lines[0]} {text}")
    return "\n".join(out)


# ────────────────────────────────────────────────────────────────────────────
# Meglévő regiszter beolvasása / írása
# ────────────────────────────────────────────────────────────────────────────

def parse_local(path: str):
    """Visszaad: (fájl szövege, pár-lista, egyéb regiszter-sorok, szakasz megvan-e).

    A pár-lista elemei: {a, b, mutual, form, note}. Az "egyéb sorok" (pl.
    'alapértelmezés idegenekkel: MAGÁZ', 'váltás: ...', megjegyzések) változatlanul
    visszakerülnek a fájlba — azokat nem a script kezeli."""
    if not os.path.isfile(path):
        return "", [], [], False
    text = Path(path).read_text(encoding="utf-8")
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip().startswith(SECTION_HEADER)), None)
    if start is None:
        return text, [], [], False

    pairs, others = [], []
    i = start + 1
    while i < len(lines):
        line = lines[i]
        # a szakasz addig tart, amíg behúzott vagy üres sorok jönnek
        if line.strip() and not line.startswith((" ", "\t")):
            break
        m = PAIR_RE.match(line)
        if m:
            pairs.append({
                "a": m.group("a").strip(),
                "b": m.group("b").strip(),
                "mutual": m.group("arrow") in (ARROW_BOTH, "<->"),
                "form": m.group("form"),
                "note": (m.group("note") or "").strip(),
            })
        elif line.strip():
            others.append(line.rstrip())
        i += 1
    return text, pairs, others, True


def render_section(pairs, others) -> str:
    lines = [f"{SECTION_HEADER}   (frissítendő MINDEN epizód előtt)"]
    for p in pairs:
        arrow = ARROW_BOTH if p["mutual"] else ARROW_ONE
        note = f"  ({p['note']})" if p.get("note") else ""
        lines.append(f"  - {p['a']} {arrow} {p['b']}: {p['form']}{note}")
    lines.extend(others)
    return "\n".join(lines)


def write_local(path: str, pairs, others):
    """A regiszter-szakasz cseréje/beszúrása, .bak mentéssel és atomikus írással."""
    text = Path(path).read_text(encoding="utf-8") if os.path.isfile(path) else ""
    section = render_section(pairs, others)
    lines = text.split("\n") if text else []
    start = next((i for i, l in enumerate(lines) if l.strip().startswith(SECTION_HEADER)), None)

    if start is None:
        new_text = (text.rstrip() + "\n\n" + section + "\n") if text.strip() else section + "\n"
    else:
        end = start + 1
        while end < len(lines):
            if lines[end].strip() and not lines[end].startswith((" ", "\t")):
                break
            end += 1
        new_text = "\n".join(lines[:start] + section.split("\n") + lines[end:])

    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    tmp = f"{path}.tmp.{os.getpid()}"
    Path(tmp).write_text(new_text.rstrip("\n") + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print(f"\nRegiszter mentve: {path} (előző állapot: {path}.bak)")


# ────────────────────────────────────────────────────────────────────────────
# Prompt
# ────────────────────────────────────────────────────────────────────────────

# Az angol felirat NEM jelöli a formalitást (`you` mindenre), ezért ott a
# regisztert közvetett jelekből kell kikövetkeztetni. A legtöbb más
# forrásnyelv viszont grammatikailag jelöli — ott a feladat leolvasás, nem
# következtetés, és a promptnak ezt kell mondania, különben a modell fölöslegesen
# találgat egy olyan szövegben, ami a választ már tartalmazza.
INDIRECT_CUES = """=== MIRE FIGYELJ ===
MAGÁZÁS felé mutat: `sir` / `ma'am`; `Mr.` / `Ms.` + vezetéknév; titulus + név
(`Director` / `Manager` / `Professor` / `CEO` / `Chairman`); emelt regiszter
(`may I`, `would you mind`, `I apologize`); első találkozás; hivatalos helyszín;
alárendelt → felettes irány.
TEGEZÉS felé mutat: keresztnév vagy becenév önmagában; `hey`, `dude`; szleng;
káromkodás; családtag fiatalabb felé; gyerekek egymás közt; felettes → beosztott.
AZ EREDETI NYELVBŐL ÁTVETT megszólítások a legerősebb jelek, ha bennmaradtak:
`-ssi`, `-nim`, `sunbae`, `hyung` / `unnie` / `oppa` / `noona`, `senpai`, `-san`.
FIGYELEM: a `hyung` / `oppa` közeli, de ASZIMMETRIKUS viszonyt jelöl — a
fiatalabb gyakran mégis udvarias formában beszél, ebből nem következik tegezés."""


HUNGARIAN_MARKER = ("Ön/ön, Maga/maga, Önök + 3. személyű igealak és birtokos "
                    "(pl. »Mit gondol?«, »az Ön lánya«) = MAGÁZ; te/ti, 2. személyű "
                    "igealak és birtokos (pl. »Mit gondolsz?«, »a lányod«) = TEGEZ; "
                    "felszólításnál »jöjjön« = MAGÁZ, »gyere« = TEGEZ")


def build_prompt(context: str, existing, dialogue: str, episode_label: str,
                 src_lang: str = config.DEFAULT_SOURCE_LANG,
                 hungarian: bool = False) -> str:
    """A regiszter-kinyerő prompt.

    hungarian=True: a `dialogue` nem forrásfelirat, hanem a KÉSZ MAGYAR
    fordítás (pl. más forrásból átvett korábbi részek) — ott a tegezés/magázás
    nem következtetés és nem is idegen nyelvű jel leolvasása, hanem maga a
    magyar igealak. A forrásnyelv ilyenkor nem számít."""
    existing_txt = "\n".join(
        f"  - {p['a']} {ARROW_BOTH if p['mutual'] else ARROW_ONE} {p['b']}: {p['form']}"
        for p in existing
    ) or "  (még nincs)"

    src = config.source_lang_name(src_lang)
    the_src = config.the_source_lang(src_lang)       # "az angol" / "a német"
    The_src = the_src.capitalize()                   # mondat elején
    marker = config.source_lang_formality(src_lang)

    if hungarian:
        src = "magyar (kész fordítás)"
        intro = f"""A megadott felirat NEM forrásnyelvi szöveg, hanem a sorozat korábbi
részeinek KÉSZ MAGYAR FORDÍTÁSA. A magyar nyelv jelöli a tegezést/magázást,
tehát a feladatod tiszta LEOLVASÁS: nézd meg, melyik szereplő melyiket hogyan
szólítja meg, és rögzítsd ugyanazt — ezt a regisztert kell a hátralévő
részeknek is tartaniuk.

=== MIRE FIGYELJ ===
A magyar igealak és névmás a bizonyíték: {HUNGARIAN_MARKER}.
Ahol ez látszik, ott ne mérlegelj mást, és az "evidence" mezőbe a magyar
sort idézd. Ne javíts és ne bírálj felül semmit: ha a fordítás egy párnál
következetlen, azt VÁLTÁS-ként vagy bizonytalanként jelezd, ne átlagold el —
a felhasználó dönti el, melyik alak a helyes.
A kikerülő (nem döntő) mondatok — főnévi igenév, többes szám első személy,
megszólítás nélküli felkiáltás — NEM bizonyítékok."""
    elif marker:
        intro = f"""A magyar nyelv megköveteli a tegezés/magázás döntést — és szerencsére
{the_src} forrás EZT MAGA IS JELÖLI: {marker}.
A feladatod elsősorban LEOLVASÁS, nem következtetés: nézd meg, a szereplők
milyen formában beszélnek egymáshoz a forrásban, és vidd át magyarra.

=== MIRE FIGYELJ ===
{The_src} formalitás-jelölése ({marker}) a LEGERŐSEBB bizonyíték — ahol ez
látszik, ott ne mérlegelj mást, és az "evidence" mezőbe ezt idézd.
Csak ott támaszkodj közvetett jelekre (titulus, megszólítási forma, emelt
regiszter, első találkozás, alá-fölérendeltség), ahol a szereplőpár között
egyetlen explicit alak sem hangzik el.
FIGYELEM: a formalitás-váltás önmagában is információ — ha egy páros a felirat
folyamán vált, azt VÁLTÁS-ként jelezd, ne átlagold el."""
    else:
        intro = f"""A magyar nyelv megköveteli a tegezés/magázás döntést, {the_src} felirat
viszont ezt nem jelöli (`you` mindenre). A feladatod: {the_src} szövegből kikövetkeztetni,
melyik szereplő melyiket TEGEZI és melyiket MAGÁZZA a magyar fordításban.

""" + INDIRECT_CUES

    return f"""Feliratfordítás előkészítése: MEGSZÓLÍTÁSI REGISZTERT állítasz össze.

{intro}

=== FONTOS SZABÁLYOK ===
- A viszony gyakran ASZIMMETRIKUS: a főnök tegez, a beosztott magáz. Ilyenkor
  KÉT külön sort adj vissza (mutual=false mindkettőnél), ne egyet.
- Csak akkor tegyél be egy párt, ha tényleg beszélnek egymással a feliratban.
- confidence="biztos" CSAK akkor, ha van konkrét, idézhető bizonyítékod.
  Ha a szövegből nem dönthető el, confidence="bizonytalan" — ezt a felhasználó
  fogja eldönteni, tehát a bizonytalanság megjelölése HASZNOS, nem hiba.
- Az "evidence" mezőbe konkrét sorszámot és rövid idézetet adj (pl.
  '#412 "Yes, sir."'), ne általánosságot. Bizonyíték nélkül ne állíts semmit.
- A "relation" rövid magyar leírás legyen (pl. "beosztott→főnök", "legjobb barátnők").
- A neveket úgy írd, ahogy a sorozatkontextusban szerepelnek.

=== SOROZAT KONTEXTUS ===
{context.strip()}

=== MÁR JÓVÁHAGYOTT REGISZTER (ezeket ne ismételd, csak ha ELLENTMOND a felirat) ===
{existing_txt}

=== {src.upper()} FELIRAT ({episode_label}) ===
{dialogue}
"""


# ────────────────────────────────────────────────────────────────────────────
# Providerek
# ────────────────────────────────────────────────────────────────────────────

def _validate(relations) -> list[dict]:
    out = []
    for r in relations or []:
        if not isinstance(r, dict):
            continue
        a, b = str(r.get("a", "")).strip(), str(r.get("b", "")).strip()
        form = str(r.get("form", "")).strip().upper()
        if not a or not b or a == b or form not in FORMS:
            continue
        ev = [str(e).strip() for e in (r.get("evidence") or []) if str(e).strip()][:4]
        conf = "biztos" if str(r.get("confidence", "")).strip().lower() == "biztos" else "bizonytalan"
        # Gépi fék: a modell önbevallásos magabiztossága nem szűr (tapasztalat
        # szerint mindent "biztos"-nak jelöl). Két független bizonyíték alatt
        # a sor bizonytalan, akármit is állít magáról — a felhasználó dönt.
        if len(ev) < MIN_EVIDENCE:
            conf = "bizonytalan"
        out.append({
            "a": a, "b": b,
            "mutual": bool(r.get("mutual")),
            "form": form,
            "confidence": conf,
            "relation": str(r.get("relation", "")).strip(),
            "evidence": ev,
        })
    return out


def run_gemini(prompt: str, model: str) -> list[dict]:
    """Gemini ág — a retry/kvóta logika a közös adapterben (subtr.providers.gemini)."""
    from subtr.providers import gemini as gemini_provider
    if not gemini_provider.DEPS_OK:
        print(f"HIBA: Hiányzó függőség: {gemini_provider.DEPS_ERROR}")
        print("      Telepítés: pip install google-genai python-dotenv pydantic")
        return []
    gemini_provider.preflight(model, needed=1)
    print(f"Gemini elemzi a feliratot... ({model})")
    try:
        client = gemini_provider.make_client()
    except RuntimeError as e:
        print(f"HIBA: {e}")
        return []
    parsed, err = gemini_provider.call_json(client, model, prompt,
                                            schema=RESULT_SCHEMA,
                                            temperature=0.2)
    if err:
        print(f"HIBA: Gemini API hiba: {err}")
        return []
    return _validate(parsed.get("relations"))


def run_codex(prompt: str, model, timeout: int) -> list[dict]:
    codex_cmd = find_codex()
    if not codex_cmd:
        print("HIBA: A 'codex' parancs nem található a PATH-on.")
        return []
    print(f"Codex elemzi a feliratot... ({codex_cmd})")
    try:
        result = run_codex_json(prompt, RESULT_SCHEMA, timeout=timeout,
                                model=model, codex_bin=codex_cmd)
    except CodexRunError as exc:
        print(f"HIBA: Codex hiba: {exc}")
        return []
    return _validate(result.get("relations"))


def run_claude(prompt: str, timeout: int) -> list[dict]:
    claude_cmd = find_claude_cli()
    print(f"Claude Code elemzi a feliratot... ({claude_cmd})")
    prompt += ('\n\nKIMENET: kizárólag egy JSON objektum, semmi más szöveg:\n'
               '{"relations":[{"a":"","b":"","mutual":false,"form":"MAGÁZ",'
               '"confidence":"biztos","relation":"","evidence":[""]}]}')
    raw, err = run_prompt(prompt, timeout, claude_bin=claude_cmd)
    if err:
        print(f"HIBA: {err}")
        return []

    parsed = extract_json(raw)
    if not isinstance(parsed, dict):
        # None (parse-hiba) VAGY tömb — a válasznak {"relations":[...]}
        # objektumnak kell lennie; a nyers választ megőrizzük.
        debug = ".register_extract_debug.txt"
        Path(debug).write_text(raw, encoding="utf-8")
        print(f"HIBA: JSON parse hiba (nem objektum a válasz)\n  Nyers válasz mentve: {debug}")
        return []
    return _validate(parsed.get("relations"))


# ────────────────────────────────────────────────────────────────────────────
# Összefésülés
# ────────────────────────────────────────────────────────────────────────────

def key_of(r) -> tuple:
    """Kölcsönös viszonynál a sorrend ne számítson; egyirányúnál számít."""
    return ("<->", *sorted((r["a"], r["b"]))) if r["mutual"] else ("->", r["a"], r["b"])


def merge_episodes(per_episode: list[tuple]) -> list[dict]:
    """Epizódonkénti találatok összefésülése.

    Ha ugyanaz a pár két epizódban MÁS formát kap, az VÁLTÁS-jelölt: nem
    csendben felülírjuk, hanem bizonytalanná tesszük és megjelöljük, hol
    fordul a viszony — pont ezt kell a regiszter 'váltás' sorába írni."""
    merged = {}
    for label, relations in per_episode:
        for r in relations:
            k = key_of(r)
            cur = merged.get(k)
            if cur is None:
                merged[k] = dict(r, episodes={label: r["form"]},
                                 evidence=[f"[{label}] {e}" for e in r["evidence"]])
                continue
            cur["episodes"][label] = r["form"]
            cur["evidence"] = (cur["evidence"] + [f"[{label}] {e}" for e in r["evidence"]])[:6]
            if cur["form"] != r["form"]:
                cur["switch"] = True
                cur["confidence"] = "bizonytalan"
                cur["form"] = r["form"]  # a későbbi epizód formája a javaslat
            elif r["confidence"] == "biztos":
                cur["confidence"] = "biztos"
    return list(merged.values())


def diff_against_existing(found, existing):
    """(új, ütköző, változatlan) — az ütközőt mindig meg kell kérdezni."""
    by_key = {key_of(p): p for p in existing}
    new, conflict, same = [], [], []
    for r in found:
        cur = by_key.get(key_of(r))
        if cur is None:
            new.append(r)
        elif cur["form"] == r["form"]:
            same.append(r)
        else:
            conflict.append(dict(r, previous=cur["form"]))
    return new, conflict, same


# ────────────────────────────────────────────────────────────────────────────
# Interaktív jóváhagyás
# ────────────────────────────────────────────────────────────────────────────

def describe(r) -> str:
    arrow = ARROW_BOTH if r["mutual"] else ARROW_ONE
    return f"{r['a']} {arrow} {r['b']}: {r['form']}"


def other_form(form: str) -> str:
    return FORMS[0] if form == FORMS[1] else FORMS[1]


def ask(r, reason: str):
    """Visszaad: (döntés, rekord). Döntés: 'accept' | 'skip' | 'quit'."""
    print(f"\n{'-' * 58}")
    print(f"  {reason}: {describe(r)}")
    if r.get("relation"):
        print(f"  viszony:    {r['relation']}")
    if r.get("previous"):
        print(f"  eddig:      {r['previous']}  →  javasolt: {r['form']}")
    if r.get("switch"):
        eps = ", ".join(f"{k}={v}" for k, v in r.get("episodes", {}).items())
        print(f"  VÁLTÁS?     epizódonként eltér: {eps}")
        print(f"              ha tényleg váltás, a 'váltás:' sorba írd be kézzel")
    for e in r.get("evidence", []):
        print(f"  bizonyíték: {e}")
    while True:
        choice = input(f"  [y] elfogad  [m] {other_form(r['form'])} helyette  "
                       f"[n] kihagy  [e] szerkeszt  [q] kilép: ").strip().lower()
        if choice in ("y", ""):
            return "accept", r
        if choice == "m":
            return "accept", dict(r, form=other_form(r["form"]))
        if choice == "n":
            return "skip", r
        if choice == "q":
            return "quit", r
        if choice == "e":
            note = input(f"  viszony leírása [{r.get('relation','')}]: ").strip()
            form = input(f"  forma (MAGÁZ/TEGEZ) [{r['form']}]: ").strip().upper()
            return "accept", dict(r,
                                  relation=note or r.get("relation", ""),
                                  form=form if form in FORMS else r["form"])
        print("  Érvénytelen. y / m / n / e / q")


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Megszólítási regiszter kinyerése a forrásfeliratból (opcionális lépés)")
    parser.add_argument("srt", nargs="+",
                        help="Egy vagy több forrásnyelvi SRT (több rész = pontosabb)")
    config.add_source_lang_argument(parser)
    parser.add_argument("--hungarian", action="store_true",
                        help="A megadott fájl(ok) a KÉSZ MAGYAR fordítás (pl. más forrásból "
                             "átvett korábbi részek): a tegezés/magázás közvetlenül a magyar "
                             "igealakból olvasódik le, a forrásnyelv nem számít")
    parser.add_argument("--provider", choices=("gemini", "claude", "codex"),
                        default=config.default_provider(builtin="gemini"),
                        help="Kinyerő provider (default: gemini, "
                             "felülírható: SUBTR_DEFAULT_PROVIDER env)")
    parser.add_argument("--model", help="Modellazonosító (gemini/codex)")
    parser.add_argument("--local-file", default=LOCAL_FILE_DEFAULT,
                        help=f"A regisztert tartalmazó fájl (default: {LOCAL_FILE_DEFAULT})")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Claude/Codex timeout másodpercben (default: 300)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Csak kiírja a javasolt regisztert, nem ír fájlba")
    parser.add_argument("--all-interactive", action="store_true",
                        help="Minden párnál kérdezzen, ne csak a bizonytalanoknál")
    parser.add_argument("--yes", action="store_true",
                        help="Ne kérdezzen: csak a biztos sorokat veszi át, a többit kihagyja")
    args = parser.parse_args()

    missing = [p for p in args.srt if not os.path.isfile(p)]
    if missing:
        for p in missing:
            print(f"HIBA: Nem találom a fájlt: {p}")
        sys.exit(1)
    if args.all_interactive and args.yes:
        print("HIBA: A --yes és a --all-interactive kizárja egymást.")
        sys.exit(1)

    context = load_translation_context()
    _, existing, others, has_section = parse_local(args.local_file)
    print(f"Meglévő regiszter: {len(existing)} pár "
          f"({'szakasz megvan' if has_section else 'még nincs szakasz'}) — {args.local_file}")

    model = config.resolve_model(args.model, args.provider, "register",
                                 builtin=GEMINI_MODEL_DEFAULT if args.provider == "gemini" else None)
    per_episode = []
    for path in args.srt:
        label = Path(path).stem
        dialogue = srt_dialogue(path)
        if not dialogue:
            print(f"FIGYELEM: {label} — nem találtam feliratszöveget, kihagyom.")
            continue
        src_lang = config.resolve_source_lang(args.source_lang, path)
        lang_label = "magyar — kész fordítás" if args.hungarian else config.source_lang_name(src_lang)
        print(f"\n=== {label} ({dialogue.count(chr(10)) + 1} sor, {lang_label})")
        prompt = build_prompt(context, existing, dialogue, label, src_lang,
                              hungarian=args.hungarian)
        if args.provider == "gemini":
            rel = run_gemini(prompt, model)
        elif args.provider == "codex":
            rel = run_codex(prompt, model, args.timeout)
        else:
            rel = run_claude(prompt, args.timeout)
        print(f"  {len(rel)} viszony")
        per_episode.append((label, rel))

    found = merge_episodes(per_episode)
    if not found:
        print("\nNem találtam megszólítási viszonyt. A regisztert kézzel is megírhatod.")
        return

    new, conflict, same = diff_against_existing(found, existing)
    print(f"\n{'=' * 58}")
    print(f"  {len(new)} új, {len(conflict)} ütköző, {len(same)} változatlan viszony")
    print(f"{'=' * 58}")

    accepted, auto = [], []
    for r in new:
        # Az ütközőt és a bizonytalant mindig megkérdezzük; a biztosat csak
        # --all-interactive esetén. A --yes a bizonytalanokat kihagyja.
        needs_ask = args.all_interactive or r["confidence"] != "biztos" or r.get("switch")
        if not needs_ask:
            auto.append(r)
            accepted.append(r)
            continue
        if args.yes:
            continue
        decision, rec = ask(r, "BIZONYTALAN" if r["confidence"] != "biztos" else "ÚJ")
        if decision == "quit":
            print("\nMegszakítva — a fájl nem módosult.")
            return
        if decision == "accept":
            accepted.append(rec)

    for r in conflict:
        if args.yes:
            continue
        decision, rec = ask(r, "ÜTKÖZIK A MEGLÉVŐVEL")
        if decision == "quit":
            print("\nMegszakítva — a fájl nem módosult.")
            return
        if decision == "accept":
            accepted.append(rec)

    if auto:
        print(f"\nAutomatikusan elfogadva ({len(auto)} biztos viszony):")
        for r in auto:
            print(f"  - {describe(r)}" + (f"  ({r['relation']})" if r.get("relation") else ""))
            for e in r.get("evidence", [])[:2]:
                print(f"      {e}")

    if not accepted:
        print("\nNincs átvezetendő változás.")
        return

    # Beolvasztás: az elfogadottak felülírják az azonos kulcsú meglévőt
    by_key = {key_of(p): p for p in existing}
    for r in accepted:
        by_key[key_of(r)] = {"a": r["a"], "b": r["b"], "mutual": r["mutual"],
                             "form": r["form"], "note": r.get("relation", "")}
    final = list(by_key.values())

    print(f"\n{'=' * 58}\nJavasolt regiszter ({len(final)} pár):\n{'=' * 58}")
    print(render_section(final, others))

    if args.dry_run:
        print("\n--dry-run: a fájl NEM módosult. Másold be kézzel, amit megtartanál.")
        return
    write_local(args.local_file, final, others)
    print("Ellenőrizd a fájlt — a regiszter kézzel bármikor javítható.")


if __name__ == "__main__":
    main()
