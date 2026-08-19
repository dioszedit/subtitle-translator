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
