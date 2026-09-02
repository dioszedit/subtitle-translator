"""Provider-adapterek — a "prompt + séma → strukturált JSON" réteg.

Egy provider-adapter dolga szándékosan szűk: egy promptot (opcionális
system-utasítással és JSON-sémával) strukturált válasszá alakít, a saját
átviteli részleteivel együtt (retry, kvóta, subprocess). A feladat-logika
(mit kérdezünk, hogyan daraboljuk, mit kezdünk a válasszal) a subtr.tasks
rétegben él, provider-függetlenül.

Kivétel (dokumentált): a Claude fordítási útja nem szöveg-transzformer —
az agent maga írja a kimeneti fájlt (lásd claude_cli.translate_block_to_file).
"""


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
    raise ValueError(f"Ismeretlen provider: {name!r} (várt: gemini, claude, codex, grok)")
