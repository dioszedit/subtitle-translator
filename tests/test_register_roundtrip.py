"""register_extract — a TRANSLATION.local.md regiszter parse→render roundtrip."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr.tasks import register_extract as R

SAMPLE = """Title: Teszt sorozat

Megszólítási regiszter:   (frissítendő MINDEN epizód előtt)
  - Anna → Béla: MAGÁZ  (beosztott→főnök)
  - Anna ↔ Cili: TEGEZ  (barátnők)
  - alapértelmezés idegenekkel: MAGÁZ
  - váltás: Anna ↔ Béla TEGEZ a 3. rész után
"""


def test_parse_es_render_roundtrip(tmp_path):
    p = tmp_path / "local.md"
    p.write_text(SAMPLE, encoding="utf-8")
    _, pairs, others, has = R.parse_local(str(p))
    assert has
    assert len(pairs) == 2
    assert pairs[0] == {"a": "Anna", "b": "Béla", "mutual": False,
                        "form": "MAGÁZ", "note": "beosztott→főnök"}
    assert pairs[1]["mutual"] is True
    # az egyéb sorok (alapértelmezés, váltás) érintetlenül megmaradnak
    assert len(others) == 2

    rendered = R.render_section(pairs, others)
    assert "- Anna → Béla: MAGÁZ  (beosztott→főnök)" in rendered
    assert "- Anna ↔ Cili: TEGEZ  (barátnők)" in rendered
    assert "váltás: Anna ↔ Béla TEGEZ a 3. rész után" in rendered


def test_write_local_megorzi_a_tobbit(tmp_path):
    p = tmp_path / "local.md"
    p.write_text(SAMPLE, encoding="utf-8")
    _, pairs, others, _ = R.parse_local(str(p))
    pairs.append({"a": "Dani", "b": "Anna", "mutual": False,
                  "form": "TEGEZ", "note": "testvérek"})
    R.write_local(str(p), pairs, others)
    text = p.read_text(encoding="utf-8")
    assert text.startswith("Title: Teszt sorozat")     # a szakaszon kívüli rész él
    assert "- Dani → Anna: TEGEZ  (testvérek)" in text
    assert (tmp_path / "local.md.bak").exists()        # .bak készült
    # újraolvasva ugyanaz
    _, p2, o2, _ = R.parse_local(str(p))
    assert len(p2) == 3 and o2 == others


def _run_main(monkeypatch, tmp_path, *extra):
    """main() hamis Claude-válasszal és lezárt stdinnel (agent-/pipe-futás)."""
    local = tmp_path / "local.md"
    local.write_text(SAMPLE, encoding="utf-8")
    srt = tmp_path / "S01E01.kor.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n안녕하세요\n", encoding="utf-8")
    rel = [
        {"a": "Dani", "b": "Emma", "mutual": True, "form": "TEGEZ",
         "confidence": "biztos", "relation": "barátok", "evidence": ["#1"]},
        {"a": "Emma", "b": "Feri", "mutual": False, "form": "MAGÁZ",
         "confidence": "bizonytalan", "relation": "vegyes", "evidence": ["#2"]},
        {"a": "Anna", "b": "Béla", "mutual": False, "form": "TEGEZ",
         "confidence": "biztos", "relation": "", "evidence": ["#3"]},
    ]
    monkeypatch.setattr(R, "run_claude", lambda *a, **k: [dict(r) for r in rel])
    monkeypatch.setattr(R, "load_translation_context", lambda: "")
    monkeypatch.setattr("sys.stdin", open(os.devnull))
    monkeypatch.setattr("sys.argv", ["register", str(srt), "--provider", "claude",
                                     "--local-file", str(local), *extra])
    R.main()
    return local.read_text(encoding="utf-8")


def test_dry_run_nem_kerdez_es_jelol(monkeypatch, tmp_path, capsys):
    text = _run_main(monkeypatch, tmp_path, "--dry-run")
    out = capsys.readouterr().out
    assert text == SAMPLE  # a fájl nem módosult
    assert "Traceback" not in out and "[y] elfogad" not in out
    assert "[BIZONYTALAN] Emma → Feri: MAGÁZ" in out
    assert "[ÜTKÖZIK (eddig: MAGÁZ)] Anna → Béla: TEGEZ" in out
    assert "- Emma → Feri: MAGÁZ" in out.split("Javasolt regiszter")[1]


def test_eles_futas_stdin_nelkul_nem_omlik_ossze(monkeypatch, tmp_path, capsys):
    text = _run_main(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert text == SAMPLE
    assert "Nincs interaktív bemenet" in out
    assert "Megszakítva" in out
