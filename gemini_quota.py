#!/usr/bin/env python3
"""
gemini_quota.py — kompatibilitási shim.

A tényleges implementáció a subtr/quota.py-ba költözött (refaktor 5. lépés).
Ez a fájl két okból marad meg:
  1. CLI-ként is hívják (`python3 gemini_quota.py --days 7` stb.)
  2. Modulként is importálják (`import gemini_quota as _gq`) más scriptekből,
     ezért minden korábban publikus nevet explicit re-exportál.
"""

from subtr.quota import (
    KEEP_DAYS,
    LOCK_TIMEOUT,
    LOCK_STALE,
    KNOWN_LIMITS,
    DEFAULT_LIMIT,
    ledger_path,
    key_fingerprint,
    pacific_now,
    today_key,
    hours_to_reset,
    record,
    note_limit,
    forget_limit,
    note_exhausted,
    note_limit_from_error,
    status,
    preflight,
    main,
)

__all__ = [
    "KEEP_DAYS",
    "LOCK_TIMEOUT",
    "LOCK_STALE",
    "KNOWN_LIMITS",
    "DEFAULT_LIMIT",
    "ledger_path",
    "key_fingerprint",
    "pacific_now",
    "today_key",
    "hours_to_reset",
    "record",
    "note_limit",
    "forget_limit",
    "note_exhausted",
    "note_limit_from_error",
    "status",
    "preflight",
    "main",
]

if __name__ == "__main__":
    main()
