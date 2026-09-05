"""subtr.providers.claude_cli — a 4 helyen duplikált Claude CLI logika közös
adapterének kontraktusa: extract_json robusztussága és find_claude nem-üres
visszatérése."""

import os
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subtr.providers.claude_cli import extract_json, find_claude


def test_extract_json_fenced_object():
    raw = 'Íme az elemzés:\n```json\n{"suggestions": [1, 2, 3]}\n```\nKösz.'
    assert extract_json(raw) == {"suggestions": [1, 2, 3]}


def test_extract_json_bare_array_mid_text():
    raw = 'Előtte szöveg [1, 2, {"a": "b"}] utána is szöveg.'
    assert extract_json(raw) == [1, 2, {"a": "b"}]


def test_extract_json_fenced_array():
    raw = '```json\n[{"term": "x"}]\n```'
    assert extract_json(raw) == [{"term": "x"}]


def test_extract_json_unparseable_returns_none():
    raw = 'Ez itt semmiképp sem JSON, se zárójel, se semmi.'
    assert extract_json(raw) is None


def test_extract_json_empty_string_returns_none():
    assert extract_json("") is None
    assert extract_json(None) is None


def test_find_claude_returns_nonempty_string():
    result = find_claude()
    assert isinstance(result, str)
    assert result != ""


# ── sys-prompt fájl: párhuzamos futás nem törli a másik hash-ét ────────────

from subtr.providers.claude_cli import (cleanup_stale_sys_prompts,
                                        write_sys_prompt_file)


def test_write_sys_prompt_file_keeps_other_hash(tmp_path, monkeypatch):
    """Két futás (más epizód = más szűrt szójegyzék) más hash-t kap; a második
    indulása NEM törölheti az elsőét, mert az még használja chunkonként."""
    monkeypatch.chdir(tmp_path)
    a, new_a = write_sys_prompt_file("A epizód kontextus", ".review_claude_sys_prompt_")
    b, new_b = write_sys_prompt_file("B epizód kontextus", ".review_claude_sys_prompt_")
    assert new_a and new_b and a != b
    assert os.path.isfile(a) and os.path.isfile(b)
    # azonos tartalom → ugyanaz a fájl, nem készül új
    again, new_again = write_sys_prompt_file("A epizód kontextus", ".review_claude_sys_prompt_")
    assert again == a and not new_again


def test_cleanup_stale_sys_prompts_only_old(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old, _ = write_sys_prompt_file("régi", ".review_claude_sys_prompt_")
    fresh, _ = write_sys_prompt_file("friss", ".review_claude_sys_prompt_")
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))
    assert cleanup_stale_sys_prompts(".review_claude_sys_prompt_", max_age_days=1) == 1
    assert not os.path.isfile(old) and os.path.isfile(fresh)
