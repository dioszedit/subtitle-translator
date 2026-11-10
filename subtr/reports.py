"""Review-riport kontraktus — fájlnevek, formázás, mentés EGY helyen.

A riport-utótag (`_REVIEW_CLAUDE.json` stb.) kontraktus: a `subtr.py apply`
globbal keresi, a review-triage skill `_REVIEW_*.json`-t vár. Az alakja itt
rögzül, és nem változhat a fogyasztók tudta nélkül.

Egy finding normalizált alakja (minden provider erre hozza):
    {"sorszam": int, "eredeti": str, "hiba": str, "javaslat": str}
a JSON-riportban kiegészülve a "chunk" mezővel.

Nem teljes lefedettségű riport — a JSON további mezőket kap, a teljes riportban
ezek NINCSENEK (a fogyasztó ebből tudja, hogy a találatlista nem az egész
feliratról szól):
  "total_chunks"   a felirat chunkjainak száma
  "missing_chunks" a kért tartományból nem lektorált chunkok (kvóta, hibás
                   chunk, megszakítás utáni --from-partial)
  "chunk_range"    [első, utolsó] — rész-tartomány riportja (--start-chunk /
                   --end-chunk): a tartományon kívüli chunkokat nem fedi

Részeredmény (`.partial`): a review chunkonként ide menti a kész találatokat,
hogy egy megszakadt futás folytatható legyen. Az elavult részeredmény
`.partial.stale` néven félrekerül. A kiterjesztése szándékosan nem
.json / .txt — sem a `subtr apply`, sem a `_REVIEW_*.json` glob nem veszi fel.
"""

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# reviewer-név → riport-utótag törzs (a .txt/.json és az opcionális
# --suffix a hívónál ragad hozzá)
REVIEW_SUFFIX = {
    "claude": "_REVIEW_CLAUDE",
    "gemini": "_REVIEW_GEMINI",
    "codex": "_REVIEW_CODEX",
    "grok": "_REVIEW_GROK",
    "antigravity": "_REVIEW_ANTIGRAVITY",
}


def report_paths(srt_path: Path, reviewer: str, suffix: str = ""):
    """(txt_path, json_path) a kontraktus szerint."""
    stem = srt_path.stem + REVIEW_SUFFIX[reviewer] + suffix
    return (srt_path.with_name(stem + ".txt"),
            srt_path.with_name(stem + ".json"))


def format_findings(findings: list[dict], chunk_num: int, total: int):
    """Normalizált találatokból szöveges riport-blokk (a bevált formátumban)."""
    if not findings:
        return None
    lines = [f"--- Chunk {chunk_num}/{total} ---"]
    for err in findings:
        lines.append(f'#{err["sorszam"]}: "{err["eredeti"]}"')
        lines.append(f"  → HIBA: {err['hiba']}")
        lines.append(f"  → JAVASLAT: {err['javaslat']}")
        lines.append("")
    return "\n".join(lines)


