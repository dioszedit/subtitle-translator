"""Provider-adapterek — a "prompt + séma → strukturált JSON" réteg.

Egy provider-adapter dolga szándékosan szűk: egy promptot (opcionális
system-utasítással és JSON-sémával) strukturált válasszá alakít, a saját
átviteli részleteivel együtt (retry, kvóta, subprocess). A feladat-logika
(mit kérdezünk, hogyan daraboljuk, mit kezdünk a válasszal) a subtr.tasks
rétegben él, provider-függetlenül.

Kivétel (dokumentált): a Claude fordítási útja nem szöveg-transzformer —
az agent maga írja a kimeneti fájlt (lásd claude_cli.translate_block_to_file).

A HEADLESS CLI-ADAPTEREK (codex_cli, grok_cli, antigravity_cli) AZONOS
FELÜLETET ADNAK, hogy a
tasks réteg egyetlen ággal kezelhesse őket (korábban minden task két, csak a
függvénynevekben eltérő másolatot hordozott):
    LABEL          "Codex" / "Grok" / "Antigravity" — kiírásokhoz
    MISSING_HINT   a "nem található" hibaüzenet
    find_cli()     a parancs útvonala vagy None
    RunError       a hívás hibája (CliRunError leszármazott)
    run_json(prompt, schema, *, timeout, model=None, cli_bin=None) -> dict
"""


import re

# Keret-kimerülés (előfizetéses limit, elfogyott kredit) a provider SAJÁT
# üzenetében. Csak ott hívható, ahol a szöveg biztosan a providertől jön
# (stderr, a CLI hiba-eseményének üzenete) — a modell válaszában feliratszöveg
# van, abban ezek a szavak bármikor előfordulhatnak.
_QUOTA_SIGNAL_RE = re.compile(
    r"usage limit|hit your (?:usage )?limit|"
    r"(?:\d+.?hour|hourly|daily|weekly|monthly|session|plan|message) limit (?:reached|exceeded|hit)|"
    r"\blimit reached\b|rate.?limit.?(?:error|exceeded|reached)|"
    r"quota (?:exceeded|exhausted|will reset)|exceeded your (?:current )?quota|"
    r"exhausted your (?:capacity|quota)|insufficient[_ ]quota|"
    r"out of credits|insufficient credit", re.I)
# Átmeneti kapacitáshiány — nem a felhasználó kerete fogyott el, egy perc múlva
# megy tovább. Ha ilyen jel is van az üzenetben, NEM tekintjük kimerülésnek.
_TRANSIENT_SIGNAL_RE = re.compile(
    r"no capacity|overloaded|temporarily|try again (?:later|in a)|"
    r"\b(?:500|502|503|504)\b|unavailable", re.I)


def quota_signal(provider_message) -> bool:
    """Keret-kimerülésre utal-e a provider saját üzenete."""
    text = str(provider_message or "")
    return bool(_QUOTA_SIGNAL_RE.search(text)) and not _TRANSIENT_SIGNAL_RE.search(text)


class CliRunError(RuntimeError):
    """Egy headless CLI (Codex, Grok, Antigravity) nem futott le, vagy nem adott érvényes
    JSON választ. A konkrét adapterek ebből származtatnak.

    `quota`: az adapter állítja be, ha a provider saját üzenete keret-kimerülést
    jelez — a tasks réteg ebből tudja, hogy a hátralévő hívások is elbuknának.
    """

    def __init__(self, message="", *, quota: bool = False):
        super().__init__(message)
        self.quota = bool(quota)


def get_provider(name: str):
    """Adapter-modul név szerint. Lazy import, hogy a hiányzó függőség
    (pl. google-genai) csak a ténylegesen használt providernél fájjon."""
    if name == "gemini":
        from subtr.providers import gemini
        return gemini
    if name == "claude":
        from subtr.providers import claude_cli
        return claude_cli
    if name == "codex":
        from subtr.providers import codex_cli
        return codex_cli
    if name == "grok":
        from subtr.providers import grok_cli
        return grok_cli
    if name == "antigravity":
        from subtr.providers import antigravity_cli
        return antigravity_cli
    raise ValueError(f"Ismeretlen provider: {name!r} "
                     "(várt: gemini, claude, codex, grok, antigravity)")
