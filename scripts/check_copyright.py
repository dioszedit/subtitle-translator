#!/usr/bin/env python3
"""
Commit előtti szűrő: jogvédett / sorozat-specifikus tartalom és titok ne
kerüljön a (nyilvános) repóba.

Mit néz — csak determinisztikus szabályokat, LLM nélkül:

  1. TILTOTT ÚTVONAL   .env, TRANSLATION.local.md, input/ output/ blocks/ tartalma,
                        felirat- és médiafájlok (.srt .vtt .ass .mkv …), review-
                        riportok, decisions.json — akkor is, ha `git add -f`-fel
                        került be a gitignore ellenére.
  2. TITOK              API-kulcs minták (sk-ant-…, AIza…, xai-…, ghp_…) és
                        kitöltött *_API_KEY=… sor (a placeholder, pl.
                        `your-api-key-here`, rendben van).
  3. FELIRAT-TÖMEG      egy fájlban túl sok SRT-időbélyeg (`00:00:01,000 --> …`)
                        vagy túl sok ♪-sor: egy-két cue tesztfixture-nek jó, egy
                        teljes blokk vagy dalszöveg nem.
  4. SOROZAT-TERMINUS   az AKTUÁLIS sorozat címei és szereplőnevei — automatikusan
                        a TRANSLATION.local.md-ből és a glossary.json-ból — plus a
                        gitignore-olt `.copyright-blocklist` sorai (régebbi
                        sorozatok, amiket kézzel írsz bele). Egész szóra, kis-/
                        nagybetű-függetlenül, fájlnévben is.

Használat:
  python3 scripts/check_copyright.py            # a stage-elt fájlok (pre-commit)
  python3 scripts/check_copyright.py --all      # minden verziózott fájl (audit)
  python3 scripts/check_copyright.py --terms    # csak listázza, milyen terminusokat keres

Kihagyás egyszer:  SKIP_COPYRIGHT_CHECK=1 git commit …   vagy   git commit --no-verify
Telepítés:         git config core.hooksPath .githooks
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL_MD = "TRANSLATION.local.md"
GLOSSARY = "glossary.json"
BLOCKLIST = ".copyright-blocklist"

# ── 1. tiltott útvonalak ────────────────────────────────────────────────────

MEDIA_EXT = {".srt", ".vtt", ".ass", ".ssa", ".sub", ".sup", ".idx",
             ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts",
             ".mp3", ".wav", ".flac", ".m4a"}

_FORBIDDEN_PATH_RULES: list[tuple[str, re.Pattern]] = [
    ("titkos konfig (.env)", re.compile(r"(^|/)\.env(\.local)?$")),
    ("sorozat-kontextus (TRANSLATION.local.md)", re.compile(r"(^|/)TRANSLATION\.local\.md$")),
    ("munkamappa tartalma (input/ output/ blocks/)",
     re.compile(r"(^|/)(input|output|blocks)/(?!\.gitkeep$).+")),
    ("review-riport", re.compile(r"_REVIEW_[A-Z0-9]+\.(json|txt)$")),
    ("review-döntésfájl", re.compile(r"(^|/)decisions\.json$")),
    ("futási napló", re.compile(r"(^|/)\.translate\.log")),
    ("generált system prompt", re.compile(r"(^|/)\.(translate|review_claude)_sys_prompt_")),
    ("helyi terminus-lista", re.compile(r"(^|/)\.copyright-blocklist$")),
]


def forbidden_path(path: str) -> str | None:
    p = path.replace("\\", "/")
    for label, rx in _FORBIDDEN_PATH_RULES:
        if rx.search(p):
            return label
    if Path(p).suffix.lower() in MEDIA_EXT:
        return f"felirat-/médiafájl ({Path(p).suffix.lower()})"
    return None


# ── 2. titkok ───────────────────────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Anthropic kulcs", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI kulcs", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("Google API kulcs", re.compile(r"AIza[0-9A-Za-z_\-]{30,}")),
    ("xAI kulcs", re.compile(r"xai-[A-Za-z0-9]{20,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("AWS kulcs", re.compile(r"AKIA[0-9A-Z]{16}")),
]
_KEY_ASSIGN_RE = re.compile(
    r"\b([A-Z][A-Z0-9_]*_(?:API_KEY|TOKEN|SECRET))\s*[=:]\s*[\"']?([^\s\"'#]+)")
_PLACEHOLDER_RE = re.compile(r"^(your[-_]|<|\.\.\.|\$\{|xxx|changeme|placeholder|none$|\*+$)", re.I)


def secret_findings(text: str) -> list[tuple[int, str]]:
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        for label, rx in _SECRET_PATTERNS:
            if rx.search(line):
                out.append((no, label))
                break
        else:
            m = _KEY_ASSIGN_RE.search(line)
            if m:
                value = m.group(2)
                if len(value) >= 16 and not _PLACEHOLDER_RE.match(value) \
                        and not value.endswith("..."):
                    out.append((no, f"kitöltött {m.group(1)}"))
    return out


# ── 3. felirat-tömeg ────────────────────────────────────────────────────────

CUE_LIMIT = 30      # tesztfixture-ben ma legfeljebb ~16 időbélyeg van
LYRIC_LIMIT = 12    # ♪-sorok; egy tesztben ma legfeljebb ~7

_CUE_RE = re.compile(r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}")


def bulk_findings(text: str) -> list[str]:
    out = []
    cues = len(_CUE_RE.findall(text))
    if cues >= CUE_LIMIT:
        out.append(f"{cues} SRT-időbélyeg egy fájlban (limit {CUE_LIMIT}) — ez egy felirat, nem fixture")
    lyrics = sum(1 for ln in text.splitlines() if "♪" in ln)
    if lyrics >= LYRIC_LIMIT:
        out.append(f"{lyrics} ♪-sor egy fájlban (limit {LYRIC_LIMIT}) — dalszöveg?")
    return out


# ── 4. sorozat-terminusok ───────────────────────────────────────────────────

MIN_TERM_LEN = 4
_YEAR_RE = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")
_PAREN_RE = re.compile(r"\s*\(([^()]+)\)\s*$")
_CAST_RE = re.compile(r"^\s*-\s+(?P<actor>[^()]+?)(?:\s+as\s+(?P<role>[^()]+?))?\s*(?:\([^)]*\))?\s*$")


def _clean(term: str) -> str:
    return " ".join((term or "").split())


def terms_from_local_md(text: str) -> set[str]:
    """Title / Hungarian title / Cast sorok → címek, natív cím, színész- és szerepnevek."""
    terms: set[str] = set()
    in_cast = False
    for raw in text.splitlines():
        line = raw.rstrip()
        low = line.lower()
        if low.startswith("title:"):
            value = _clean(line.split(":", 1)[1])
            m = _PAREN_RE.search(value)          # "Cím (2026) (natív)" → natív
            while m:
                inner = m.group(1).strip()
                if not _YEAR_RE.fullmatch(f"({inner})"):
                    terms.add(inner)
                value = value[:m.start()].rstrip()
                m = _PAREN_RE.search(value)
            terms.add(_YEAR_RE.sub("", value))
        elif low.startswith("hungarian title:"):
            value = _clean(line.split(":", 1)[1])
            if value and not value.upper().startswith("TODO"):
                terms.add(value)
        elif low.startswith("cast:"):
            in_cast = True
        elif in_cast:
            if line and not line.startswith("-") and not line.startswith(" "):
                in_cast = False           # következő szakasz
                continue
            m = _CAST_RE.match(line)
            if m:
                terms.add(_clean(m.group("actor")))
                if m.group("role"):
                    # "Shen Qing — Lu Yan főnöke" → csak a név
                    terms.add(_clean(re.split(r"\s+[—–-]\s+", m.group("role"))[0]))
    return {t for t in terms if t and not t.upper().startswith("TODO")}


def terms_from_glossary(text: str) -> set[str]:
    """meta.series + character_names (en és hu)."""
    try:
        data = json.loads(text.lstrip("﻿"))
    except ValueError:
        return set()
    terms: set[str] = set()
    series = _clean(str((data.get("meta") or {}).get("series") or ""))
    if series:
        terms.add(series)
    for e in data.get("character_names") or []:
        if isinstance(e, dict):
            for k in ("en", "hu"):
                v = _clean(str(e.get(k) or ""))
                if v:
                    terms.add(v)
    return terms


def terms_from_blocklist(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(_clean(line))
    return out


def usable_terms(terms: set[str]) -> list[str]:
    """Rövid / generikus tokenek kiszűrése — a 3 betűs név több hamis riasztást
    adna, mint amennyit fog. Hosszabb elöl, hogy a riport olvashatóbb legyen."""
    return sorted({t for t in terms if len(t) >= MIN_TERM_LEN}, key=lambda t: (-len(t), t))


def collect_terms(root: Path = REPO) -> list[str]:
    terms: set[str] = set()
    for name, fn in ((LOCAL_MD, terms_from_local_md),
                     (GLOSSARY, terms_from_glossary),
                     (BLOCKLIST, terms_from_blocklist)):
        p = root / name
        if p.is_file():
            try:
                terms |= fn(p.read_text(encoding="utf-8"))
            except OSError:
                pass
    return usable_terms(terms)


def term_findings(text: str, terms: list[str]) -> list[tuple[int, str]]:
    if not terms:
        return []
    rx = re.compile("|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in terms), re.IGNORECASE)
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        m = rx.search(line)
        if m:
            out.append((no, m.group(0)))
    return out


# ── fájlok begyűjtése és a riport ───────────────────────────────────────────

def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True,
                          capture_output=True).stdout


def staged_files() -> list[tuple[str, bytes]]:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    out = []
    for n in names:
        if n:
            path = n.decode("utf-8", "surrogateescape")
            out.append((path, _git("show", f":{path}")))
    return out


def all_tracked_files() -> list[tuple[str, bytes]]:
    names = _git("ls-files", "-z").split(b"\0")
    out = []
    for n in names:
        if n:
            path = n.decode("utf-8", "surrogateescape")
            p = REPO / path
            if p.is_file():
                out.append((path, p.read_bytes()))
    return out


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def check_files(files: list[tuple[str, bytes]], terms: list[str]) -> list[str]:
    """Minden találat egy sor: `útvonal[:sor]: szabály — részlet`."""
    findings: list[str] = []
    for path, data in files:
        label = forbidden_path(path)
        if label:
            findings.append(f"{path}: TILTOTT ÚTVONAL — {label}")
            continue
        for no, hit in term_findings(path, terms):
            findings.append(f"{path}: SOROZAT-TERMINUS a fájlnévben — „{hit}”")
        if is_binary(data):
            continue
        text = data.decode("utf-8", "replace")
        for no, label in secret_findings(text):
            findings.append(f"{path}:{no}: TITOK — {label}")
        for msg in bulk_findings(text):
            findings.append(f"{path}: FELIRAT-TÖMEG — {msg}")
        for no, hit in term_findings(text, terms):
            findings.append(f"{path}:{no}: SOROZAT-TERMINUS — „{hit}”")
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Jogvédett tartalom / titok szűrése commit előtt.")
    ap.add_argument("--all", action="store_true", help="minden verziózott fájl, nem csak a stage-eltek")
    ap.add_argument("--terms", action="store_true", help="csak a keresett terminusok listája")
    args = ap.parse_args(argv)

    if os.environ.get("SKIP_COPYRIGHT_CHECK"):
        print("check_copyright: kihagyva (SKIP_COPYRIGHT_CHECK).")
        return 0

    terms = collect_terms()
    if args.terms:
        print(f"{len(terms)} terminus ({LOCAL_MD}, {GLOSSARY}, {BLOCKLIST}):")
        for t in terms:
            print(f"  {t}")
        return 0

    try:
        files = all_tracked_files() if args.all else staged_files()
    except subprocess.CalledProcessError as e:
        print(f"check_copyright: git-hiba: {e.stderr.decode('utf-8', 'replace').strip()}")
        return 2

    findings = check_files(files, terms)
    if not findings:
        return 0

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("check_copyright: a commit LEÁLLÍTVA — jogvédett/sorozat-specifikus tartalom vagy titok:\n")
    for f in findings:
        print(f"  {f}")
    print(f"\n{len(findings)} találat. Javítsd, vagy ha biztosan hamis riasztás:")
    print("  SKIP_COPYRIGHT_CHECK=1 git commit …    (vagy: git commit --no-verify)")
    print(f"A keresett terminusok: python3 scripts/check_copyright.py --terms  "
          f"(forrás: {LOCAL_MD}, {GLOSSARY}, {BLOCKLIST})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
