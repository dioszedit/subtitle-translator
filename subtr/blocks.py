"""Blokk-fájl konvenció és checkpoint-segédek.

A pipeline fájlnév-kontraktusa (split_srt írja, minden fordító és a merge
olvassa) EGY helyen: a `*_block_*.srt` az input blokk, a `*_block_*_HUN.srt`
a kész fordítás. A checkpoint-logika ("kész = van _HUN párja") is itt él.
"""

import glob
import os
import time

BLOCK_GLOB = "*_block_*.srt"
HUN_SUFFIX = "_HUN.srt"


def hun_path(block_path: str) -> str:
    """Az input blokkhoz tartozó kimeneti (_HUN) fájl útvonala."""
    return block_path[:-len(".srt")] + HUN_SUFFIX


def get_all_blocks(blocks_dir: str) -> list[str]:
    """Az összes input blokk (a _HUN kimenetek nélkül), név szerint rendezve."""
    all_files = sorted(glob.glob(os.path.join(blocks_dir, BLOCK_GLOB)))
    return [f for f in all_files if not f.endswith(HUN_SUFFIX)]


def get_pending_blocks(blocks_dir: str) -> list[str]:
    """A még lefordítatlan blokkok (nincs _HUN párjuk) — checkpoint-logika."""
    return [f for f in get_all_blocks(blocks_dir)
            if not os.path.isfile(hun_path(f))]


def safe_remove(filepath: str):
    """Fájl biztonságos törlése — Windows-on kezeli a fájl-zárolást."""
    try:
        if os.path.isfile(filepath):
            os.remove(filepath)
    except PermissionError:
        time.sleep(2)
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
        except PermissionError:
            print(f"  [!] Nem sikerült törölni (zárolva): {os.path.basename(filepath)}")
            print(f"      Töröld kézzel, majd futtasd újra a scriptet.")
