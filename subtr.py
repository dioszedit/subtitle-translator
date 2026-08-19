#!/usr/bin/env python3
"""subtr — a feliratfordító pipeline egyparancsos CLI-je.

    py subtr.py <parancs> [argumentumok...]        (Windows)
    python3 subtr.py <parancs> [argumentumok...]   (macOS/Linux)

Parancsok listája: py subtr.py --help
"""

from subtr.cli import main

if __name__ == "__main__":
    main()
