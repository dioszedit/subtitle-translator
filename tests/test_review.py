"""subtr.tasks.review — a provider-független részek: a Claude-válasz
findings-parse-a, a forrás-párosítás és az igazítás-ellenőrzés."""

from subtr.tasks import review


def test_parse_json_findings_array():
    raw = '[{"sorszam": "3", "eredeti": "a", "hiba": "b", "javaslat": "c"}]'
    assert review.parse_json_findings(raw) == [
        {"sorszam": 3, "eredeti": "a", "hiba": "b", "javaslat": "c"}]


def test_parse_json_findings_fenced_and_prose():
    raw = 'Íme:\n```json\n[{"sorszam": 1, "javaslat": "x"}]\n```\nKész.'
    assert [f["sorszam"] for f in review.parse_json_findings(raw)] == [1]


def test_parse_json_findings_object_with_errors_key():
    """A strukturált ág objektumát is elfogadja — ne vesszen el a chunk."""
    raw = '{"errors": [{"sorszam": 4, "javaslat": "x"}]}'
    assert [f["sorszam"] for f in review.parse_json_findings(raw)] == [4]


def test_parse_json_findings_empty_and_garbage():
    assert review.parse_json_findings("[]") == []
    assert review.parse_json_findings("") == []
    assert review.parse_json_findings("nem json") is None
    assert review.parse_json_findings('{"x": 1}') is None


def test_parse_json_findings_skips_items_without_javaslat_or_bad_sorszam():
    raw = '[{"sorszam": 1}, {"sorszam": "abc", "javaslat": "x"}, {"sorszam": 2, "javaslat": "y"}]'
    assert [f["sorszam"] for f in review.parse_json_findings(raw)] == [2]
