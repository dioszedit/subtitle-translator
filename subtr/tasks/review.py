"""Review-task — a lektorálási logika provider-függetlenül, EGY példányban.

A refaktor előtt három külön script élt (review_with_claude/gemini/codex),
a forrás-párosítás és a lektor-prompt törzse két teljes másolatban. Itt:

  - a forrás-párosítás (check_source_alignment, attach_source, ...) egy helyen,
  - a lektor system prompt EGY példányban (a json_output kapcsoló hordozza a
    két tudatos provider-eltérést: a JSON kimeneti blokk és a [FORRÁS]-mondat
    megfogalmazása),
  - a chunk-ciklus + riportírás közös, a provider csak egy "executor" closure:
    (chunk_text, i, total) -> (normalizált findings-lista | None, hibaüzenet).

A gyökér review_with_*.py fájlok vékony wrapperek a main(provider) fölött.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from subtr import config, reports
from subtr.context import load_translation_context
from subtr.glossary import as_prompt_text
from subtr.providers import claude_cli
from subtr.providers import codex_cli
from subtr.providers import gemini as gemini_provider
from subtr.srt import parse_by_index, parse_entries

DEFAULT_CHUNK_SIZE = 100
TEMPERATURE = 0.2
MAX_RETRIES = 4                 # Gemini-ág (a backoff az adapterben)
CLAUDE_TIMEOUT_PER_CHUNK = 600  # 10 perc chunkonként
CLAUDE_SYS_PROMPT_PREFIX = ".review_claude_sys_prompt_"

# Beégetett modell-defaultok — a .env (SUBTR_<P>_MODEL_REVIEW / SUBTR_<P>_MODEL)
# és a --model kapcsoló a config.resolve_model() precedenciája szerint felülbírálja.
MODEL_BUILTIN = {"gemini": "gemini-3.6-flash", "claude": "sonnet", "codex": None}

DESCRIPTION = {
    "claude": "Magyar fordítás review Claude-dal",
    "gemini": "Magyar fordítás review Gemini-vel",
    "codex": "Magyar SRT review Codex CLI-vel",
}

# Codex strict séma (a Gemini-adapter ugyanennek az additionalProperties
# nélküli változatát használná — de a Gemini-ág pydantic sémával megy)
CODEX_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sorszam": {"type": "integer"}, "eredeti": {"type": "string"},
                    "hiba": {"type": "string"}, "javaslat": {"type": "string"},
                },
                "required": ["sorszam", "eredeti", "hiba", "javaslat"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["errors"],
    "additionalProperties": False,
}

# Pydantic séma a Gemini structured outputhoz — lazy, hogy a --help
# függőségek nélkül is fusson.
try:
    from pydantic import BaseModel

    class ReviewError(BaseModel):
        sorszam: int
        eredeti: str
        hiba: str
        javaslat: str

    class ErrorReport(BaseModel):
        errors: list[ReviewError]
except ImportError:
    ErrorReport = None


# ────────────────────────────────────────────────────────────────────────────
# Forrás-párosítás (korábban 2 azonos másolat + 1 import)
# ────────────────────────────────────────────────────────────────────────────

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


# ────────────────────────────────────────────────────────────────────────────
# Lektor system prompt — EGY példányban
# ────────────────────────────────────────────────────────────────────────────

def build_system_instruction(claude_md: str, glossary: str,
                             has_source: bool = False,
                             json_output: bool = True) -> str:
    """A lektor-prompt. json_output=True a strukturált (Gemini/Codex) ág:
    tartalmazza a === KIMENET === blokkot, és a [FORRÁS]-mondat a "eredeti"
    MEZŐRŐL beszél; json_output=False (Claude CLI) a szöveges ág: a kimeneti
    formátumot a per-chunk prompt írja le, a mondat az idézett szövegről szól."""
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
6. Tegezés/magázás AKKOR ÉS CSAK AKKOR, ha valamelyik feltétel teljesül:
   (a) a sorozatkontextus Megszólítási regisztere mást ír elő a szereplőpárra,
   (b) a [FORRÁS] sor explicit formalitás-jelet tartalmaz (megszólítási forma,
       rang/titulus, udvariassági fordulat), amivel a magyar forma ütközik,
   (c) a blokkon belül ugyanaz a szereplőpár váltogatja a formát ÉS a beszélő a
       szövegből azonosítható (elhangzó név, megszólítás, beszélőcímke vagy
       [FORRÁS]-jel alapján).
   Ilyen találatnál a "hiba" mező NEVEZZE MEG, mire hivatkozol: melyik
   regiszter-sorra, melyik idézett forrás-jelre, vagy melyik másik sorszámmal
   ütközik. Indoklás nélküli tegezés/magázás-találatot ne adj.

=== AMIT NE JELENTS ===
- Helyesírás apróságok (azokat a helyesírás-ellenőrző elkapja)
- Stilisztikai ízlésváltozatok, ha az adott fordítás is helyes
- HTML tagek, időbélyegek, sorszámok
- A szójegyzékben (lent) szereplő fordításokat NE javasold átírni —
  ezek a sorozat kötelező, jóváhagyott fordításai
- Karakterneveket NE javasold lefordítani (a szójegyzékben szerepelnek)
- Tegezés/magázás váltást NE javasolj "érzésre", ha a fenti (a)/(b)/(c)
  feltételek egyike sem áll fenn
- A semleges, formát nem eldöntő megfogalmazás (T/1, főnévi igenév,
  személytelen szerkezet) HELYES megoldás — ne javasolj helyette konkrét
  tegező vagy magázó alakot"""]

    if has_source:
        if json_output:
            forras_zaras = """- A [FORRÁS] sor csak kontextus: a "eredeti" mezőbe MINDIG a magyar szöveg
  kerüljön, a [FORRÁS] sort ne idézd bele és ne javasold módosítani."""
        else:
            forras_zaras = """- A [FORRÁS] sor csak kontextus: az idézett "eredeti" szöveg MINDIG a magyar
  legyen, a [FORRÁS] sort ne idézd bele és ne javasold módosítani."""
        parts.append("""=== FORRÁSNYELVI EREDETI ===
A legtöbb szekció után egy [FORRÁS] sor áll: ez a FORRÁSNYELVI EREDETI, amiből
a magyar fordítás készült. Ez a viszonyítási alap:
- Jelezd, ha a magyar mást mond, mint a forrás (félrefordítás,
  kimaradt/hozzáköltött tartalom, tagadás/idő/szám/személy eltérés).
- NE jelents hibát, ha a forrás igazolja a magyar megoldást —
  ami forrás nélkül furcsának tűnne, a forrás ismeretében gyakran helyes.
""" + forras_zaras)

    if json_output:
        parts.append("""=== KIMENET ===
JSON séma szerint, minden hibához:
- sorszam: a felirat szekció sorszáma (egész szám)
- eredeti: az eredeti magyar szöveg (ahogy az SRT-ben van)
- hiba: rövid leírás a problémáról
- javaslat: javított magyar változat

Ha nincs hiba, üres errors tömböt adj vissza.""")

    if claude_md.strip():
        parts.append("=== SOROZAT KONTEXTUS (CLAUDE.md) ===\n" + claude_md.strip())

    if glossary.strip():
        parts.append(
            "=== SZÓJEGYZÉK — EZEK A FORDÍTÁSOK HELYESEK, NE JAVASOLJ MÁST! ===\n"
            + glossary.strip()
        )

    return "\n\n".join(parts)


