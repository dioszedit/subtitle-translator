"""Gemini API adapter — retry, átmeneti hibák, kvóta-könyvelés EGY helyen.

A refaktor előtt a retry-ciklus két teljes másolatban élt (translate/review),
a glossary/register gemini-ágából pedig hiányzott. Innentől minden Gemini-hívás
ugyanazon a `call_json()`-on megy át, és egységesen kapja:
  - exponenciális backoff-ot 429/5xx-re és hálózati hibákra,
  - a 429-ből a napi limit megtanulását (gemini_quota),
  - a sikeres hívás kvóta-könyvelését (a parse ELŐTT — a blokkolt válasz is
    fogyaszt kvótát),
  - üres/blokkolt válaszra retry-t,
  - napi limitnél modellváltást (SUBTR_GEMINI_ON_QUOTA = off | ask | auto,
    tartaléklista: SUBTR_GEMINI_FALLBACK_MODELS — lásd subtr/gemini_models.py).
    A váltás folyamatszintű: a futás hátralévő hívásai már az új modellel mennek.
    Napi limitnél ugyanazt a modellt nem próbáljuk újra — aznap úgysem menne.

A séma kétféle lehet:
  - pydantic BaseModel osztály → a válasz `response.parsed` (a hívó típusos
    objektumot kap),
  - sima dict (JSON Schema, Codex-alakban additionalProperties-szel) → az
    adapter no_additional()-lel Gemini-alakra hozza, és json.loads-olt dict-et
    ad vissza.
"""

import json
import threading
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
MAX_SWITCHES = 5       # egy hívás legfeljebb ennyiszer válthat modellt

# Napi limit miatti modellváltások (folyamatszintű): kimerült → helyettesítő.
# A párhuzamos agentek közül csak egy kérdez / dönt; a többi a lock után már a
# kész döntést látja.
_SWITCH_LOCK = threading.Lock()
_SWITCHED = {}
# Kimerült modellek, amelyekre nem váltottunk (nincs tartalék / a felhasználó
# nem kérte) → a hibaüzenet. A további hívások ezzel KÉRÉS NÉLKÜL térnek vissza:
# aznap úgysem mennének, és mindegyik 429 egy-egy napló-írás lenne.
_DECLINED = {}


def effective_model(model: str) -> str:
    """A modell, amellyel a hívás ténylegesen megy (a váltások láncát követve)."""
    seen = set()
    while model in _SWITCHED and model not in seen:
        seen.add(model)
        model = _SWITCHED[model]
    return model


def switches() -> dict:
    """Az eddigi váltások (kimerült → helyettesítő)."""
    return dict(_SWITCHED)


def switch_summary() -> str:
    """A futás közbeni váltások egy sorban ('a → b, b → c'), vagy ''. Minden
    task ezzel jelzi az összegzésében, hogy a munka egy részét más modell végezte."""
    return ", ".join(f"{a} → {b}" for a, b in _SWITCHED.items())


def cancel_prompts() -> None:
    """Ctrl+C a fő szálon: a worker-szálon váró modellváltás-kérdés szakadjon meg
    (különben a ThreadPoolExecutor leállása a felhasználó válaszára várna)."""
    try:
        from subtr import gemini_models
        gemini_models.CANCEL.set()
    except Exception:
        pass


def reset_switches() -> None:
    with _SWITCH_LOCK:
        _SWITCHED.clear()
        _DECLINED.clear()


def _switch_after_exhaustion(model: str):
    """A napi limitbe futott modell helyettesítője, vagy None (nincs váltás)."""
    with _SWITCH_LOCK:
        if model in _SWITCHED:            # egy másik agent már döntött
            return effective_model(model)
        if model in _DECLINED:
            return None
        try:
            from subtr import gemini_models
            new = gemini_models.choose_fallback(model, tried=set(_SWITCHED))
        except Exception as e:
            print(f"  [!] Modellváltás sikertelen ({e}) — nem váltok.")
            new = None
        if new and new != model:
            _SWITCHED[model] = new
            print(f"  >>> MODELLVÁLTÁS: {model} → {new} — a futás hátralévő "
                  f"hívásai ezzel mennek.")
            return new
        _DECLINED.setdefault(model, f"[API hiba: a {model} napi kerete elfogyott "
                                    f"(429 RESOURCE_EXHAUSTED, quotaId: PerDay)]")
        return None


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


def daily_quota_exhausted(api_error, strict: bool = False) -> bool:
    """A hiba (kivétel vagy a call_json hibaszövege) a NAPI keret kimerülését
    jelzi-e. A percenkénti / token-alapú 429 nem az — lásd subtr/quota.py.
    strict=True: csak a strukturált quotaId alapján (modellváltáshoz)."""
    if not _gq:
        return False
    try:
        return _gq.is_daily_exhaustion(api_error, strict=strict)
    except Exception:
        return False


def call_json(client, model: str, prompt: str, *, schema,
              system: str | None = None, temperature: float = 0.2,
              max_retries: int = MAX_RETRIES_DEFAULT, meta: dict | None = None):
    """Egy Gemini API hívás retry-logikával.

    Visszaad: (parsed | None, err_msg | None). A parsed pydantic objektum
    (ha a schema BaseModel osztály) vagy dict (ha a schema JSON-séma dict).
    `meta` (opcionális dict): a hívás után meta["model"] az a modell, amellyel
    a hívás ténylegesen ment (napi limit miatti váltás után más, mint a kért).
    """
    dict_schema = isinstance(schema, dict)
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=no_additional(schema) if dict_schema else schema,
    )

    model = effective_model(model)
    if meta is not None:
        meta["model"] = model
    if model in _DECLINED:
        return None, _DECLINED[model]
    last_err = None
    attempt = switched = 0
    while attempt < max_retries:
        attempt += 1
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
            # Csak a strukturált (quotaId-s) napi limit vált modellt / hagyja el
            # az újrapróbálást: egy félreolvasott percenkénti 429 az egész
            # futást más modellre tenné.
            if status == 429 and daily_quota_exhausted(e, strict=True):
                new = (_switch_after_exhaustion(model)
                       if switched < MAX_SWITCHES else None)
                if new:
                    model, switched, attempt = new, switched + 1, 0
                    if meta is not None:
                        meta["model"] = model
                    continue
                # Aznap ezzel a modellel úgysem menne — nincs értelme várni; a
                # további hívások kérés nélkül ugyanezt kapják.
                _DECLINED[model] = f"[API hiba: {e}]"
                return None, _DECLINED[model]
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
