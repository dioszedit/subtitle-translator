"""Közös beállítás- és modell-feloldási logika minden providerhez és taskhoz.

A .env betöltése IMPORT-IDŐBEN, EGYSZER történik — ez ugyanaz a minta, mint a
repo több meglévő scriptjében. A python-dotenv csomag opcionális függőség:
ha nincs telepítve, ez a modul akkor is importálható marad, csak a .env
fájl nem töltődik be (pl. ha a környezeti változók már máshonnan jönnek).
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import find_dotenv, load_dotenv

    # A CWD-ből felfelé keresünk: a pipeline a sorozat mappájából fut, és
    # minden más út is CWD-relatív. A paraméter nélküli find_dotenv() a
    # csomag mappájából indulna — editable telepítés + sorozat-másolat esetén
    # a MÁSIK mappa .env-jét töltené be. Ha a CWD fölött nincs .env, marad a
    # régi, csomag-relatív keresés.
    load_dotenv(find_dotenv(usecwd=True) or None)
except ImportError:
    pass


TASKS = ("translate", "review", "glossary", "register")
PROVIDERS = ("gemini", "claude", "codex", "grok", "antigravity")
# A headless CLI-adapterek (subtr.providers közös felülete): a tasks réteg
# egyetlen ágon kezeli őket.
CLI_PROVIDERS = ("codex", "grok", "antigravity")

# CWD-relatív útvonalak, mint eddig is — NEM keresünk repo-gyökeret,
# a scripteket úgyis a repo gyökeréből futtatjuk.
GLOSSARY_PATH = "glossary.json"
# Alap-szótárak (műfaj × kultúra) mappája — a sorozat glossary.json-ja mellett;
# a glossary.json „meta.bases” listája választ belőlük. Lásd subtr/glossary.py.
GLOSSARIES_DIR = "glossaries"
TRANSLATION_MD = "TRANSLATION.md"
TRANSLATION_LOCAL_MD = "TRANSLATION.local.md"


def api_key(name: str = "GEMINI_API_KEY") -> str:
    """A megadott nevű env-változó értéke, vagy üres string, ha nincs beállítva."""
    return os.environ.get(name, "") or ""


# A Google által kivezetett Gemini API-modellek → amire a Google átirányítja őket.
# A hívás így is működne (a Google átirányít), de a kvóta-nyilvántartás a
# modellnévhez kötött, és a régi név bármikor megszűnhet — ezért cseréljük.
DEPRECATED_GEMINI_MODELS = {
    "gemini-3.5-flash": ("gemini-3.8-flash", "2026-10-10"),
    "gemini-3.6-flash": ("gemini-3.8-flash", "2026-10-19"),
    "gemini-3.7-flash": ("gemini-3.8-flash", "2026-10-10"),
}


# Az Antigravity CLI (`agy models`) kínálatából 2026-10-13-án kikerült Gemini-modellek → utód.
# Nem szűntek meg: a hivatalos modell-lista (antigravity.google/docs/models) szerint
# azóta CSAK Enterprise-előfizetésben érhetők el. Ezért csak akkor cseréljük őket,
# ha a felhasználó `agy models` listájában tényleg nincsenek benne — az agy NEM
# irányít át, a régi névvel a hívás hibával leállna.
# Az effort-utótag (-high/-medium/-low) megmarad, ha az utódnak is van ilyen.
DEPRECATED_ANTIGRAVITY_MODELS = {
    "gemini-3.1-pro": ("gemini-3.8-flash", "2026-10-13"),
    "gemini-3.6-flash": ("gemini-3.8-flash", "2026-10-13"),
    "gemini-3.7-flash": ("gemini-3.8-flash", "2026-10-13"),
}

_AGY_MODELS_CACHE = {}


def antigravity_available_models():
    """Az `agy models` által kínált modell-azonosítók halmaza, vagy None, ha nem
    kérdezhető le (nincs `agy`, hiba, timeout). Folyamatonként egyszer fut."""
    if "models" not in _AGY_MODELS_CACHE:
        import shutil
        import subprocess
        result = None
        agy = shutil.which("agy")
        if agy:
            try:
                proc = subprocess.run([agy, "models"], capture_output=True,
                                      text=True, encoding="utf-8", timeout=60)
                if proc.returncode == 0:
                    ids = {line.split()[0] for line in proc.stdout.splitlines()
                           if line.strip() and not line.startswith("Fetching")}
                    result = ids or None
            except (OSError, subprocess.SubprocessError):
                result = None
        _AGY_MODELS_CACHE["models"] = result
    return _AGY_MODELS_CACHE["models"]


def replace_deprecated(provider: str, model):
    """Kivezetett modellnél figyelmeztet, és az utódját adja vissza."""
    if not model:
        return model
    if provider == "gemini" and model in DEPRECATED_GEMINI_MODELS:
        successor, since = DEPRECATED_GEMINI_MODELS[model]
        print(f"FIGYELEM: a {model} modellt a Google {since}-én kivezette (deprecated), "
              f"a hívásokat a {successor} modellre irányítja át — ezt használjuk. "
              f"Frissítsd a --model kapcsolót / a .env modell-sorait.",
              file=sys.stderr)
        return successor
    if provider == "antigravity":
        base, _, effort = model.rpartition("-")
        if effort not in ("high", "medium", "low"):
            base, effort = model, ""
        if base in DEPRECATED_ANTIGRAVITY_MODELS:
            available = antigravity_available_models()
            if available is not None and model in available:
                return model  # pl. Enterprise-előfizetés: nálad elérhető
            new_base, since = DEPRECATED_ANTIGRAVITY_MODELS[base]
            successor = f"{new_base}-{effort}" if effort else new_base
            print(f"FIGYELEM: a {model} modell {since} óta csak Enterprise-előfizetésben "
                  f"érhető el az Antigravityben, a te `agy models` listádban nincs benne "
                  f"— helyette: {successor}. Frissítsd a --model kapcsolót / "
                  f"a .env modell-sorait.", file=sys.stderr)
            return successor
    return model



# ────────────────────────────────────────────────────────────────────────────
# Provider / modell / effort feloldása
# ────────────────────────────────────────────────────────────────────────────
#
# A kódban nincs beégetett provider vagy modellnév: minden alapérték a csomag
# melletti defaults.env-ben él, a .env / környezet azt írja felül, a parancssori
# kapcsoló pedig mindkettőt. Funkciónként egy hármas:
#
#   SUBTR_<TASK>_PROVIDER   SUBTR_<TASK>_MODEL   SUBTR_<TASK>_EFFORT
#
# és provider-szintű tartalék arra az esetre, ha a funkció nem a beállított
# providerével fut:
#
#   SUBTR_<PROVIDER>_MODEL  SUBTR_<PROVIDER>_EFFORT

DEFAULTS_PATH = Path(__file__).with_name("defaults.env")

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# Ezeknél a providereknél hat az effort; az antigravity-nél a modellnév utótagja.
EFFORT_PROVIDERS = ("claude", "antigravity")
ANTIGRAVITY_EFFORTS = ("low", "medium", "high")

SRC_CLI = "kapcsoló"
SRC_ENV = ".env"
SRC_DEFAULTS = "defaults.env"


class SettingsError(ValueError):
    """Hibás vagy hiányzó provider / modell / effort beállítás."""


def read_env_file(path) -> dict:
    """Egyszerű KEY=VALUE olvasó (# komment, üres sor kimarad) — a defaults.env-hez,
    hogy az alapértékek a python-dotenv nélkül is betöltődjenek."""
    values = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                value = value.split(" #", 1)[0].strip().strip("'\"")
                values[key.strip()] = value
    except OSError:
        pass
    return values


_DEFAULTS = read_env_file(DEFAULTS_PATH)


def _layers():
    """A beállítás-rétegek erősségi sorrendben: (név, kulcs→érték)."""
    return ((SRC_ENV, os.environ), (SRC_DEFAULTS, _DEFAULTS))


def _validate(provider: str, task: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Ismeretlen provider: {provider!r} (várt: {PROVIDERS})")
    if task not in TASKS:
        raise ValueError(f"Ismeretlen task: {task!r} (várt: {TASKS})")


def legacy_env_names() -> list:
    """A környezetben talált, már nem olvasott változónevek: (régi, teendő)."""
    found = []
    if "SUBTR_DEFAULT_PROVIDER" in os.environ:
        found.append(("SUBTR_DEFAULT_PROVIDER",
                      "funkciónként: " + ", ".join(
                          f"SUBTR_{t.upper()}_PROVIDER" for t in TASKS)))
    for provider in PROVIDERS:
        for kind in ("MODEL", "EFFORT"):
            for task in TASKS:
                old = f"SUBTR_{provider.upper()}_{kind}_{task.upper()}"
                if old in os.environ:
                    found.append((old, f"SUBTR_{task.upper()}_{kind} (és "
                                       f"SUBTR_{task.upper()}_PROVIDER={provider})"))
    return found


def check_legacy_env() -> None:
    found = legacy_env_names()
    if found:
        lines = ["a .env-ben / környezetben megszűnt változónév van:"]
        lines += [f"  {old}  →  {new}" for old, new in found]
        lines.append("Írd át az új nevekre (minta: .env.example; az érvényes "
                     "beállítást a `subtr config` mutatja).")
        raise SettingsError("\n".join(lines))


def _task_provider(task: str, start: int = 0):
    """A funkció beállított providere a `start`. rétegtől lefelé: (érték, forrás)."""
    key = f"SUBTR_{task.upper()}_PROVIDER"
    for name, layer in _layers()[start:]:
        value = (layer.get(key) or "").strip()
        if value:
            return value, f"{name}: {key}"
    return "", ""


def _lookup(kind: str, provider: str, task: str):
    """A funkció MODEL / EFFORT értéke a futó providerhez: (érték, forrás).

    A funkció-szintű sor csak akkor érvényes, ha ahhoz a providerhez tartozik,
    amelyik éppen fut: egy rétegbeli sor gazdája az a provider, amelyet a
    funkcióhoz ugyanaz vagy egy gyengébb réteg állít be. Így a defaults.env
    modellje nem megy át egy olyan providernek, amelyet csak a .env választott.
    Az üres érték is beállítás (modell: a CLI sajátja; effort: nincs szint).

    A rétegek sorban jönnek: a .env bármely sora — a provider-szintű is —
    erősebb a defaults.env-nél.
    """
    task_key = f"SUBTR_{task.upper()}_{kind}"
    provider_key = f"SUBTR_{provider.upper()}_{kind}"
    for index, (name, layer) in enumerate(_layers()):
        if task_key in layer and _task_provider(task, index)[0] == provider:
            return (layer[task_key] or "").strip(), f"{name}: {task_key}"
        if provider_key in layer:
            return (layer[provider_key] or "").strip(), f"{name}: {provider_key}"
    return "", "nincs beállítva"


def split_antigravity_effort(model: str):
    """'gemini-x-high' → ('gemini-x', 'high'); utótag nélkül (model, '')."""
    base, _, suffix = (model or "").rpartition("-")
    if base and suffix in ANTIGRAVITY_EFFORTS:
        return base, suffix
    return model or "", ""


@dataclass
class Settings:
    """Egy funkció feloldott beállítása. A `model` az, ami a providernek megy
    (antigravity-nél már az effort-utótaggal); az `effort` csak ott nem None,
    ahol külön kapcsolóként megy át (claude). A `shown_effort` a kijelzéshez
    való: az antigravity utótagját is tartalmazza."""
    task: str
    provider: str
    model: str | None
    effort: str | None
    shown_effort: str | None = None
    sources: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def resolve_settings(task: str, cli_provider=None, cli_model=None,
                     cli_effort=None) -> Settings:
    """A funkció providere, modellje és effortja.

      provider: --provider > SUBTR_<TASK>_PROVIDER
      modell:   --model    > SUBTR_<TASK>_MODEL  > SUBTR_<PROVIDER>_MODEL
      effort:   --effort   > SUBTR_<TASK>_EFFORT > SUBTR_<PROVIDER>_EFFORT

    előbb a .env / környezet rétegben (ott a funkció-, majd a provider-szintű
    sor), és csak utána ugyanígy a defaults.env-ben. Hibás vagy
    hiányzó beállításnál SettingsError — nincs néma visszaesés.
    """
    if task not in TASKS:
        raise ValueError(f"Ismeretlen task: {task!r} (várt: {TASKS})")
    check_legacy_env()
    upper = task.upper()
    sources, warnings = {}, []

    if cli_provider:
        provider, sources["provider"] = cli_provider, f"{SRC_CLI}: --provider"
    else:
        provider, sources["provider"] = _task_provider(task)
        if not provider:
            raise SettingsError(f"nincs provider beállítva: SUBTR_{upper}_PROVIDER "
                                f"(lehet: {', '.join(PROVIDERS)})")
    if provider not in PROVIDERS:
        raise SettingsError(f"ismeretlen provider: {provider!r} "
                            f"({sources['provider']}; lehet: {', '.join(PROVIDERS)})")

    if cli_model:
        model, sources["model"] = cli_model, f"{SRC_CLI}: --model"
    else:
        model, sources["model"] = _lookup("MODEL", provider, task)
    if cli_effort:
        effort, sources["effort"] = cli_effort, f"{SRC_CLI}: --effort"
    else:
        effort, sources["effort"] = _lookup("EFFORT", provider, task)
    if effort and effort not in EFFORT_LEVELS:
        raise SettingsError(f"érvénytelen effort: {effort!r} ({sources['effort']}; "
                            f"lehet: {', '.join(EFFORT_LEVELS)})")

    shown_effort = effort or None
    if provider == "antigravity":
        base, suffix = split_antigravity_effort(model)
        if suffix:
            # A modellnévbe írt utótag nyer — kivéve, ha az --effort kapcsoló
            # egy nem kapcsolóval megadott modellt pontosít.
            if effort and effort != suffix:
                if cli_effort and not cli_model:
                    suffix = ""
                else:
                    warnings.append(f"a modellnév utótagja ({model}) felülírja az "
                                    f"effortot ({effort}; {sources['effort']}).")
            if suffix:
                effort, sources["effort"] = suffix, sources["model"] + " (utótag)"
        if effort and effort not in ANTIGRAVITY_EFFORTS:
            raise SettingsError(f"az antigravity providernél az effort "
                                f"{' | '.join(ANTIGRAVITY_EFFORTS)} lehet (kaptam: "
                                f"{effort!r}; {sources['effort']})")
        if base and effort:
            model = f"{base}-{effort}"
        shown_effort, effort = effort or None, None
    elif provider not in EFFORT_PROVIDERS:
        if effort:
            warnings.append(f"az effort ({effort}; {sources['effort']}) a(z) {provider} "
                            f"providernél nem hat, kimarad.")
        effort = shown_effort = None

    model = replace_deprecated(provider, model) or None
    if provider == "gemini" and not model:
        raise SettingsError(f"a gemini providerhez kötelező a modell: állítsd be a "
                            f"SUBTR_{upper}_MODEL vagy a SUBTR_GEMINI_MODEL sort, "
                            f"vagy add meg a --model kapcsolót")
    return Settings(task, provider, model, effort or None, shown_effort,
                    sources, warnings)


def settings_or_exit(task: str, args) -> Settings:
    """A task-ok main()-jéhez: feloldás az argparse-eredményből; hibánál
    üzenet és kilépés, a figyelmeztetések kiírva."""
    try:
        settings = resolve_settings(task, getattr(args, "provider", None),
                                    getattr(args, "model", None),
                                    getattr(args, "effort", None))
    except SettingsError as e:
        print(f"HIBA: {e}")
        sys.exit(1)
    for warning in settings.warnings:
        print(f"FIGYELEM: {warning}")
    return settings


def add_provider_argument(parser, task: str, role: str = "Provider") -> None:
    parser.add_argument(
        "--provider", choices=PROVIDERS, default=None,
        help=f"{role} (alapérték: SUBTR_{task.upper()}_PROVIDER a .env-ből, "
             f"különben a defaults.env-ből — lásd: subtr config)")


def add_model_argument(parser, task: str) -> None:
    parser.add_argument(
        "--model", type=str, default=None,
        help=f"Modell-azonosító. Feloldás: --model > SUBTR_{task.upper()}_MODEL > "
             f"SUBTR_<PROVIDER>_MODEL (.env, különben defaults.env)")


def add_effort_argument(parser, task: str) -> None:
    parser.add_argument(
        "--effort", choices=EFFORT_LEVELS, default=None,
        help=f"Gondolkodási szint (claude: kapcsoló; antigravity: a modellnév "
             f"utótagja, low|medium|high; máshol nem hat). Feloldás: --effort > "
             f"SUBTR_{task.upper()}_EFFORT > SUBTR_<PROVIDER>_EFFORT")


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
    for label, candidate in (("--source-lang", cli_value),
                             ("SUBTR_SOURCE_LANG", os.environ.get("SUBTR_SOURCE_LANG", ""))):
        if not candidate or not str(candidate).strip():
            continue
        code = normalize_source_lang(candidate)
        if code:
            return code
        # Elgépelt kód ("german", "deutsch") némán angolra esne vissza, és a
        # felhasználó azt hinné, német promptot kap — ezért hangosan szólunk.
        print(f"FIGYELEM: ismeretlen forrásnyelv-kód a {label} értékében: "
              f"{str(candidate).strip()!r} — figyelmen kívül hagyva "
              f"(lehet: {', '.join(sorted(SOURCE_LANGS))})", file=sys.stderr)
    return detect_source_lang(path) or DEFAULT_SOURCE_LANG


def source_lang_origin(cli_value=None, path=None) -> str:
    """Honnan jött a feloldott forrásnyelv — az állapotkiíráshoz."""
    if normalize_source_lang(cli_value):
        return "--source-lang"
    if normalize_source_lang(os.environ.get("SUBTR_SOURCE_LANG", "")):
        return "SUBTR_SOURCE_LANG"
    if detect_source_lang(path):
        return "a fájl-/mappanévből"
    return "alapértelmezés"


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