def build_prompt(chunk_text, chunk_num, total_chunks):
    """Per-chunk prompt (Gemini) — minimális, a szabályok a system instruction-ben."""
    return f"""SRT BLOKK ({chunk_num}/{total_chunks}):
{chunk_text}
"""


# ────────────────────────────────────────────────────────────────────────────
# Claude CLI segédek
# ────────────────────────────────────────────────────────────────────────────

def parse_json_findings(result):
    """A Claude válaszából kinyeri a hibalistát (JSON tömb).

    Vissza: lista (üres = nincs hiba), vagy None, ha a válasz nem
    értelmezhető — azt a hívó hibás chunkként kezeli, a nyers szöveg
    megőrzésével, hogy találat ne veszhessen el.
    """
    m = re.search(r"\[.*\]", result, re.S)
    if not m:
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


def _claude_chunk_prompt(chunk_text, chunk_num, total_chunks):
    return f"""Lektoráld az alábbi SRT felirat blokkot a system promptban
megadott szabályok szerint. A válaszod KIZÁRÓLAG egy JSON tömb legyen,
minden hibához egy objektum, pontosan ezekkel a kulcsokkal:

[{{"sorszam": 12, "eredeti": "az eredeti magyar szöveg", "hiba": "rövid leírás", "javaslat": "javított magyar változat"}}]

Ha nincs hiba ebben a chunkban, üres tömböt adj vissza: []
Semmilyen egyéb szöveget, magyarázatot vagy markdown-kerítést ne írj.

SRT BLOKK ({chunk_num}/{total_chunks}):
{chunk_text}
"""