def write_reports(srt_path: Path, report_path: Path, json_path: Path, *,
                  reviewer: str, model_label: str,
                  finding_blocks: list[str], json_findings: list[dict],
                  errors: dict[int, str] | None = None,
                  total_chunks: int | None = None,
                  chunk_range: tuple[int, int] | None = None):
    """A .txt és .json riport mentése a bevált szerkezetben.

    `errors`: {chunk sorszáma: hibaüzenet} a nem lektorált chunkokra. Ebből az
    EGY leírásból készül a .txt hibaszakasza és a JSON `missing_chunks` mezője
    is — ha van ilyen chunk, a JSON találat nélkül is elkészül, és jelzi a hiányt.
    `chunk_range`: (első, utolsó), ha a futás csak egy rész-tartományt lektorált.

    A .txt fejlécében a reviewer nagybetűs kezdőbetűvel jelenik meg
    (Claude/Gemini/Codex/Grok/Antigravity), a .json-ban kisbetűvel — ez a meglévő kontraktus.
    """
    errors = errors or {}
    missing_chunks = sorted(errors)
    total_label = total_chunks if total_chunks is not None else "?"
    error_chunks = [f"--- Chunk {i}/{total_label} ---\n{errors[i]}\n"
                    for i in missing_chunks]
    sections = []
    if finding_blocks:
        sections.append("\n".join(finding_blocks))
    if error_chunks:
        sections.append("=== HIBÁS / KIHAGYOTT CHUNKOK ===\n\n" + "\n".join(error_chunks))

    if sections:
        report_content = (
            f"Review riport ({reviewer.capitalize()}): {srt_path.name}\n"
            f"Modell: {model_label}\n"
            f"{'=' * 60}\n\n"
            + "\n\n".join(sections)
        )
        report_path.write_text(report_content, encoding="utf-8")
        print(f"\nRiport mentve: {report_path}")
        print(f"Találatok: {len(finding_blocks)} chunkban, hibás chunkok: {len(error_chunks)}")
    else:
        print("\nNincs hiba egyik chunkban sem!")
        _remove_stale(report_path)

    if json_findings or missing_chunks:
        data = {
            "source": srt_path.name,
            "reviewer": reviewer,
            "model": model_label,
        }
        if missing_chunks or chunk_range:
            data["total_chunks"] = total_chunks
        if chunk_range:
            data["chunk_range"] = list(chunk_range)
        if missing_chunks:
            data["missing_chunks"] = missing_chunks
        data["findings"] = json_findings
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"JSON riport mentve: {json_path}")
        if missing_chunks:
            print(f"HIÁNYOS riport: {len(missing_chunks)} chunk nincs lektorálva "
                  f"({chunk_ranges(missing_chunks)} / {total_label}).")
    else:
        _remove_stale(json_path)


def _remove_stale(path: Path) -> None:
    """Egy korábbi futás riportja, amire a mostani nem hozott találatot.

    Ha maradna, a `subtr apply` a már javított (vagy elvetett) találatokat
    ajánlaná fel újra — a mostani futás eredménye az, hogy NINCS találat, és
    a fájloknak ezt kell tükrözniük.
    """
    if path.exists():
        path.unlink()
        print(f"Elavult riport törölve (a mostani futásban nincs találat): {path.name}")


def chunk_ranges(numbers) -> str:
    """[1, 2, 3, 6] → '1–3, 6' (emberi olvasásra). Nem-szám elem kimarad."""
    out, run = [], []
    if isinstance(numbers, (str, bytes)) or not hasattr(numbers, "__iter__"):
        return "?"
    for n in sorted(n for n in numbers if isinstance(n, int)):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(run)
        run = [n]
    if run:
        out.append(run)
    return ", ".join(str(r[0]) if len(r) == 1 else f"{r[0]}–{r[-1]}" for r in out)


# ────────────────────────────────────────────────────────────────────────────
# Részeredmény (.partial) — megszakadt review folytatásához
# ────────────────────────────────────────────────────────────────────────────
#
# JSON Lines: az első sor a futás ujjlenyomata (beállítások), utána chunkonként
# egy sor, a chunk befejeztekor azonnal lemezre írva:
#   {"chunk": N, "hash": "...", "findings": [...]}   kész chunk
#   {"chunk": N, "hash": "...", "error": "..."}      hibára futott — NEM számít
#                                     késznek; az újrafutás a sor végén próbálja újra
# A "hash" a chunk lektorált szövegének (magyar + párosított forrás) ujjlenyomata:
# ha a felirat egy része megváltozott (pl. átvezetett javítások), csak az érintett
# chunkok eredménye évül el, a többi felhasználható marad.

STALE_SUFFIX = ".stale"


