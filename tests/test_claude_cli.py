"""subtr.providers.claude_cli — a 4 helyen duplikált Claude CLI logika közös
adapterének kontraktusa: extract_json robusztussága és find_claude nem-üres
visszatérése."""

import os
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
