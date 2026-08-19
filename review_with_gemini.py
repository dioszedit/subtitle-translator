#!/usr/bin/env python3
"""
Fordítás ellenőrző script — Gemini API alapú review.
Az ÖSSZEFŰZÖTT hun.srt fájlt darabokra szedi, és minden darabot
Gemini-vel átnézet, kifejezetten tükörfordítások és ragozási hibák
szempontjából. A talált hibákat egy riportba írja.

Használat:
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt"
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --chunk-size 100
    python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --model gemini-3.5-flash-lite

Angol eredeti (kevesebb téves találat):
    Ha megtalálja a forrásnyelvi SRT-t, minden szekció mellé odaadja a
    Gemini-nek a forrás eredetit is [FORRÁS] sorként — így a lektor a forráshoz
    tudja mérni a magyart, nem csak "gyanús" mondatokat keres.
    Automatikus keresés: a .hun.srt névből .eng.srt, az input/ mappában
    (ill. a hun fájl mellett). Kézi megadás / kikapcsolás:
        python review_with_gemini.py "output/....hun.srt" --source "input/....eng.srt"
        python review_with_gemini.py "output/....hun.srt" --no-source

    Csak egy konkrét chunk(tartomány) lefuttatása (pl. kvótahiba utáni pótlás):
        python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --start-chunk 9 --suffix _part2
        python review_with_gemini.py "output/Sorozat - S01E01.hun.srt" --start-chunk 5 --end-chunk 7 --suffix _part2

Modell:
    Alapértelmezett: gemini-3.6-flash (erős és stabilan elérhető)
    --model <név>: tetszőleges Gemini modell-azonosító megadható
        Flash:      gemini-3.6-flash, gemini-3.5-flash
        Legújabb:   gemini-3.7-flash — gyakran túlterhelt (503), ezért nem default
        Olcsó/lite: gemini-3.5-flash-lite, gemini-3.1-flash-lite
        Pro:        gemini-3.1-pro-preview
        Alias:      gemini-flash-latest, gemini-flash-lite-latest, gemini-pro-latest
        Modell-lista: https://ai.google.dev/gemini-api/docs/models

    Free tier: a nem-lite modellek napi kérésszáma szűkös (tapasztalat szerint
    ~20/nap modellenként — egy ~400 szekciós rész review-ja 4-5 kérés), a -lite
    modellek bőkezűbbek. Kvótahiba esetén: --model gemini-3.5-flash-lite,
    illetve a --start-chunk / --end-chunk / --suffix kapcsolók.

Tartomány-paraméterek:
    --start-chunk N    Csak ettől a chunktól kezdje (1-alapú). Default: 1
    --end-chunk N      Eddig a chunkig bezárólag (1-alapú). Default: utolsó
    --suffix _xxx      Riport fájlnév-utótag, hogy ne írja felül a meglévő
                       riportot. Pl. --suffix _part2 →
                       Sorozat - S01E01.hun_REVIEW_GEMINI_part2.txt

API kulcs:
    A .env fájlba tedd: GEMINI_API_KEY=...

Függőségek:
    pip install google-genai python-dotenv pydantic

Kimenet:
    output/Sorozat - S01E01.hun_REVIEW_GEMINI.txt   (olvasható riport)
    output/Sorozat - S01E01.hun_REVIEW_GEMINI.json  (apply_review.py bemenete)
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import List

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from glossary_categories import CATEGORIES
from translation_context import load_translation_context

# Kvótakövetés — gépszintű, API kulcs szerint (a Gemini API nem adja vissza
# a maradék napi kérésszámot). Ha a modul hiányzik, a script fut tovább.
try:
    import gemini_quota as _gq
except Exception:
    _gq = None

# Külső függőségek — lazy try/except, hogy a --help akkor is fusson, ha még
# nincsenek telepítve. A main() ellenőrzi a _DEPS_OK flag-et a tényleges
# munka előtt; ha hiányzik függőség, friendly üzenettel kilép.
_DEPS_OK = True
_DEPS_ERROR = None
try:
    from dotenv import load_dotenv
    from pydantic import BaseModel
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
except ImportError as _e:
    _DEPS_OK = False
    _DEPS_ERROR = str(_e)
    # Stub BaseModel — a class definíciók (ErrorItem, ErrorReport) így import
    # időben nem hasalnak el. Az osztályokat csak a main()-ből hívjuk meg
    # tényleges használatra, ami ellenőrzi a _DEPS_OK-ot.
    class BaseModel:  # type: ignore[no-redef]
        pass


DEFAULT_CHUNK_SIZE = 100
MODEL_DEFAULT = "gemini-3.6-flash"
TEMPERATURE = 0.2
MAX_RETRIES = 4
RETRY_BASE_DELAY = 5  # másodperc


class ErrorItem(BaseModel):
    sorszam: int
    eredeti: str
    hiba: str
    javaslat: str


class ErrorReport(BaseModel):
    errors: List[ErrorItem]


def parse_srt(filepath):
    """SRT blokkok beolvasása teljes szöveggel együtt."""
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


def build_system_instruction(claude_md: str, glossary: str,
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
        parts.append("""=== FORRÁSNYELVI EREDETI ===