# ────────────────────────────────────────────────────────────────────────────
# Provider-executorok: (chunk_text, i, total) -> (findings | None, hiba | None)
# ────────────────────────────────────────────────────────────────────────────

def _make_gemini_executor(client, model, instruction):
    def executor(chunk_text, i, total):
        parsed, err = gemini_provider.call_json(
            client, model, build_prompt(chunk_text, i, total),
            schema=ErrorReport, system=instruction,
            temperature=TEMPERATURE, max_retries=MAX_RETRIES)
        if err:
            return None, err
        return [{"sorszam": e.sorszam, "eredeti": e.eredeti,
                 "hiba": e.hiba, "javaslat": e.javaslat}
                for e in parsed.errors], None
    return executor


def _make_claude_executor(claude_bin, sys_prompt_path, model):
    def executor(chunk_text, i, total):
        prompt = _claude_chunk_prompt(chunk_text, i, total)
        # A prompt STDIN-en megy át, nem argumentumként: Windows-on a
        # parancssor 32 KB-os limitje nagy chunkoknál elhasalna.
        try:
            proc = subprocess.run(
                [claude_bin, "-p",
                 "--append-system-prompt-file", sys_prompt_path,
                 "--allowedTools", "",
                 "--model", model],
                input=prompt, capture_output=True, text=True,
                timeout=CLAUDE_TIMEOUT_PER_CHUNK, encoding="utf-8")
        except subprocess.TimeoutExpired:
            return None, f"[TIMEOUT a chunkban {i} ({CLAUDE_TIMEOUT_PER_CHUNK // 60} perc)]"
        except FileNotFoundError:
            print("HIBA: A 'claude' parancs nem található!")
            sys.exit(1)
        if proc.returncode != 0:
            return None, f"[HIBA a chunkban {i}]: exit code {proc.returncode}\n{proc.stderr}"
        findings = parse_json_findings(proc.stdout.strip())
        if findings is None:
            # Nem értelmezhető válasz — a nyers szöveget megőrizzük,
            # hogy esetleges találat ne veszhessen el.
            return None, ("[Nem JSON válasz — nyers kimenet megőrizve:]\n"
                          + proc.stdout.strip())
        return findings, None
    return executor


def _make_codex_executor(codex_bin, model, instruction, timeout, retries):
    def executor(chunk_text, i, total):
        prompt = f"{instruction}\n\n=== REVIEW BLOKK ({i}/{total}) ===\n{chunk_text}"
        error = None
        for attempt in range(1, retries + 1):
            try:
                parsed = codex_cli.run_codex_json(prompt, CODEX_REVIEW_SCHEMA,
                                                  timeout=timeout, model=model,
                                                  codex_bin=codex_bin)
                findings = []
                for item in parsed.get("errors", []):
                    if not isinstance(item, dict):
                        continue
                    if not isinstance(item.get("sorszam"), int):
                        continue
                    findings.append(
                        {key: str(item.get(key, ""))
                         for key in ("eredeti", "hiba", "javaslat")}
                        | {"sorszam": item["sorszam"]})
                return findings, None
            except codex_cli.CodexRunError as exc:
                error = str(exc)
                if attempt < retries:
                    print(f"  Codex hiba, újrapróbálás ({attempt}/{retries})...")
        return None, error
    return executor


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────

