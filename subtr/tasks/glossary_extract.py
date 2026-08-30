"""
glossary_extract.py — Kifejezések kinyerése feliratból, interaktív jóváhagyással

Két mód:
  (1) Fordítás ELŐTT, csak a forrásfeliratból (a magyar argumentum elhagyásával):
      az agent JAVASLATOT tesz a magyar fordításra a CLAUDE.md szabályai alapján.
  (2) Fordítás UTÁN, forrás-magyar párból: a "hu" a ténylegesen használt fordítás.

Használat:
    python glossary_extract.py eredeti.eng.srt                      # (1) előzetes mód
    python glossary_extract.py eredeti.eng.srt forditott.hun.srt    # (2) utólagos mód
    python glossary_extract.py eredeti.eng.srt forditott.hun.srt --glossary glossary.json
    python glossary_extract.py eredeti.eng.srt --provider gemini   # vagy codex / claude
    python glossary_extract.py eredeti.eng.srt --yes                # csak a biztosakat veszi át
    python glossary_extract.py eredeti.eng.srt --all-interactive    # mindent végigkérdez
    python glossary_extract.py eredeti.eng.srt --dry-run            # nem ír fájlba

A feliratot Claude Code-dal, Codex CLI-vel vagy Gemini API-val elemzi (hosszú fájlnál több darabban, szekció-
határon vágva — párban a két nyelv ugyanazokat a szekciókat kapja), kigyűjti
a visszatérő kifejezéseket (megszólítások, helyszínek, nevek, speciális
fogalmak), majd a konzolon jóváhagyhatod őket.

A javaslatok BIZTOS/BIZONYTALAN besorolást kapnak: a modell önbevallása mellett
a gépi fék is számít (a kifejezés tényleges előfordulásszáma a forrásfeliratban,
lásd MIN_OCCURRENCES). Alapból a biztosak automatikusan átmennek, és csak a
bizonytalanokat kérdezzük — ugyanaz a séma, mint a regiszter-kinyerésnél.

A prompt a fordítóéval AZONOS kontextust kap: a teljes TRANSLATION.md +
TRANSLATION.local.md, és a teljes jóváhagyott szójegyzék (a `hu`/`context`
mezőkkel), hogy a rokon kifejezéseknél is a sorozat terminológiáját kövesse.
Csak az elfogadott kifejezések kerülnek a glossary.json-ba.
Mentéskor az előző állapotról glossary.json.bak készül.
"""

import os
import sys
import json
import re
import argparse
import shutil
import subprocess

from subtr.glossary import CATEGORIES, as_prompt_text
from subtr.providers.codex_cli import CodexRunError, find_codex, run_codex_json
from subtr import config
from subtr.context import load_translation_context as load_claude_md
from subtr.providers.claude_cli import find_claude as find_claude_cli

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')


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
    """Meglévő glossary betöltése vagy üres struktúra.

    A hiányzó kategória-kulcsokat pótolja (kézzel szerkesztett / régebbi
    glossary-nál KeyError lenne a mentésnél — a teljes jóváhagyó munkamenet
    UTÁN), a korrupt JSON-t pedig barátságos hibával jelzi még a munka előtt.
    """
    if os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"HIBA: A {path} nem érvényes JSON: {e}")
            print(f"      Javítsd kézzel, vagy állítsd vissza a {path}.bak mentésből.")
            sys.exit(1)
        if not isinstance(data, dict):
            print(f"HIBA: A {path} gyökere nem JSON objektum.")
            sys.exit(1)
        data.setdefault("meta", {"description": "Fordítási szójegyzék", "series": ""})
        for cat in CATEGORIES:
            data.setdefault(cat, [])
        return data
    return {
        "meta": {"description": "Fordítási szójegyzék — kézzel validált kifejezések", "series": ""},
        **{cat: [] for cat in CATEGORIES},
    }


def save_glossary(path: str, data: dict):
    """Glossary mentése — atomikusan (tmp + rename), az előző állapotról
    .bak mentéssel, hogy egy félbeszakadt írás ne tegye tönkre a fájlt."""
    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    print(f"\nSzójegyzék mentve: {path} (előző állapot: {path}.bak)")


def get_existing_terms(glossary: dict) -> set:
    """Meglévő EN kifejezések halmaza (kisbetűs) a duplikátumszűréshez."""
    terms = set()
    for cat in CATEGORIES:
        for entry in glossary.get(cat, []):
            terms.add(entry.get("en", "").lower())
    return terms


