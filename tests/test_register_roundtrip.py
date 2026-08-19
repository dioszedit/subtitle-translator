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
