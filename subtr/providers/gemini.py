"""Gemini API adapter — retry, átmeneti hibák, kvóta-könyvelés EGY helyen.

A refaktor előtt a retry-ciklus két teljes másolatban élt (translate/review),
a glossary/register gemini-ágából pedig hiányzott. Innentől minden Gemini-hívás
ugyanazon a `call_json()`-on megy át, és egységesen kapja:
  - exponenciális backoff-ot 429/5xx-re és hálózati hibákra,
  - a 429-ből a napi limit megtanulását (gemini_quota),
  - a sikeres hívás kvóta-könyvelését (a parse ELŐTT — a blokkolt válasz is
    fogyaszt kvótát),
  - üres/blokkolt válaszra retry-t.

A séma kétféle lehet:
  - pydantic BaseModel osztály → a válasz `response.parsed` (a hívó típusos
    objektumot kap),
  - sima dict (JSON Schema, Codex-alakban additionalProperties-szel) → az
    adapter no_additional()-lel Gemini-alakra hozza, és json.loads-olt dict-et
    ad vissza.
"""

import json
import time

from subtr import config
from subtr.providers.base import no_additional

# Kvótakövetés — gépszintű, API kulcs szerint. Ha a modul hiányzik, a hívás
# fut tovább: a kvótakövetés kényelmi funkció, nem állíthatja meg a munkát.
try:
    from subtr import quota as _gq
except Exception:
    _gq = None

# Külső függőségek — lazy, hogy az importáló --help-je függőség nélkül is fusson.
try:
    from google import genai
    from google.genai import types
    from google.genai import errors as genai_errors
    DEPS_OK = True
    DEPS_ERROR = None
except ImportError as _e:
    genai = types = genai_errors = None
    DEPS_OK = False
    DEPS_ERROR = str(_e)

RETRY_BASE_DELAY = 5   # másodperc — exponential backoff alapja
MAX_RETRIES_DEFAULT = 4


def make_client(api_key: str | None = None):
    """Gemini kliens. api_key nélkül a config-ból (env/.env) jön."""
    key = api_key or config.api_key("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY nincs beállítva. Tedd a .env fájlba.")
    return genai.Client(api_key=key)


def is_transient_error(e: Exception) -> bool:
    """Hálózati / átmeneti hiba, amit érdemes újrapróbálni."""
    if isinstance(e, (ConnectionError, TimeoutError)):
        return True
    mod = type(e).__module__ or ""
    return mod.split(".")[0] in ("httpx", "httpcore", "anyio", "ssl")


def preflight(model: str, needed: int = 0) -> None:
    """Futás előtti kvóta-jelzés (nem állítja meg a futást)."""
    if _gq:
        try:
            _gq.preflight(model, needed=needed)
        except Exception:
            pass


def call_json(client, model: str, prompt: str, *, schema,
              system: str | None = None, temperature: float = 0.2,
              max_retries: int = MAX_RETRIES_DEFAULT):
    """Egy Gemini API hívás retry-logikával.

    Visszaad: (parsed | None, err_msg | None). A parsed pydantic objektum
    (ha a schema BaseModel osztály) vagy dict (ha a schema JSON-séma dict).
    """
    dict_schema = isinstance(schema, dict)
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=no_additional(schema) if dict_schema else schema,
    )

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=cfg,
            )
            # A hívás lefutott a modellen → fogyasztotta a napi kvótát.
            # (Az üres/blokkolt válasz is, ezért a parse ELŐTT könyvelünk.)
            if _gq:
                try:
                    _gq.record(model)
                except Exception:
                    pass
            if dict_schema:
                try:
                    parsed = json.loads(response.text)
                except (json.JSONDecodeError, TypeError):
                    parsed = None
            else:
                parsed = response.parsed
            if parsed is None:
                # Blokkolt/csonka válasz gyakran átmeneti — megér egy retry-t
                last_err = "üres / blokkolt válasz"
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    print(f"  Üres/blokkolt válasz, újrapróbálás {delay}s múlva... ({attempt}/{max_retries})")
                    time.sleep(delay)
                    continue
                return None, "[Üres / blokkolt válasz a Gemini-től]"
            return parsed, None
        except genai_errors.APIError as e:
            last_err = e
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            # 429-ből megtanuljuk a modell tényleges NAPI limitjét. Csak a napi
            # (PerDay) kvóta számít — a percenkénti 429-et, ami magas
            # párhuzamosságnál rutinszerű, az alábbi retry-ág kezeli, és nem
            # jelenti azt, hogy a napi keret elfogyott.
            if status == 429 and _gq:
                try:
                    _gq.note_limit_from_error(model, e)
                except Exception:
                    pass
            if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  API hiba ({status}), újrapróbálás {delay}s múlva... ({attempt}/{max_retries})")
                time.sleep(delay)
                continue
            return None, f"[API hiba: {e}]"
        except Exception as e:
            last_err = e
            if is_transient_error(e) and attempt < max_retries:
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"  Hálózati hiba ({type(e).__name__}), újrapróbálás {delay}s múlva... ({attempt}/{max_retries})")
                time.sleep(delay)
                continue
            return None, f"[Váratlan hiba: {e}]"
    return None, f"[{max_retries} próbálkozás után sem sikerült: {last_err}]"