JSON_SYNTAX_RULES = """JSON SZINTAKTIKAI SZABÁLY (KRITIKUS):
- A JSON string értékek BELSEJÉBEN SOHA ne használj ASCII " (U+0022) karaktert, mert az lezárja a stringet és a parser elhasal.
- Ha a magyar vagy forrásnyelvi szövegben idézőjel kell (pl. egy nevet idézel), KIZÁRÓLAG a magyar tipográfiai idézőjeleket használd: nyitó „ (U+201E) és záró " (U+201D).
- Példa HELYES: {"en":"Shim Coffee House","hu":"„Shim” Kávéház","context":"kávézó neve"}
- Példa HIBÁS:  {"en":"Shim Coffee House","hu":"„Shim\\" Kávéház",...} — a value belsejében " (ASCII) lezárja a stringet.
- Aposztrófként se ASCII '-t, hanem ' (U+2019) karaktert használj, ha kell."""

# Az "en" kulcs a glossary.json ADATFORMÁTUMA — a meglévő szójegyzékek miatt
# akkor is ez a neve, ha a forrás nem angol. Jelentése: "forrásnyelvi alak".
OUTPUT_SCHEMA = """Válaszolj KIZÁRÓLAG egy JSON tömbbel, semmi más szöveget NE írj:
[{"en": "a forrásnyelvi kifejezés", "hu": "magyar fordítás", "category": "honorifics|place_names|character_names|special_terms|phrases", "context": "rövid megjegyzés", "confidence": "biztos|bizonytalan", "evidence": ["#412 „idézet a feliratból”"]}]"""

# A regiszter-kinyerés bevált szövege: a modell önbevallását kérjük, de a
# gépi fék (count_occurrences + MIN_OCCURRENCES) felül is bírálja.
CONFIDENCE_RULE = """- confidence="biztos" CSAK akkor, ha a magyar alak a fenti szabályokból vagy a
  már jóváhagyott szójegyzék terminológiájából EGYÉRTELMŰEN következik.
  Ha mérlegelned kell (több elfogadható magyar alak, kontextusfüggő jelentés,
  ismeretlen kulturális fogalom), akkor confidence="bizonytalan" — a
  bizonytalanság megjelölése HASZNOS, nem hiba: azt a felhasználó dönti el.
- Az "evidence" mezőbe konkrét sorszámot és rövid idézetet adj a feliratból
  (pl. '#412 „Yes, sir.”'), ne általánosságot. Bizonyíték nélkül ne állíts semmit."""