def partial_path(json_path: Path) -> Path:
    return json_path.with_suffix(".partial")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class PartialState:
    """A betöltött részeredmény.

    done      {chunk: findings}   — kész, és a chunk szövege azóta nem változott
    failed    {chunk: [üzenetek]} — korábban hibára futott (és nincs kész); a
                                    futások eltérő hibaüzenetei időrendben
    attempts  {chunk: N}          — hány sikertelen próbálkozás volt a chunkon
    outdated  [chunk, …]          — volt eredménye, de a chunk szövege megváltozott
    changed   [kulcs, …] | None   — a futás beállításai eltérnek: az EGÉSZ fájl
                                    más futáshoz tartozik (a hívó dönt a félretevésről)
    """
    done: dict = field(default_factory=dict)
    failed: dict = field(default_factory=dict)
    attempts: dict = field(default_factory=dict)
    outdated: list = field(default_factory=list)
    changed: list | None = None


def load_partial(path: Path, fingerprint: dict, chunk_hashes: dict) -> PartialState:
    """A részeredmény betöltése. Nincs fájl → üres állapot. Csonka (félbeírt)
    sor és hibás bájt kimarad. Olvasási hibánál OSError — a hívó kezeli."""
    if not path.exists():
        return PartialState()
    done, failed, attempts, outdated, header = {}, {}, {}, set(), None
    # errors="replace": egy több bájtos karakter közepén megszakadt írás ne
    # dobjon UnicodeDecodeError-t — az a sor úgyis érvénytelen JSON lesz.
    with open(path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if n == 0:
                header = row.get("fingerprint") if isinstance(row, dict) else None
                continue
            if not isinstance(row, dict) or not isinstance(row.get("chunk"), int):
                continue
            chunk = row["chunk"]
            if row.get("hash") != chunk_hashes.get(chunk):
                outdated.add(chunk)
                for store in (done, failed, attempts):
                    store.pop(chunk, None)
                continue
            outdated.discard(chunk)
            if isinstance(row.get("findings"), list):
                done[chunk] = row["findings"]
                failed.pop(chunk, None)
                attempts.pop(chunk, None)
            elif "error" in row:
                attempts[chunk] = attempts.get(chunk, 0) + 1
                history = failed.setdefault(chunk, [])
                if str(row["error"]) not in history:
                    history.append(str(row["error"]))
    if not isinstance(header, dict):
        return PartialState(changed=["fejléc"])
    changed = sorted(k for k in set(header) | set(fingerprint)
                     if header.get(k) != fingerprint.get(k))
    if changed:
        return PartialState(changed=changed)
    return PartialState(done, failed, attempts,
                        sorted(outdated - set(done) - set(failed)))


def start_partial(path: Path, fingerprint: dict) -> None:
    path.write_text(json.dumps({"fingerprint": fingerprint}, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _append_row(path: Path, row: dict) -> None:
    # Ha az előző írás félbeszakadt (nincs sorvég a fájl végén), az új sor a
    # csonkához ragadna, és betöltéskor mindkettő elveszne — előbb lezárjuk.
    lead = ""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    lead = "\n"
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(lead + json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def append_partial(path: Path, chunk: int, chunk_hash: str,
                   findings: list[dict]) -> None:
    _append_row(path, {"chunk": chunk, "hash": chunk_hash, "findings": findings})


def append_partial_error(path: Path, chunk: int, chunk_hash: str,
                         message: str) -> None:
    """Hibára futott chunk feljegyzése a TELJES üzenettel (a nem értelmezhető
    modellválasz nyers szövege is benne van — ne vesszen el egy újrafutásnál).
    A következő futás ezeket a sor végére teszi."""
    _append_row(path, {"chunk": chunk, "hash": chunk_hash, "error": str(message)})


def set_aside_partial(path: Path) -> Path | None:
    """Az elavult részeredményt nem töröljük: `<név>.partial.stale` néven
    félretesszük (a korábbit felülírva), hogy visszahozható legyen."""
    if not path.exists():
        return None
    stale = stale_path(path)
    os.replace(path, stale)
    return stale


def stale_path(path: Path) -> Path:
    return path.with_name(path.name + STALE_SUFFIX)


def discard_partial(path: Path) -> None:
    if path.exists():
        path.unlink()
