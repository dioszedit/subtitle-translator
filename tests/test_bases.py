"""subtr.tasks.bases — alap-szótárak listázása, sorozatból alapba emelés, ütközés-ellenőrzés."""

import json

import pytest

from subtr.tasks import bases


def _write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """Kis „repo”: .git + glossaries/ + egy sorozat-mappa glossaryval és kész fordítással."""
    (tmp_path / ".git").mkdir()
    gdir = tmp_path / "glossaries"
    gdir.mkdir()
    _write(gdir / "index.json", {"bases": [{"id": "zh-historical", "countries": ["CN"]}]})
    _write(gdir / "zh-historical.json", {"meta": {"id": "zh-historical"},
                                          "honorifics": [{"en": "Marquis", "hu": "márki", "context": "c"}]})
    series = tmp_path / "Sorozat"
    (series / "input").mkdir(parents=True)
    (series / "output").mkdir()
    _write(series / "glossary.json", {"meta": {"bases": ["zh-historical"]},
                                      "honorifics": [{"en": "Duke", "hu": "herceg", "context": "Wang herceg"},
                                                     {"en": "Marquis", "hu": "őrgróf", "context": ""}],
                                      "special_terms": []})
    (series / "input" / "X - S01E01.eng.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nThe Duke arrived.\n", encoding="utf-8")
    (series / "output" / "X - S01E01.hun.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nMegjött a herceg.\n", encoding="utf-8")
    return tmp_path


def test_promote_athelyez_es_context_cserelheto(repo, monkeypatch):
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit) as e:
        bases.main(["promote", "Duke", "--to", "zh-historical", "--from", "Sorozat/glossary.json",
                    "--context", "公; név + herceg", "--yes"])
    assert e.value.code == 0
    base = json.loads((repo / "glossaries" / "zh-historical.json").read_text(encoding="utf-8"))
    assert {"en": "Duke", "hu": "herceg", "context": "公; név + herceg"} in base["honorifics"]
    series = json.loads((repo / "Sorozat" / "glossary.json").read_text(encoding="utf-8"))
    assert [x["en"] for x in series["honorifics"]] == ["Marquis"]
    assert (repo / "glossaries" / "zh-historical.json.bak").exists()


def test_promote_meglevot_nem_ir_felul_replace_nelkul(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit) as e:
        bases.main(["promote", "Marquis", "--to", "zh-historical", "--from", "Sorozat/glossary.json", "--yes"])
    assert e.value.code == 1
    assert "--replace" in capsys.readouterr().out


def test_promote_keep_es_dry_run(repo, monkeypatch):
    monkeypatch.chdir(repo)
    before = (repo / "glossaries" / "zh-historical.json").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        bases.main(["promote", "Duke", "--to", "zh-historical", "--from", "Sorozat/glossary.json", "--dry-run"])
    assert (repo / "glossaries" / "zh-historical.json").read_text(encoding="utf-8") == before
    with pytest.raises(SystemExit):
        bases.main(["promote", "Duke", "--to", "zh-historical", "--from", "Sorozat/glossary.json",
                    "--keep", "--yes"])
    series = json.loads((repo / "Sorozat" / "glossary.json").read_text(encoding="utf-8"))
    assert "Duke" in [x["en"] for x in series["honorifics"]]


def test_promote_nem_verziokovetett_alapba_force_nelkul_nem_ir(tmp_path, monkeypatch, capsys):
    (tmp_path / "glossaries").mkdir()
    _write(tmp_path / "glossaries" / "zh-common.json", {"honorifics": []})
    _write(tmp_path / "glossary.json", {"honorifics": [{"en": "Aunt", "hu": "néni"}]})
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        bases.main(["promote", "Aunt", "--to", "zh-common", "--yes"])
    assert e.value.code == 1
    assert "MÁSOLATA" in capsys.readouterr().out


def test_check_felulirast_es_forditasi_elterest_jelez(repo):
    project = json.loads((repo / "Sorozat" / "glossary.json").read_text(encoding="utf-8"))
    project["honorifics"] = [{"en": "Marquis", "hu": "őrgróf"}]
    _write(repo / "glossaries" / "zh-historical.json",
           {"honorifics": [{"en": "Marquis", "hu": "márki"}, {"en": "Duke", "hu": "fejedelem"}]})
    result = bases.check(project, str(repo / "glossaries"), str(repo / "Sorozat"))
    assert [(e["en"], hu) for _, e, hu in result["overridden"]] == [("Marquis", "őrgróf")]
    assert result["pairs"] == 1
    assert [(e["en"], n) for _, e, _, n, _ in result["mismatches"]] == [("Duke", 1)]