def main(provider: str):
    builtin = MODEL_BUILTIN[provider]
    parser = argparse.ArgumentParser(description=DESCRIPTION[provider])
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Feliratok chunkonként (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--model", type=str, default=None,
                        help=config.model_help(provider, "review", builtin))
    if provider == "codex":
        parser.add_argument("--timeout", type=int, default=900,
                            help="Timeout chunkonként mp-ben")
        parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="Csak ettől a chunktól kezdje (1-alapú). Default: 1")
    parser.add_argument("--end-chunk", type=int, default=None,
                        help="Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó")
    parser.add_argument("--suffix", type=str, default="",
                        help="Riport fájl utótag, pl. '_part2' → _REVIEW_...:_part2.txt")
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

    model = config.resolve_model(args.model, provider, "review", builtin=builtin)

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    # Provider-előfeltételek
    claude_bin = codex_bin = client = None
    if provider == "gemini":
        if not gemini_provider.DEPS_OK:
            print(f"HIBA: Hiányzó Python függőség: {gemini_provider.DEPS_ERROR}")
            print(f"      Telepítés: pip install google-genai python-dotenv pydantic")
            sys.exit(1)
        try:
            client = gemini_provider.make_client()
        except RuntimeError as e:
            print(f"HIBA: {e}")
            sys.exit(1)
        # Pre-flight: ellenőrizzük, hogy a modell létezik-e.
        # Csak a 404 jelent rossz modellnevet — kvótahiba (429) vagy átmeneti
        # 5xx esetén félrevezető lenne "nem létező modell"-t mondani.
        try:
            client.models.get(model=model)
        except gemini_provider.genai_errors.APIError as e:
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            if status == 404:
                print(f"HIBA: Nem létező Gemini modell: '{model}'")
                print(f"      A használható modellek listája:")
                print(f"      https://ai.google.dev/gemini-api/docs/models")
            else:
                print(f"HIBA: Gemini API hiba a modell-ellenőrzésnél ({status}): {e}")
                print(f"      (Kvóta / átmeneti hiba lehet — próbáld később.)")
            sys.exit(1)
    elif provider == "claude":
        claude_bin = claude_cli.which_claude()
        if not claude_bin:
            print("HIBA: A 'claude' parancs nem található a PATH-on!")
            print("      Telepítés: npm install -g @anthropic-ai/claude-code")
            sys.exit(1)
    elif provider == "codex":
        codex_bin = codex_cli.find_codex()
        if not codex_bin:
            print("HIBA: A 'codex' parancs nem található a PATH-on.")
            sys.exit(1)

    entries = parse_entries(srt_path)
    print(f"Beolvasva: {len(entries)} felirat szekció")

    # Forrásnyelvi SRT párosítása (kevesebb téves találat)
    has_source = False
    if not args.no_source:
        src_path = Path(args.source) if args.source else find_source_srt(srt_path)
        if args.source and not src_path.is_file():
            print(f"HIBA: forrás SRT nem található: {src_path}")
            sys.exit(1)
        if src_path:
            src_map = parse_by_index(src_path)
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
    print(f"Modell: {model or 'provider-alapértelmezés'}")

    # Kontextus + lektor-prompt
    claude_md = load_translation_context()
    glossary = as_prompt_text()
    instruction = build_system_instruction(claude_md, glossary, has_source,
                                           json_output=(provider != "claude"))
    print(f"System instruction: {len(instruction)} char "
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

    if provider == "gemini":
        # Kvóta-előrejelzés: a Gemini API nem adja vissza a maradékot, ezért
        # helyi (gépszintű, kulcs szerinti) könyvelésből becsüljük meg, hogy
        # a most következő (end - start + 1) kérés belefér-e a napi limitbe.
        gemini_provider.preflight(model, needed=end - start + 1)
    print()

    report_path, json_path = reports.report_paths(srt_path, provider, args.suffix)

    # Felülírás-védelem: rész-tartomány futtatása suffix nélkül letörölné
    # a korábbi teljes riportot (pl. chunk 1-8 találatai vesznének el).
    if (start > 1 or end < total_chunks) and not args.suffix and report_path.exists():
        print(f"HIBA: Létező riport ({report_path.name}) + rész-tartomány futtatás.")
        print("      A futás felülírná a teljes korábbi riportot!")
        print("      Adj meg --suffix _part2 (vagy hasonló) utótagot.")
        sys.exit(1)

    # Executor összeállítása
    if provider == "gemini":
        executor = _make_gemini_executor(client, model, instruction)
    elif provider == "claude":
        sys_prompt_path = claude_cli.write_sys_prompt_file(
            instruction, CLAUDE_SYS_PROMPT_PREFIX)
        executor = _make_claude_executor(claude_bin, sys_prompt_path, model)
    else:
        executor = _make_codex_executor(codex_bin, model, instruction,
                                        args.timeout, args.max_retries)

    finding_blocks, json_findings, error_chunks = [], [], []
    for i in range(start, end + 1):
        chunk_text = "\n\n".join(chunks[i - 1])
        print(f"[{i}/{total_chunks}] Ellenőrzés folyamatban...")
        findings, err_msg = executor(chunk_text, i, total_chunks)
        if err_msg:
            error_chunks.append(f"--- Chunk {i}/{total_chunks} ---\n{err_msg}\n")
            print(f"  {err_msg.splitlines()[0]}")
            continue
        block = reports.format_findings(findings, i, total_chunks)
        if block:
            finding_blocks.append(block)
        for err in findings:
            json_findings.append({**err, "chunk": i})

    reports.write_reports(srt_path, report_path, json_path,
                          reviewer=provider,
                          model_label=model or "default",
                          finding_blocks=finding_blocks,
                          json_findings=json_findings,
                          error_chunks=error_chunks)

    # A codex-review kontraktusa: hibás chunk esetén nem-nulla exit kód
    if provider == "codex" and error_chunks:
        sys.exit(1)
