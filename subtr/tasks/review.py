"""Review-task — a lektorálási logika provider-függetlenül, EGY példányban.

A refaktor előtt három külön script élt (review_with_claude/gemini/codex),
a forrás-párosítás és a lektor-prompt törzse két teljes másolatban. Itt:

  - a forrás-párosítás (check_source_alignment, attach_source, ...) egy helyen,
  - a lektor system prompt EGY példányban (a json_output kapcsoló hordozza a
    két tudatos provider-eltérést: a JSON kimeneti blokk és a [FORRÁS]-mondat
    megfogalmazása),
  - a chunk-ciklus + riportírás közös, a provider csak egy "executor" closure:
    (chunk_text, i, total) -> (normalizált findings-lista | None, hibaüzenet).

Belépési pont: `subtr.py review [--provider claude|gemini|codex|grok]`.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from subtr import config, reports
from subtr.config import PROVIDERS
from subtr.context import load_translation_context
from subtr.glossary import as_prompt_text
from subtr.providers import claude_cli
from subtr.providers import codex_cli
from subtr.providers import gemini as gemini_provider
from subtr.providers import grok_cli
from subtr.srt import parse_by_index, parse_entries

DEFAULT_CHUNK_SIZE = 100
TEMPERATURE = 0.2
MAX_RETRIES = 4                 # Gemini-ág (a backoff az adapterben)
CLAUDE_TIMEOUT_PER_CHUNK = 600  # 10 perc chunkonként
CLAUDE_SYS_PROMPT_PREFIX = ".review_claude_sys_prompt_"

# Beégetett modell-defaultok — a .env (SUBTR_<P>_MODEL_REVIEW / SUBTR_<P>_MODEL)
# és a --model kapcsoló a config.resolve_model() precedenciája szerint felülbírálja.
MODEL_BUILTIN = {"gemini": "gemini-3.6-flash", "claude": "sonnet",
                 "codex": None, "grok": "grok-4.6"}

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


def find_source_srt(hun_path: Path, src_lang: str = None):
    """A forrásnyelvi SRT automatikus megkeresése a .hun.srt névből.

    A `.hun.` tagot cseréli a forrásnyelv kódjára (`.eng.`, `.ger.` …).
    Ha a megadott nyelvvel nincs találat — vagy nem is kaptunk nyelvet —,
    végigpróbálja az összes ismert nyelvkódot, mert a magyar fájl neve nem
    árulja el, milyen nyelvből készült. Több találatnál az elsőt adja vissza;
    ilyenkor a hívó a --source kapcsolóval dönthet.
    """
    if ".hun." not in hun_path.name:
        return None

    ordered = [c for c in (src_lang,) if c] + [
        c for c in config.SOURCE_LANGS if c != src_lang]
    for code in ordered:
        src_name = hun_path.name.replace(".hun.", f".{code}.")
        for cand in (Path("input") / src_name,
                     hun_path.parent / src_name,
                     hun_path.parent.parent / "input" / src_name):
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
                             json_output: bool = True,
                             src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    """A lektor-prompt. json_output=True a strukturált (Gemini/Codex) ág:
    tartalmazza a === KIMENET === blokkot, és a [FORRÁS]-mondat a "eredeti"
    MEZŐRŐL beszél; json_output=False (Claude CLI) a szöveges ág: a kimeneti
    formátumot a per-chunk prompt írja le, a mondat az idézett szövegről szól."""
    src = config.source_lang_name(src_lang)
    marker = config.source_lang_formality(src_lang)
    # Ahol a forrásnyelv grammatikailag jelöli a formalitást, ott a lektornak
    # megmondjuk, MIT keressen — így a (b) feltétel nem "érzés", hanem idézhető.
    formality_hint = ("" if not marker else
                      f"\n       {config.the_source_lang(src_lang)} forrásban ez konkrétan: {marker};")
    parts = [f"""=== SZEREP ===
Magyar fordítás lektor vagy. {src.capitalize()} nyelvű forrásból magyarra
fordított SRT feliratokat nézel át, és STÍLUS / NYELVTANI hibákat keresel.

=== AMIT KERESEL ===
1. Tükörfordítások (pl. "framed me" → "kereteztek be" helyett "tőrbe csaltak")
2. Helytelen igeragozás (pl. ikes igék, "tetszesz" helyett "tetszel")
3. Nemhez kötött kifejezések hibái (pl. "férjhez megy" férfiról; alapból
   semleges forma kell, csak ha BIZTOSAN ismert a beszélő/alany neme)
