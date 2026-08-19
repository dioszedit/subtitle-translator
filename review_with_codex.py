#!/usr/bin/env python3
"""Kompatibilitási wrapper — a review-logika a subtr.tasks.review modulban él.

Használat és kapcsolók: python review_with_codex.py --help
"""
from subtr.tasks.review import main

if __name__ == "__main__":
    main("codex")
