"""Közös sorozat- és fordítási szabályzat betöltése minden providerhez."""

from pathlib import Path


BASE_CONTEXT_FILES = ("TRANSLATION.md", "CLAUDE.md")
LOCAL_CONTEXT_FILE = "TRANSLATION.local.md"


def load_translation_context() -> str:
    """A verziózott alapot és az opcionális, gitignore-os helyi kontextust tölti be."""
    base = ""
    for name in BASE_CONTEXT_FILES:
        path = Path(name)
        if path.is_file():
            base = path.read_text(encoding="utf-8")
            break

    local_path = Path(LOCAL_CONTEXT_FILE)
    if local_path.is_file():
        local = local_path.read_text(encoding="utf-8").strip()
        if local:
            return f"{base.rstrip()}\n\n=== HELYI SOROZATKONTEXTUS ===\n{local}\n"
    return base
