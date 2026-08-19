"""subtr — a feliratfordító pipeline egyparancsos CLI-je.

Használat:
    py subtr.py <parancs> [argumentumok...]
    python -m subtr <parancs> [argumentumok...]

A parancsok a pipeline lépései; a provider (gemini / claude / codex) ott,
ahol értelmezett, a --provider kapcsolóval választható. Részletek:
    py subtr.py <parancs> --help
"""

import importlib
import sys

# parancs → (modul, egysoros leírás). A sorrend a pipeline sorrendje —
# a `subtr --help` ebben a sorrendben listáz.
COMMANDS = {
    "split":      ("subtr.tasks.split",             "1.  SRT szétvágása blokkokra"),
    "glossary":   ("subtr.tasks.glossary_extract",  "1.5 Szójegyzék kinyerése (opcionális, --provider)"),
    "register":   ("subtr.tasks.register_extract",  "1.6 Megszólítási regiszter kinyerése (opcionális, --provider)"),
    "translate":  ("subtr.tasks.translate",         "2.  Blokkok fordítása (--provider kötelező vagy env)"),
    "merge":      ("subtr.tasks.merge",             "3.  Blokkok összefűzése egy SRT-vé"),
    "verify":     ("subtr.tasks.verify",            "4.  Strukturális ellenőrzés"),
    "review":     ("subtr.tasks.review",            "5.  Stilisztikai review (--provider, default: gemini)"),
    "apply":      ("subtr.tasks.apply_review",      "5b. Review-javaslatok interaktív átvezetése"),
    "apply-auto": ("subtr.tasks.apply_review_auto", "5c. Átvezetés döntés-fájlból, kérdés nélkül"),
    "resegment":  ("subtr.tasks.resegment",         "7.  Sorhossz-riport / újratördelés"),
    "quota":      ("subtr.quota",                   "    Gemini napi kvóta állása"),
}


def _usage() -> str:
    lines = ["Használat: subtr <parancs> [argumentumok...]", "", "Parancsok:"]
    for name, (_, desc) in COMMANDS.items():
        lines.append(f"  {name:<11} {desc}")
    lines += ["", "Egy parancs kapcsolói: subtr <parancs> --help"]
    return "\n".join(lines)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help"):
        print(_usage())
        return
    cmd = argv[0]
    if cmd not in COMMANDS:
        print(f"HIBA: ismeretlen parancs: {cmd!r}\n")
        print(_usage())
        sys.exit(2)

    module = importlib.import_module(COMMANDS[cmd][0])
    # A task-parserek a sys.argv[0]-ból veszik a prog nevet — így a
    # `subtr translate --help` fejlécében is a parancs neve áll.
    sys.argv = [f"subtr {cmd}"] + argv[1:]
    module.main()