4. Természetellenes magyar nyelvezet — a forrásnyelv mondatszerkezetét
   másoló, magyarul idegenül hangzó megoldások
5. Rossz szórend, helytelen határozott/határozatlan ragozás
6. Tegezés/magázás AKKOR ÉS CSAK AKKOR, ha valamelyik feltétel teljesül:
   (a) a sorozatkontextus Megszólítási regisztere mást ír elő a szereplőpárra,
   (b) a [FORRÁS] sor explicit formalitás-jelet tartalmaz (megszólítási forma,
       rang/titulus, udvariassági fordulat), amivel a magyar forma ütközik,{formality_hint}
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

def _make_gemini_executor(client, model, instruction, max_retries=MAX_RETRIES):
    def executor(chunk_text, i, total):
        parsed, err = gemini_provider.call_json(
            client, model, build_prompt(chunk_text, i, total),
            schema=ErrorReport, system=instruction,
            temperature=TEMPERATURE, max_retries=max_retries)
        if err:
            return None, err
        return [{"sorszam": e.sorszam, "eredeti": e.eredeti,
                 "hiba": e.hiba, "javaslat": e.javaslat}
                for e in parsed.errors], None
    return executor


def _make_claude_executor(claude_bin, sys_prompt_path, model,
                          timeout=CLAUDE_TIMEOUT_PER_CHUNK):
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
                timeout=timeout, encoding="utf-8")
        except subprocess.TimeoutExpired:
            return None, f"[TIMEOUT a chunkban {i} ({timeout // 60} perc)]"
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


def _make_grok_executor(grok_bin, model, instruction, timeout, retries):
    def executor(chunk_text, i, total):
        prompt = f"{instruction}\n\n=== REVIEW BLOKK ({i}/{total}) ===\n{chunk_text}"
        error = None
        for attempt in range(1, retries + 1):
            try:
                parsed = grok_cli.run_grok_json(prompt, CODEX_REVIEW_SCHEMA,
                                                timeout=timeout, model=model,
                                                grok_bin=grok_bin)
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
            except grok_cli.GrokRunError as exc:
                error = str(exc)
                if attempt < retries:
                    print(f"  Grok hiba, újrapróbálás ({attempt}/{retries})...")
        return None, error
    return executor


