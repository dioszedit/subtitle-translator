"""subtr config — az érvényes provider / modell / effort funkciónként.

Megmutatja, mivel futna a négy LLM-es parancs ebből a mappából, és hogy
melyik érték honnan jön (.env / környezet vagy a csomag defaults.env-je).
Semmit nem hív meg és nem módosít.
"""

import argparse
import sys

from subtr import config


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Az érvényes provider / modell / effort a négy LLM-es parancshoz")
    parser.add_argument("--provider", choices=config.PROVIDERS, default=None,
                        help="Mit adna a feloldás, ha minden parancs ezzel a "
                             "providerrel futna (mint a parancsok --provider kapcsolója)")
    args = parser.parse_args(argv)

    try:
        config.check_legacy_env()
    except config.SettingsError as e:
        print(f"HIBA: {e}")
        sys.exit(1)

    print(f"Alapértékek: {config.DEFAULTS_PATH}")
    print("Felülírás:   .env / környezet, majd a parancsok kapcsolói\n")
    failed = False
    for task in config.TASKS:
        try:
            s = config.resolve_settings(task, cli_provider=args.provider)
        except config.SettingsError as e:
            print(f"{task}\n  HIBA: {e}\n")
            failed = True
            continue
        rows = (("provider", s.provider, s.sources["provider"]),
                ("modell", s.model or "(a CLI sajátja)", s.sources["model"]),
                ("effort", s.shown_effort or "(nincs megadva)", s.sources["effort"]))
        print(task)
        for label, value, source in rows:
            print(f"  {label:<9}{value:<28}{source}")
        for warning in s.warnings:
            print(f"  FIGYELEM: {warning}")
        print()
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