A legtöbb szekció után egy [FORRÁS] sor áll: ez a FORRÁSNYELVI EREDETI, amiből
a magyar fordítás készült. Ez a viszonyítási alap:
- Jelezd, ha a magyar mást mond, mint a forrás (félrefordítás,
  kimaradt/hozzáköltött tartalom, tagadás/idő/szám/személy eltérés).
- NE jelents hibát, ha a forrás igazolja a magyar megoldást —
  ami forrás nélkül furcsának tűnne, a forrás ismeretében gyakran helyes.
- A [FORRÁS] sor csak kontextus: a "eredeti" mezőbe MINDIG a magyar szöveg
  kerüljön, a [FORRÁS] sort ne idézd bele és ne javasold módosítani.""")

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
    """Per-chunk prompt — minimális, a szabályok a system instruction-ben."""
    return f"""SRT BLOKK ({chunk_num}/{total_chunks}):
{chunk_text}
"""


def is_transient_error(e: Exception) -> bool:
    """Átmeneti (retry-olható) hiba-e: hálózati megszakadás, timeout stb.
    A google-genai SDK ezeket httpx/httpcore kivételként dobja, NEM
    APIError-ként — egy wifi-bukkanó nem indokolja a chunk végleges bukását."""
    if isinstance(e, (ConnectionError, TimeoutError)):
        return True
    mod = type(e).__module__ or ""
    return mod.split(".")[0] in ("httpx", "httpcore", "anyio", "ssl")


def review_chunk_gemini(client, model, chunk_text, chunk_num, total_chunks,
                        system_instruction):
    """Egy chunk átnézetése Gemini API-val. Strukturált JSON kimenet."""
    prompt = build_prompt(chunk_text, chunk_num, total_chunks)

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=TEMPERATURE,
        response_mime_type="application/json",
        response_schema=ErrorReport,
    )

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            # A hívás lefutott a modellen → fogyasztotta a napi kvótát.
            # (Az üres/blokkolt válasz is, ezért a parse ELŐTT könyvelünk.)
            if _gq:
                _gq.record(model)

            parsed: ErrorReport = response.parsed
            if parsed is None:
                # Safety filter vagy üres válasz — gyakran átmeneti
                last_err = "üres / blokkolt válasz"
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    print(f"  Üres/blokkolt válasz, újrapróbálás {delay}s múlva... ({attempt}/{MAX_RETRIES})")
                    time.sleep(delay)
                    continue
                return None, "[Üres / blokkolt válasz a Gemini-től]"
            return parsed, None

        except genai_errors.APIError as e:
            last_err = e
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            # 429-ből megtanuljuk a modell tényleges NAPI limitjét, így a
            # következő futás előtt már pontosat tudunk jelezni. A modul csak
            # a napi (PerDay) kvótát veszi figyelembe — az alábbi retry-ág
            # által kezelt percenkénti 429-et szándékosan figyelmen kívül hagyja.
            if status == 429 and _gq:
                _gq.note_limit_from_error(model, e)
            if status in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  API hiba ({status}), újrapróbálás {delay}s múlva... ({attempt}/{MAX_RETRIES})")
                time.sleep(delay)
                continue
            return None, f"[API hiba: {e}]"
        except Exception as e:
            last_err = e
            if is_transient_error(e) and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  Hálózati hiba ({type(e).__name__}), újrapróbálás {delay}s múlva... ({attempt}/{MAX_RETRIES})")
                time.sleep(delay)
                continue
            return None, f"[Váratlan hiba: {e}]"

    return None, f"[{MAX_RETRIES} próbálkozás után sem sikerült: {last_err}]"


def format_findings(parsed: ErrorReport, chunk_num, total):
    """A JSON-ból szöveges riport-blokk."""
    if not parsed.errors:
        return None

    lines = [f"--- Chunk {chunk_num}/{total} ---"]
    for err in parsed.errors:
        lines.append(f'#{err.sorszam}: "{err.eredeti}"')
        lines.append(f"  → HIBA: {err.hiba}")
        lines.append(f"  → JAVASLAT: {err.javaslat}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Magyar fordítás review Gemini-vel")
    parser.add_argument("srt_file", help="Az összefűzött hun.srt fájl")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Feliratok chunkonként (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--model", type=str, default=MODEL_DEFAULT,
                        help=f"Gemini modell-azonosító (default: {MODEL_DEFAULT}). "
                             "Pl. gemini-3.7-flash (gyakran túlterhelt), gemini-3.5-flash-lite, "
                             "gemini-3.1-flash-lite, gemini-3.1-pro-preview")
    parser.add_argument("--start-chunk", type=int, default=1,
                        help="Csak ettől a chunktól kezdje (1-alapú). Default: 1")
    parser.add_argument("--end-chunk", type=int, default=None,
                        help="Eddig a chunkig (bezárólag, 1-alapú). Default: utolsó")
    parser.add_argument("--suffix", type=str, default="",
                        help="Riport fájl utótag, pl. '_part2' → _REVIEW_GEMINI_part2.txt")
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

    # Függőség-ellenőrzés (a --help-hez nem kellettek az import-ok)
    if not _DEPS_OK:
        print(f"HIBA: Hiányzó Python függőség: {_DEPS_ERROR}")
        print(f"      Telepítés: pip install google-genai python-dotenv pydantic")
        sys.exit(1)

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("HIBA: GEMINI_API_KEY nincs beállítva. Tedd a .env fájlba vagy a környezeti változók közé.")
        sys.exit(1)

    srt_path = Path(args.srt_file)
    if not srt_path.exists():
        print(f"HIBA: Fájl nem található: {srt_path}")
        sys.exit(1)

    model = args.model
    client = genai.Client(api_key=api_key)

    # Pre-flight: ellenőrizzük, hogy a modell létezik-e.
    # Csak a 404 jelent rossz modellnevet — kvótahiba (429) vagy átmeneti
    # 5xx esetén félrevezető lenne "nem létező modell"-t mondani.
    try:
        client.models.get(model=model)
    except genai_errors.APIError as e:
        status = getattr(e, "code", None) or getattr(e, "status_code", None)
        if status == 404:
            print(f"HIBA: Nem létező Gemini modell: '{model}'")
            print(f"      A használható modellek listája:")
            print(f"      https://ai.google.dev/gemini-api/docs/models")
        else:
            print(f"HIBA: Gemini API hiba a modell-ellenőrzésnél ({status}): {e}")
            print(f"      (Kvóta / átmeneti hiba lehet — próbáld később.)")
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
    print(f"Modell: {model}")

    # Kontextus betöltése
    claude_md = load_claude_md()
    glossary = load_glossary()
    system_instruction = build_system_instruction(claude_md, glossary, has_source)
    print(f"System instruction: {len(system_instruction)} char "
          f"(CLAUDE.md: {len(claude_md)} char, glossary: {len(glossary)} char)")

    start = max(1, args.start_chunk)
    end = args.end_chunk if args.end_chunk is not None else total_chunks
    end = min(end, total_chunks)
    if start > end:
        print(f"HIBA: --start-chunk ({start}) nagyobb mint --end-chunk ({end}).")
        sys.exit(1)
    if start > 1 or end < total_chunks:
        print(f"Tartomány: {start}–{end}")

    # Kvóta-előrejelzés: a Gemini API nem adja vissza a maradékot, ezért
    # helyi (gépszintű, kulcs szerinti) könyvelésből becsüljük meg, hogy
    # a most következő (end - start + 1) kérés belefér-e a napi limitbe.
    if _gq:
        _gq.preflight(model, needed=end - start + 1)
    print()

    report_path = srt_path.with_name(srt_path.stem + f"_REVIEW_GEMINI{args.suffix}.txt")
    json_path = srt_path.with_name(srt_path.stem + f"_REVIEW_GEMINI{args.suffix}.json")

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

        parsed, err_msg = review_chunk_gemini(client, model, chunk_text, i, len(chunks),
                                              system_instruction)

        if err_msg:
            error_chunks.append(f"--- Chunk {i}/{len(chunks)} ---\n{err_msg}\n")
            print(f"  {err_msg}")
            continue

        block = format_findings(parsed, i, len(chunks))
        if block:
            all_findings.append(block)
        for err in parsed.errors:
            json_findings.append({"sorszam": err.sorszam, "eredeti": err.eredeti,
                                  "hiba": err.hiba, "javaslat": err.javaslat,
                                  "chunk": i})

    # Riport mentése
    sections = []
    if all_findings:
        sections.append("\n".join(all_findings))
    if error_chunks:
        sections.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(error_chunks))

    if sections:
        report_content = (
            f"Review riport (Gemini): {srt_path.name}\n"
            f"Modell: {model}\n"
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
            "reviewer": "gemini",
            "model": model,
            "findings": json_findings,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON riport mentve: {json_path}")


if __name__ == "__main__":
    main()
