"""Közös beállítás- és modell-feloldási logika minden providerhez és taskhoz.

A .env betöltése IMPORT-IDŐBEN, EGYSZER történik — ez ugyanaz a minta, mint a
repo több meglévő scriptjében. A python-dotenv csomag opcionális függőség:
ha nincs telepítve, ez a modul akkor is importálható marad, csak a .env
fájl nem töltődik be (pl. ha a környezeti változók már máshonnan jönnek).
"""

import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


TASKS = ("translate", "review", "glossary", "register")
PROVIDERS = ("gemini", "claude", "codex")

# CWD-relatív útvonalak, mint eddig is — NEM keresünk repo-gyökeret,
# a scripteket úgyis a repo gyökeréből futtatjuk.
GLOSSARY_PATH = "glossary.json"
TRANSLATION_MD = "TRANSLATION.md"
TRANSLATION_LOCAL_MD = "TRANSLATION.local.md"


def api_key(name: str = "GEMINI_API_KEY") -> str:
    """A megadott nevű env-változó értéke, vagy üres string, ha nincs beállítva."""
    return os.environ.get(name, "") or ""


def _validate(provider: str, task: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Ismeretlen provider: {provider!r} (várt: {PROVIDERS})")
    if task not in TASKS:
        raise ValueError(f"Ismeretlen task: {task!r} (várt: {TASKS})")


def _env_model_keys(provider: str, task: str) -> tuple[str, str]:
    """A task-specifikus és a generikus env-kulcs neve a providerhez/taskhoz."""
    provider_upper = provider.upper()
    task_upper = task.upper()
    task_specific = f"SUBTR_{provider_upper}_MODEL_{task_upper}"
    generic = f"SUBTR_{provider_upper}_MODEL"
    return task_specific, generic


def resolve_model(cli_value, provider: str, task: str, builtin=None):
    """Feloldja, melyik modell nevet kell használni egy adott providerhez/taskhoz.

    Precedencia (a legerősebb nyer):
      1. cli_value               — a --model kapcsolóval explicit megadott érték
      2. SUBTR_<PROVIDER>_MODEL_<TASK>  — task-specifikus env
      3. SUBTR_<PROVIDER>_MODEL         — generikus, provider-szintű env
      4. builtin                 — a hívó script beégetett alapértelmezése

    Az üres string env-érték úgy számít, mintha nem lenne beállítva (kihagyjuk
    a láncból).
    """
    _validate(provider, task)

    if cli_value:
        return cli_value

    task_specific_key, generic_key = _env_model_keys(provider, task)

    task_specific_value = os.environ.get(task_specific_key, "")
    if task_specific_value:
        return task_specific_value

    generic_value = os.environ.get(generic_key, "")
    if generic_value:
        return generic_value

    return builtin


def default_provider(builtin: str = "claude") -> str:
    """A SUBTR_DEFAULT_PROVIDER env értéke, ha az egy érvényes provider-név.

    Ha az env nincs beállítva, üres, vagy érvénytelen provider-nevet tartalmaz,
    a builtin alapértelmezést adja vissza.
    """
    value = os.environ.get("SUBTR_DEFAULT_PROVIDER", "")
    if value in PROVIDERS:
        return value
    return builtin


def model_help(provider: str, task: str, builtin) -> str:
    """Emberi olvasásra szánt szöveg a --help kimenetéhez a feloldási láncról."""
    _validate(provider, task)
    task_specific_key, generic_key = _env_model_keys(provider, task)
    return f"default: {task_specific_key} / {generic_key} / {builtin}"


# ────────────────────────────────────────────────────────────────────────────
# Forrásnyelv
# ────────────────────────────────────────────────────────────────────────────
#
# A pipeline alapesetben angol feliratból fordít, de nem mindig van angol
# sáv (pl. a kiadó rossz sávot muxol be), ezért a forrásnyelv váltható.
#
# A kulcs az ISO 639-2/B kód — ugyanaz, amit az mkv-k a feliratsávok
# nyelvcímkéjeként használnak, és amit a fájlnév-konvenció is visel
# (`Sorozat - S01E01.eng.srt`), így a fájlnévből felismerhető.
#
# Érték: (magyar név, formalitás-jelölés leírása | None)
#
# A második elem azt mondja meg, hogy a forrásnyelv GRAMMATIKAILAG jelöli-e a
# tegezés/magázás megfelelőjét. Ez a fordító- és regiszter-promptokba kerül:
# ahol van ilyen jel, ott a tegezés/magázás nem következtetés, hanem leolvasás.
# Az angol az egyetlen, ahol nincs (`you` mindenre) — a pipeline eredetileg
# emiatt kerülgeti ezt a döntést.
SOURCE_LANGS = {
    "eng": ("angol",      None),
    "ger": ("német",      "Sie/du, Ihnen/Ihre, Herr/Frau + vezetéknév"),
    "fre": ("francia",    "vous/tu — FIGYELEM: a `vous` többes szám is lehet, "
                          "csak egyetlen megszólítottnál számít magázásnak"),
    "spa": ("spanyol",    "usted/tú, ustedes/vosotros"),
    "por": ("portugál",   "o senhor / a senhora vs. você/tu"),
    "ita": ("olasz",      "Lei/tu"),
    "rus": ("orosz",      "вы/ты"),
    "pol": ("lengyel",    "pan/pani + 3. személy vs. ty"),
    "tur": ("török",      "siz/sen, -sınız/-sin igerag"),
    "chi": ("kínai",      "您/你"),
    "jpn": ("japán",      "keigo: です・ます és tiszteleti alakok vs. plain form"),
    "kor": ("koreai",     "beszédszintek: -습니다/-요 vs. banmal; -씨/-님 utótag"),
    "vie": ("vietnámi",   "rokonsági megszólítások rendszere (anh/chị/em/ông/bà)"),
    "ind": ("indonéz",    "Anda / Bapak / Ibu vs. kamu"),
    "may": ("maláj",      "anda/awak vs. kau"),
    "tha": ("thai",       "ครับ/ค่ะ udvariassági partikulák"),
    "hin": ("hindi",      "आप vs. तुम/तू"),
    "ara": ("arab",       "حضرتك és többes tiszteleti alakok"),
}

# Gyakori rövidítések és ISO 639-1 kódok a fenti kulcsokra.
SOURCE_LANG_ALIASES = {
    "en": "eng", "de": "ger", "deu": "ger", "fr": "fre", "fra": "fre",
    "es": "spa", "pt": "por", "it": "ita", "ru": "rus", "pl": "pol",
    "tr": "tur", "zh": "chi", "zho": "chi", "cmn": "chi", "ja": "jpn",
    "ko": "kor", "vi": "vie", "id": "ind", "ms": "may", "th": "tha",
    "hi": "hin", "ar": "ara",
}

DEFAULT_SOURCE_LANG = "eng"


def normalize_source_lang(value):
    """Nyelvkód normalizálása a SOURCE_LANGS kulcsaira, vagy None."""
    if not value:
        return None
    key = str(value).strip().lower()
    key = SOURCE_LANG_ALIASES.get(key, key)
    return key if key in SOURCE_LANGS else None


def detect_source_lang(path):
    """Forrásnyelv felismerése a fájl- vagy mappanév utolsó `.kód` tagjából.

    A konvenció `Sorozat - S01E01.eng.srt`; a split ebből
    `blocks/Sorozat - S01E01.eng` mappanevet csinál, ezért mindkettő
    ugyanígy vizsgálható. Ismeretlen vagy hiányzó tag esetén None.
    """
    if not path:
        return None
    name = os.path.basename(str(path).rstrip("/\\"))
    if name.lower().endswith(".srt"):
        name = name[: -len(".srt")]
    _, dot, tag = name.rpartition(".")
    if not dot:
        return None
    return normalize_source_lang(tag)


def resolve_source_lang(cli_value=None, path=None):
    """Feloldja, melyik forrásnyelvvel dolgozunk.

    Precedencia (a legerősebb nyer):
      1. cli_value          — a --source-lang kapcsoló
      2. SUBTR_SOURCE_LANG  — env
      3. path               — a fájl- vagy mappanév `.kód` tagja
      4. DEFAULT_SOURCE_LANG ("eng")
    """
    for candidate in (cli_value, os.environ.get("SUBTR_SOURCE_LANG", "")):
        code = normalize_source_lang(candidate)
        if code:
            return code
    return detect_source_lang(path) or DEFAULT_SOURCE_LANG


def source_lang_name(code) -> str:
    """A nyelv magyar neve (pl. "angol"). Ismeretlen kódnál az alapértelmezetté."""
    entry = SOURCE_LANGS.get(code) or SOURCE_LANGS[DEFAULT_SOURCE_LANG]
    return entry[0]


def source_lang_article(code) -> str:
    """A nyelvnév elé való határozott névelő: "az angol", de "a német"."""
    return "az" if source_lang_name(code)[:1].lower() in "aáeéiíoóöőuúüű" else "a"


def the_source_lang(code) -> str:
    """Névelős alak promptokba: "az angol" / "a német" / "az olasz"."""
    return f"{source_lang_article(code)} {source_lang_name(code)}"


def source_lang_formality(code):
    """A forrásnyelv formalitás-jelölésének leírása, vagy None, ha nem jelöli."""
    entry = SOURCE_LANGS.get(code) or SOURCE_LANGS[DEFAULT_SOURCE_LANG]
    return entry[1]


def source_lang_help() -> str:
    """--help szöveg a --source-lang kapcsolóhoz."""
    codes = ", ".join(sorted(SOURCE_LANGS))
    return (f"A forrásfelirat nyelve (default: a fájlnév `.kód` tagjából, "
            f"különben {DEFAULT_SOURCE_LANG}; env: SUBTR_SOURCE_LANG). "
            f"Lehet: {codes}")


def add_source_lang_argument(parser) -> None:
    """A közös --source-lang kapcsoló felvétele egy argparse parserre."""
    parser.add_argument("--source-lang", type=str, default=None,
                        help=source_lang_help())