CODEX_GLOSSARY_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "en": {"type": "string"}, "hu": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "context": {"type": "string"},
                    "confidence": {"type": "string",
                                   "enum": ["biztos", "bizonytalan"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["en", "hu", "category", "context",
                             "confidence", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["suggestions"],
    "additionalProperties": False,
}

GEMINI_MODEL_DEFAULT = "gemini-3.6-flash"


def _existing_note(new_terms) -> str:
    """A futás korábbi darabjaiban már javasolt kifejezések.

    A GLOSSARY-ban meglévőket nem itt soroljuk fel, hanem a `_glossary_note()`
    teljes szövegében — ott a `hu` és a `context` is látszik, ami a lényeg.
    """
    terms = sorted(t for t in new_terms if t)
    if not terms:
        return ""
    return f"""
EBBEN A FUTÁSBAN MÁR JAVASOLT KIFEJEZÉSEK (ne javasold újra ezeket):
{', '.join(terms)}
"""


def _glossary_note(glossary_text: str) -> str:
    """A jóváhagyott szójegyzék TELJES szövege a promptba.

    Korábban csak a kisbetűs `en` kulcsok listája ment át (duplikátumszűrésre),
    így a modell nem láthatta a már eldöntött magyar alakokat — a rokon
    kifejezéseknél ezért tért el a sorozat terminológiájától.
    """
    if not glossary_text.strip():
        return ""
    return f"""
=== MÁR JÓVÁHAGYOTT SZÓJEGYZÉK — A TERMINOLÓGIÁJA KÖTELEZŐ ===
{glossary_text}
=== SZÓJEGYZÉK VÉGE ===
Ezeket a kifejezéseket NE javasold újra. A ROKON kifejezéseknél viszont KÖVESD
a fenti terminológiát: ha a szójegyzék szerint "Sect" = "Rend", akkor a
"Sect Elder" magyar alakja is „Rend"-del képződik, nem „szektá"-val.
"""


def _rules_note(claude_md: str) -> str:
    """A projekt fordítási szabályzata — CSONKÍTATLANUL.

    Korábban `[:6000]`-re volt vágva; a TRANSLATION.md maga is hosszabb ennél,
    és a `subtr.context` a TRANSLATION.local.md-t a VÉGÉRE fűzi — vagyis a
    sorozatspecifikus kontextusból soha semmi nem jutott el a kinyerőhöz.
    A translate.py és a review.py is csonkítatlanul adja át.
    """
    if not claude_md.strip():
        return ""
    return f"""
=== A PROJEKT FORDÍTÁSI SZABÁLYAI (ezek szerint javasold a magyar fordítást) ===
{claude_md.strip()}
=== SZABÁLYOK VÉGE ===
"""


MIN_OCCURRENCES = 2  # ennyi előfordulás alatt a javaslat bizonytalan

_WS_RE = re.compile(r"\s+")


def count_occurrences(term: str, text: str) -> int:
    r"""Hányszor szerepel a kifejezés a forrásszövegben (kis-nagybetű-független).

    A kifejezésen belüli szóközök `\s+`-ra lazulnak, mert a feliratban a
    többszavas kifejezést sortörés is megszakíthatja. Szóhatárt csak ott
    teszünk, ahol a kifejezés betűvel/számmal kezdődik vagy végződik —
    a „Your Highness!" végén a `\b` sosem illeszkedne.
    """
    term = (term or "").strip()
    if not term or not text:
        return 0
    pattern = r"\s+".join(re.escape(p) for p in _WS_RE.split(term))
    if term[0].isalnum():
        pattern = r"\b" + pattern
    if term[-1].isalnum():
        pattern = pattern + r"\b"
    try:
        return len(re.findall(pattern, text, re.IGNORECASE))
    except re.error:
        return 0


CHUNK_CHAR_TARGET = 15000  # ~ennyi karakter kerül egy Claude-hívásba nyelvenként


def _split_sections(content: str) -> list[str]:
    return [s.strip() for s in re.split(r'\n\s*\n', content.strip()) if s.strip()]


def split_srt_chunks(content: str, max_chars: int = CHUNK_CHAR_TARGET) -> list[str]:
    """SRT tartalom feldarabolása szekcióhatáron, ~max_chars darabokra.
    Korábban a fájl egyszerűen 15000 karakternél le lett vágva — egy teljes
    epizód ~75%-a soha nem került elemzésre, figyelmeztetés nélkül."""
    sections = _split_sections(content)
    chunks, cur, cur_len = [], [], 0
    for s in sections:
        if cur and cur_len + len(s) > max_chars:
            chunks.append('\n\n'.join(cur))
            cur, cur_len = [], 0
        cur.append(s)
        cur_len += len(s) + 2
    if cur:
        chunks.append('\n\n'.join(cur))
    return chunks or [""]


def split_srt_pair_chunks(eng_content: str, hun_content: str,
                          max_chars: int = CHUNK_CHAR_TARGET) -> list[tuple[str, str]]:
    """EN+HU darabolás úgy, hogy a két nyelv UGYANAZOKAT a szekciókat kapja
    (index szerint párosítva) — a korábbi két független 15k-s ablak nem is
    ugyanazt a jelenetet fedte."""
    engs = _split_sections(eng_content)
    huns = _split_sections(hun_content)
    if len(engs) != len(huns):
        print(f"FIGYELEM: eltérő szekciószám (EN: {len(engs)}, HU: {len(huns)}) — "
              f"a közös első {min(len(engs), len(huns))} szekciót elemzem")
    n = min(len(engs), len(huns))
    chunks, cur_e, cur_h, cur_len = [], [], [], 0
    for i in range(n):
        pair_len = len(engs[i]) + len(huns[i])
        if cur_e and cur_len + pair_len > max_chars * 2:
            chunks.append(('\n\n'.join(cur_e), '\n\n'.join(cur_h)))
            cur_e, cur_h, cur_len = [], [], 0
        cur_e.append(engs[i])
        cur_h.append(huns[i])
        cur_len += pair_len + 4
    if cur_e:
        chunks.append(('\n\n'.join(cur_e), '\n\n'.join(cur_h)))
    return chunks or [("", "")]


CATEGORIES_BLOCK = """KATEGÓRIÁK:
- honorifics: megszólítások, rangok, címek (pl. Your Highness, General, My Lord)
- place_names: helyszínek, tartományok, paloták
- character_names: karakternevek — a "hu" mezőbe a helyes magyar ÍRÁSMÓD kerüljön, NE fordítás (a nevet nem fordítjuk)
- special_terms: kulturális/speciális kifejezések (pl. spiritual root, cultivation, gisaeng)
- phrases: visszatérő kifejezések, amelyeknek konzisztens fordítása fontos"""


def build_pair_prompt(src_chunk: str, hun_chunk: str, ci: int, total: int,
                      new_terms, glossary_text: str, claude_md: str,
                      src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    """Utólagos (forrás-magyar páros) mód promptja — tiszta függvény, tesztelhető."""
    src_name = config.source_lang_name(src_lang)
    return f"""Elemezd az alábbi {src_name}-magyar feliratpárt és gyűjtsd ki a visszatérő, konzisztensen fordítandó kifejezéseket.

{CATEGORIES_BLOCK}
{_existing_note(new_terms)}{_rules_note(claude_md)}{_glossary_note(glossary_text)}
FONTOS:
- Csak olyan kifejezéseket adj, amelyek TÖBBSZÖR előfordulnak vagy fontosak a konzisztencia szempontjából
- A "hu" mezőben azt a fordítást add, amit a magyar feliratban TÉNYLEGESEN használtunk
- Ne adj triviális szavakat (pl. "yes" = "igen")
{CONFIDENCE_RULE}
- Maximum 30-40 kifejezést adj

{JSON_SYNTAX_RULES}

{OUTPUT_SCHEMA}

{src_name.upper()} FELIRAT (részlet {ci}/{total}):
{src_chunk}

MAGYAR FELIRAT (részlet {ci}/{total}):
{hun_chunk}"""


def build_source_prompt(chunk: str, ci: int, total: int, new_terms,
                        glossary_text: str, claude_md: str,
                        src_lang: str = config.DEFAULT_SOURCE_LANG) -> str:
    """Fordítás előtti (csak forrás) mód promptja — tiszta függvény, tesztelhető."""
    src_name = config.source_lang_name(src_lang)
    return f"""Olvasd végig az alábbi {src_name.upper()} feliratot. A fordítás MÉG NEM készült el — a Te feladatod,
hogy ELŐRE összegyűjtsd azokat a visszatérő kifejezéseket, amelyeket az egész epizódban
KONZISZTENSEN kell majd fordítani, és JAVASLATOT tegyél a magyar megfelelőjükre.

{CATEGORIES_BLOCK}
{_existing_note(new_terms)}{_rules_note(claude_md)}{_glossary_note(glossary_text)}
FONTOS:
- Csak olyan kifejezéseket adj, amelyek TÖBBSZÖR előfordulnak vagy fontosak a konzisztencia szempontjából
- A "hu" mező a JAVASOLT fordítás — kövesd a fenti projekt-szabályokat (megszólítások, "rész", semleges nem ahol kétséges)
- Ne adj triviális szavakat (pl. "yes" = "igen")
- Ha egy kifejezés magyar fordítása bizonytalan vagy kontextusfüggő, a "context" mezőben jelezd
{CONFIDENCE_RULE}
- Maximum 30-40 kifejezést adj

{JSON_SYNTAX_RULES}

{OUTPUT_SCHEMA}

{src_name.upper()} FELIRAT (részlet {ci}/{total}):
{chunk}"""


def extract_terms(src_path: str, hun_path: str, existing_terms: set,
                  claude_md: str = "", glossary_text: str = "", timeout: int = 300,
                  provider: str = "claude", model: str | None = None,
                  src_lang: str = config.DEFAULT_SOURCE_LANG) -> list[dict]:
    """Claude Code-dal kifejezések kinyerése a feliratpárból (utólagos mód).
    Hosszú fájlnál több darabban — a teljes epizód elemzésre kerül."""
    with open(src_path, 'r', encoding='utf-8-sig') as f:
        eng_content = f.read()
    with open(hun_path, 'r', encoding='utf-8-sig') as f:
        hun_content = f.read()

    chunk_pairs = split_srt_pair_chunks(eng_content, hun_content)
    if len(chunk_pairs) > 1:
        print(f"A felirat {len(chunk_pairs)} darabban lesz elemezve "
              f"(darabonként egy hívás).")

    all_valid = []
    seen = set(existing_terms)
    for ci, (ec, hc) in enumerate(chunk_pairs, 1):
        if len(chunk_pairs) > 1:
            print(f"\n[{ci}/{len(chunk_pairs)}] darab elemzése...")
        prompt = build_pair_prompt(ec, hc, ci, len(chunk_pairs),
                                   seen - existing_terms, glossary_text,
                                   claude_md, src_lang)

        valid = _run_extraction(prompt, seen, timeout, provider, model,
                                source_text=eng_content)
        for v in valid:
            seen.add(v["en"].lower())
        all_valid.extend(valid)
    return all_valid


def extract_terms_source(src_path: str, existing_terms: set, claude_md: str = "",
                         glossary_text: str = "",
                         timeout: int = 300, provider: str = "claude",
                         model: str | None = None,
                         src_lang: str = config.DEFAULT_SOURCE_LANG) -> list[dict]:
    """Fordítás ELŐTTI kinyerés CSAK a forrásfeliratból.

    Az agent JAVASLATOT tesz a magyar fordításra (a CLAUDE.md szabályai +
    a meglévő glossary alapján), te a konzolon hagyod jóvá/szerkeszted.
    Így a párhuzamos fordítás már egységes nevekkel/címekkel indul.
    """
    with open(src_path, 'r', encoding='utf-8-sig') as f:
        eng_content = f.read()

    chunks = split_srt_chunks(eng_content)
    if len(chunks) > 1:
        print(f"A felirat {len(chunks)} darabban lesz elemezve "
              f"(darabonként egy hívás).")

    all_valid = []
    seen = set(existing_terms)
    for ci, chunk in enumerate(chunks, 1):
        if len(chunks) > 1:
            print(f"\n[{ci}/{len(chunks)}] darab elemzése...")
        prompt = build_source_prompt(chunk, ci, len(chunks),
                                     seen - existing_terms, glossary_text,
                                     claude_md, src_lang)

        valid = _run_extraction(prompt, seen, timeout, provider, model,
                                source_text=eng_content)
        for v in valid:
            seen.add(v["en"].lower())
        all_valid.extend(valid)
    return all_valid


def validate_suggestions(suggestions, existing_terms: set,
                         source_text: str = "") -> list[dict]:
    """A provider válaszát a glossary szerződéséhez igazítja.

    Itt dől el a biztos/bizonytalan besorolás is. A modell önbevallásos
    magabiztossága önmagában nem szűr (a regiszter-kinyerésnél szerzett
    tapasztalat: mindent "biztos"-nak jelöl), ezért a forrásfeliratban mért
    tényleges előfordulásszám felülbírálhatja: MIN_OCCURRENCES alatt a
    javaslat bizonytalan, akármit is állít magáról.
    """
    if not isinstance(suggestions, list):
        return []
    valid = []
    for suggestion in suggestions:
        if not isinstance(suggestion, dict):
            continue
        if not all(key in suggestion for key in ("en", "hu", "category")):
            continue
        if suggestion["category"] not in CATEGORIES:
            continue
        # A Claude-ág szabad JSON-t enged át (null, szám) — a séma nélküli
        # érték .lower()-nél dobna, és az egész darab elveszne.
        if not isinstance(suggestion["en"], str) or not isinstance(suggestion["hu"], str):
            continue
        if suggestion["en"].lower() in existing_terms:
            continue

        occ = count_occurrences(suggestion["en"], source_text)
        conf = "biztos" if str(suggestion.get("confidence", "")).strip().lower() == "biztos" \
            else "bizonytalan"
        if source_text and occ < MIN_OCCURRENCES:
            conf = "bizonytalan"
        suggestion["confidence"] = conf
        suggestion["occurrences"] = occ
        suggestion["evidence"] = [str(e).strip()
                                  for e in (suggestion.get("evidence") or [])
                                  if str(e).strip()][:4]
        valid.append(suggestion)
    return valid


def _run_gemini(prompt: str, existing_terms: set, model: str | None,
                source_text: str = "") -> list[dict]:
    """Gemini API ág — a retry/kvóta logika a közös adapterben (subtr.providers.gemini)."""
    from subtr.providers import gemini as gemini_provider
    if not gemini_provider.DEPS_OK:
        print(f"HIBA: Hiányzó függőség: {gemini_provider.DEPS_ERROR}")
        print("      Telepítés: pip install google-genai python-dotenv pydantic")
        return []

    model = model or GEMINI_MODEL_DEFAULT
    gemini_provider.preflight(model, needed=1)
    print(f"Gemini elemzi a feliratot... ({model})")
    gemini_prompt = (prompt + "\n\nKIMENET: kizárólag egy JSON objektum "
                     '`suggestions` tömbbel: {"suggestions":[...]}.')
    try:
        client = gemini_provider.make_client()
    except RuntimeError as e:
        print(f"HIBA: {e}")
        return []
    parsed, err = gemini_provider.call_json(client, model, gemini_prompt,
                                            schema=CODEX_GLOSSARY_SCHEMA,
                                            temperature=0.2)
    if err:
        print(f"HIBA: Gemini API hiba: {err}")
        return []
    return validate_suggestions(parsed.get("suggestions", []), existing_terms,
                                source_text)


def _run_extraction(prompt: str, existing_terms: set, timeout: int,
                    provider: str = "claude", model: str | None = None,
                    source_text: str = "") -> list[dict]:
    """Közös rész: provider hívás, válasz-parse és validáció."""
    if provider == "gemini":
        return _run_gemini(prompt, existing_terms, model, source_text)

    if provider == "codex":
        codex_cmd = find_codex()
        if not codex_cmd:
            print("HIBA: A 'codex' parancs nem található a PATH-on.")
            return []
        print(f"Codex elemzi a feliratot... ({codex_cmd})")
        try:
            codex_prompt = (prompt + "\n\nCODEX KIMENET: kizárólag egy JSON objektumot adj "
                            "`suggestions` tömbbel: {\"suggestions\":[...]}." )
            result = run_codex_json(codex_prompt, CODEX_GLOSSARY_SCHEMA, timeout=timeout,
                                    model=model, codex_bin=codex_cmd)
        except CodexRunError as exc:
            print(f"HIBA: Codex hiba: {exc}")
            return []
        return validate_suggestions(result.get("suggestions", []), existing_terms,
                                    source_text)

    claude_cmd = find_claude_cli()
    print(f"Claude Code elemzi a feliratot... ({claude_cmd})")
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

        return validate_suggestions(suggestions, existing_terms, source_text)

    except subprocess.TimeoutExpired:
        print(f"HIBA: Timeout ({timeout} mp)")
        return []
    except FileNotFoundError:
        print(f"HIBA: A 'claude' parancs nem található! (keresett: {claude_cmd})")
        print("  Megoldás: telepítsd a Claude Code CLI-t, vagy add hozzá a PATH-hoz.")
        print(f"  Tipp: ellenőrizd, hogy létezik-e: {os.path.join(os.path.expanduser('~'), '.local', 'bin', 'claude.exe')}")
        return []


def _describe(s: dict) -> str:
    cat_label = CATEGORY_LABELS.get(s["category"], s["category"])
    ctx = s.get("context", "")
    return (f'[{cat_label}] "{s["en"]}" = "{s["hu"]}"'
            + (f"  ({ctx})" if ctx else ""))


def _ask(s: dict, i: int, total: int) -> str:
    """Egy javaslat elbírálása. Visszaad: 'y' | 'n' | 'q'.

    Szerkesztésnél a rekordot helyben módosítja, és 'y'-t ad vissza.
    """
    cat_label = CATEGORY_LABELS.get(s["category"], s["category"])
    context = s.get("context", "")
    ctx_str = f"  ({context})" if context else ""
    flag = "BIZTOS" if s.get("confidence") == "biztos" else "BIZONYTALAN"

    print(f"[{i}/{total}] [{cat_label}]  {flag} "
          f"({s.get('occurrences', 0)} előfordulás)")
    print(f"  EN: {s['en']}")
    print(f"  HU: {s['hu']}{ctx_str}")
    for e in s.get("evidence", [])[:2]:
        print(f"  bizonyíték: {e}")

    while True:
        choice = input("  Döntés ([y] elfogad / n / e szerkeszt / q kilép): ").strip().lower()
        if choice in ("y", ""):
            print("  → Elfogadva")
            return "y"
        if choice == "n":
            print("  → Elutasítva")
            return "n"
        if choice == "q":
            return "q"
        if choice == "e":
            new_hu = input(f"  Új magyar fordítás [{s['hu']}]: ").strip()
            if new_hu:
                s["hu"] = new_hu
            new_ctx = input(f"  Új kontextus [{context}]: ").strip()
            if new_ctx:
                s["context"] = new_ctx
            new_cat = input(f"  Új kategória [{s['category']}]: ").strip()
            if new_cat and new_cat in CATEGORIES:
                s["category"] = new_cat
            print("  → Elfogadva (szerkesztve)")
            return "y"
        print("  Ismeretlen válasz. Használj: y / n / e / q")


def interactive_review(suggestions: list[dict], auto_yes: bool = False,
                       all_interactive: bool = False) -> list[dict]:
    """Jóváhagyás a konzolon, a biztos/bizonytalan besorolás szerint.

    Alapból a biztos találatok automatikusan átmennek, és csak a
    bizonytalanokat kérdezzük — ugyanaz a séma, mint a regiszter-kinyerésnél.
    `--yes` esetén a bizonytalanok kimaradnak, `--all-interactive` esetén
    mindent végigkérdezünk (ez volt a korábbi viselkedés).
    """
    if not suggestions:
        print("\nNincs új javaslat.")
        return []

    certain = sum(1 for s in suggestions if s.get("confidence") == "biztos")
    print(f"\n{'=' * 55}")
    print(f"  {len(suggestions)} új kifejezés javaslat "
          f"({certain} biztos, {len(suggestions) - certain} bizonytalan)")
    if all_interactive:
        print("  --all-interactive: mindegyiket végigkérdezem")
    elif auto_yes:
        print("  --yes: a biztosakat átveszem, a bizonytalanokat kihagyom")
    else:
        print("  A biztosakat átveszem, csak a bizonytalanokat kérdezem")
    print(f"{'=' * 55}\n")

    approved, auto, to_ask = [], [], []
    for s in suggestions:
        if not all_interactive and s.get("confidence") == "biztos":
            auto.append(s)
            approved.append(s)
        else:
            to_ask.append(s)

    if auto:
        print(f"Automatikusan elfogadva ({len(auto)} biztos találat):")
        for s in auto:
            print(f"  - {_describe(s)}  [{s.get('occurrences', 0)}×]")
        print()

    skipped = 0
    if to_ask and auto_yes:
        skipped = len(to_ask)
        print(f"--yes: {skipped} bizonytalan javaslat kihagyva "
              f"(--all-interactive vagy kapcsoló nélküli futással átnézhetők).")
        to_ask = []

    if to_ask:
        print(f"{len(to_ask)} javaslat vár döntésre:\n")
    for i, s in enumerate(to_ask, 1):
        decision = _ask(s, i, len(to_ask))
        print()
        if decision == "q":
            skipped += len(to_ask) - i + 1
            print("  Jóváhagyás megszakítva — az eddig elfogadottak megmaradnak.\n")
            break
        if decision == "y":
            approved.append(s)
        else:
            skipped += 1

    print(f"Összesítés: {len(approved)} elfogadva "
          f"({len(auto)} automatikusan), {skipped} kihagyva.")
    return approved


def merge_into_glossary(glossary: dict, approved: list[dict]) -> int:
    """Elfogadott kifejezések beillesztése a glossary-ba. Visszaadja a hozzáadottak számát.

    A duplikátum-szűrés az ÖSSZES kategóriára néz (nem csak a célkategóriára),
    és a most hozzáadottakra is — így ugyanaz az EN kifejezés nem kerülhet be
    kétszer, két kategóriában, esetleg eltérő HU fordítással."""
    added = 0
    existing_all = get_existing_terms(glossary)
    for entry in approved:
        cat = entry["category"]
        if cat not in CATEGORIES:
            continue
        if entry["en"].lower() in existing_all:
            continue
        glossary.setdefault(cat, []).append({
            "en": entry["en"],
            "hu": entry["hu"],
            "context": entry.get("context", ""),
        })
        existing_all.add(entry["en"].lower())
        added += 1

    return added


def main():
    parser = argparse.ArgumentParser(
        description="Kifejezések kinyerése felirat(pár)ból a glossary.json bővítéséhez. "
                    "Két mód: (1) fordítás ELŐTT csak a forrásfeliratból (HU javaslattal), "
                    "(2) fordítás UTÁN forrás-magyar párból."
    )
    parser.add_argument("source_srt", help="Az eredeti, forrásnyelvi SRT fájl")
    parser.add_argument("hun_srt", nargs="?", default=None,
                        help="Fordított magyar SRT fájl (opcionális). "
                             "Ha NINCS megadva → fordítás előtti, forrás-only kinyerés "
                             "(az agent javaslatot tesz a magyar fordításra).")
    config.add_source_lang_argument(parser)
    parser.add_argument("--glossary", type=str, default="glossary.json",
                        help="Szójegyzék fájl útvonala (alapértelmezett: glossary.json)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Provider timeout másodpercben (alapértelmezett: 300)")
    parser.add_argument("--provider", choices=("claude", "codex", "gemini"),
                        default=config.default_provider(builtin="claude"),
                        help="Kinyerő provider (alapértelmezett: claude, "
                             "felülírható: SUBTR_DEFAULT_PROVIDER env)")
    parser.add_argument("--model",
                        help="Opcionális modellazonosító (codex / gemini; "
                             f"gemini default: {GEMINI_MODEL_DEFAULT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Csak kiírja, mi kerülne be — a szójegyzéket nem módosítja")
    parser.add_argument("--all-interactive", action="store_true",
                        help="Minden javaslatnál kérdezzen, ne csak a bizonytalanoknál")
    parser.add_argument("--yes", action="store_true",
                        help="Ne kérdezzen: csak a biztos találatokat veszi át, "
                             "a bizonytalanokat kihagyja")
    args = parser.parse_args()

    if args.all_interactive and args.yes:
        print("HIBA: A --yes és a --all-interactive kizárja egymást.")
        sys.exit(1)

    # Modell-feloldás: CLI --model > SUBTR_<P>_MODEL_GLOSSARY > SUBTR_<P>_MODEL
    # > beégetett default (Gemini-nél GEMINI_MODEL_DEFAULT, CLI-knél None).
    args.model = config.resolve_model(
        args.model, args.provider, "glossary",
        builtin=GEMINI_MODEL_DEFAULT if args.provider == "gemini" else None)

    pre_mode = args.hun_srt is None  # fordítás előtti, forrás-only mód
    src_lang = config.resolve_source_lang(args.source_lang, args.source_srt)

    check_paths = [args.source_srt] if pre_mode else [args.source_srt, args.hun_srt]
    for path in check_paths:
        if not os.path.isfile(path):
            print(f"HIBA: Nem találom a fájlt: {path}")
            sys.exit(1)

    print("=" * 55)
    if pre_mode:
        print("  Glossary Extract — Fordítás ELŐTTI kinyerés (csak a forrásból)")
    else:
        print("  Glossary Extract — Fordítás UTÁNI kinyerés (forrás-magyar)")
    print("=" * 55)
    print(f"  Forrás:     {args.source_srt}  "
          f"[{config.source_lang_name(src_lang)}]")
    if not pre_mode:
        print(f"  Magyar:     {args.hun_srt}")
    print(f"  Szójegyzék: {args.glossary}")
    print("=" * 55)
    print()

    # Meglévő glossary betöltése
    glossary = load_glossary(args.glossary)
    existing_terms = get_existing_terms(glossary)
    if existing_terms:
        print(f"Meglévő kifejezések: {len(existing_terms)}")

    # A fordítóval AZONOS kontextus: teljes szabályzat + teljes szójegyzék.
    # (Korábban a szabályzat 6000 karakterre volt vágva — a TRANSLATION.local.md
    # így soha nem ért ide —, a szójegyzékből pedig csak az "en" kulcsok mentek át.)
    claude_md = load_claude_md()
    glossary_text = as_prompt_text(glossary)
    if claude_md:
        print(f"Szabályzat: {len(claude_md)} karakter "
              f"(TRANSLATION.md + TRANSLATION.local.md)")
    else:
        print("FIGYELEM: TRANSLATION.md nem található a munkakönyvtárban — "
              "sorozat-szabályok NÉLKÜL javaslok fordítást!")
    if glossary_text:
        print(f"Szójegyzék a promptban: {len(glossary_text)} karakter")

    # Kinyerés
    if pre_mode:
        suggestions = extract_terms_source(args.source_srt, existing_terms, claude_md,
                                           glossary_text, args.timeout, args.provider,
                                           args.model, src_lang)
    else:
        suggestions = extract_terms(args.source_srt, args.hun_srt, existing_terms,
                                    claude_md, glossary_text, args.timeout,
                                    args.provider, args.model, src_lang)

    if not suggestions:
        print("Nem találtam új kifejezést.")
        return

    print(f"\n{len(suggestions)} új kifejezés javaslat érkezett.")

    # Jóváhagyás (biztos = automatikus, bizonytalan = kérdés vagy kihagyás)
    approved = interactive_review(suggestions, auto_yes=args.yes,
                                  all_interactive=args.all_interactive)

    if not approved:
        print("\nNem lett elfogadva egyetlen kifejezés sem.")
        return

    if args.dry_run:
        print(f"\n--dry-run: a(z) {args.glossary} NEM módosul. "
              f"Beírásra várna {len(approved)} kifejezés:")
        for s in approved:
            print(f"  - {_describe(s)}")
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
