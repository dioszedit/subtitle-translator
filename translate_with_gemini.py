#!/usr/bin/env python3
"""Kompatibilitási wrapper — a fordítási logika a subtr.tasks.translate modulban él.

Használat és kapcsolók: python translate_with_gemini.py --help
"""
from subtr.tasks.translate import main

if __name__ == "__main__":
    main("gemini")