# ────────────────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    # Windows cp125x konzolon a ✓/⚠/ő és a box-karakterek elszállnának
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Magyar fordítás stilisztikai review (Gemini API / Claude Code / Codex CLI / Grok CLI)")
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--provider", choices=PROVIDERS,
                        default=config.default_provider(builtin="gemini"),
                        help="Lektor provider (default: gemini, "
                             "felülírható: SUBTR_DEFAULT_PROVIDER env)")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Feliratok chunkonként (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--model", type=str, default=None,
                        help="Modell-azonosító. Feloldás: --model > "
                             "SUBTR_<PROVIDER>_MODEL_REVIEW > SUBTR_<PROVIDER>_MODEL > "
                             "beégetett (gemini: gemini-3.6-flash, claude: sonnet, grok: grok-4.6)")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Timeout chunkonként mp-ben (default: claude 600, codex/grok 900; "
                             "a gemini-ágon nem használt)")
    parser.add_argument("--max-retries", type=int, default=None,
                        help="Újrapróbálkozások (default: gemini 4, codex/grok 2; a claude-ágon "
                             "nem használt)")
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="Csak ettől a chunktól kezdje (1-alapú). Default: 1")
    parser.add_argument("--end-chunk", type=int, default=None,
                        help="Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó")
    parser.add_argument("--suffix", type=str, default="",
                        help="Riport fájl utótag, pl. '_part2' → _REVIEW_GEMINI_part2.txt")
    config.add_source_lang_argument(parser)
    parser.add_argument("--source", "--english", type=str, default=None,
                        help="Forrásnyelvi SRT (default: automatikus keresés — "
                             "a .hun. tag helyére a forrásnyelv kódja, majd bármely "
                             "ismert .kód.srt az input/ mappában és a fájl mellett). "
                             "Csak akkor kell, ha a fájlnév nem követi a konvenciót. "
                             "A --english a kapcsoló régi neve.")
    parser.add_argument("--no-source", "--no-english", action="store_true",
                        help="Forrásnyelvi SRT kihagyása akkor is, ha megtalálható")
    args = parser.parse_args(argv)

    provider = args.provider
    builtin = MODEL_BUILTIN[provider]
    if args.timeout is None:
        args.timeout = 600 if provider == "claude" else 900
    if args.max_retries is None:
        args.max_retries = {"gemini": MAX_RETRIES, "codex": 2, "grok": 2}.get(provider, 1)
    if provider == "claude" and args.model and args.model not in ("haiku", "sonnet", "opus"):
        print(f"HIBA: a claude providernél a --model haiku|sonnet|opus lehet (kaptam: {args.model})")
        sys.exit(1)

    if args.chunk_size < 1:
        print(f"HIBA: --chunk-size legalább 1 legyen (kaptam: {args.chunk_size})")
        sys.exit(1)
    if args.source and args.no_source:
        print("HIBA: --source és --no-source együtt nem használható.")
        sys.exit(1)
    if getattr(args, "max_retries", 1) < 1:
        print(f"HIBA: --max-retries legalább 1 legyen (kaptam: {args.max_retries})")
        sys.exit(1)

    model = config.resolve_model(args.model, provider, "review", builtin=builtin)

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    # Provider-előfeltételek
    claude_bin = codex_bin = grok_bin = client = None
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
    elif provider == "grok":
        grok_bin = grok_cli.find_grok()
        if not grok_bin:
            print("HIBA: A 'grok' parancs nem található a PATH-on.")
            print("      A Grok CLI legyen a PATH-on (`grok login` vagy XAI_API_KEY).")
            sys.exit(1)

    entries = parse_entries(srt_path)
    print(f"Beolvasva: {len(entries)} felirat szekció")

    # Forrásnyelvi SRT párosítása (kevesebb téves találat).
    # A .hun.srt neve nem árulja el a forrásnyelvet, ezért kétlépcsős a
    # feloldás: előbb a kapcsoló/env/--source útvonal alapján, majd — ha a
    # kapcsoló nem szólt bele — a ténylegesen megtalált forrásfájl nevéből.
    src_lang = config.resolve_source_lang(args.source_lang, args.source)
    has_source = False
    if not args.no_source:
        src_path = (Path(args.source) if args.source
                    else find_source_srt(srt_path, src_lang))
        if args.source and not src_path.is_file():
            print(f"HIBA: forrás SRT nem található: {src_path}")
            sys.exit(1)
        if src_path:
            if not args.source_lang:
                # A megtalált fájl neve nyer az env felett: SUBTR_SOURCE_LANG=ger
                # mellett egy .eng.srt-hez ne német utasítást kapjon a lektor.
                src_lang = config.detect_source_lang(src_path) or src_lang
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
                print(f"Forrásnyelv: {config.source_lang_name(src_lang)} ({src_lang})")
        else:
            print("Forrás: nem található (review csak a magyar alapján).")
            print("  Add meg kézzel: --source \"input/....srt\"")

    chunks = list(chunk_entries(entries, args.chunk_size))
    total_chunks = len(chunks)
    print(f"Chunkok: {total_chunks} db (chunkonként {args.chunk_size} felirat)")
    print(f"Modell: {model or 'provider-alapértelmezés'}")

    # Kontextus + lektor-prompt
    claude_md = load_translation_context()
    # A lektor a magyar szöveget (és ha van, a hozzá párosított forrást) látja
    # — a szójegyzék is erre szűkül, `hu` és `en` alak szerint egyaránt.
    reviewed_text = "\n".join("\n".join(chunk) for chunk in chunks)
    glossary = as_prompt_text(source_text=reviewed_text)
    instruction = build_system_instruction(claude_md, glossary, has_source,
                                           json_output=(provider != "claude"),
                                           src_lang=src_lang)
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
        executor = _make_gemini_executor(client, model, instruction,
                                         max_retries=args.max_retries)
    elif provider == "claude":
        sys_prompt_path = claude_cli.write_sys_prompt_file(
            instruction, CLAUDE_SYS_PROMPT_PREFIX)
        executor = _make_claude_executor(claude_bin, sys_prompt_path, model,
                                         timeout=args.timeout)
    elif provider == "grok":
        executor = _make_grok_executor(grok_bin, model, instruction,
                                       args.timeout, args.max_retries)
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

    # A CLI JSON-út kontraktusa: hibás chunk esetén nem-nulla exit kód
    if provider in ("codex", "grok") and error_chunks:
        sys.exit(1)
