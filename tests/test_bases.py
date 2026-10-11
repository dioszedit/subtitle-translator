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
    assert result["compared"] == ["X - S01E01.hun.srt"] and result["skipped"] == []
    assert [(e["en"], n) for _, e, _, n, _ in result["mismatches"]] == [("Duke", 1)]


def test_promote_nem_veszi_ki_ha_a_sorozat_nem_hasznalja_az_alapot(repo, monkeypatch, capsys):
    _write(repo / "glossaries" / "zh-common.json", {"honorifics": []})
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit) as e:
        bases.main(["promote", "Duke", "--to", "zh-common", "--from", "Sorozat/glossary.json", "--yes"])
    assert e.value.code == 0
    assert "MARAD" in capsys.readouterr().out
    series = json.loads((repo / "Sorozat" / "glossary.json").read_text(encoding="utf-8"))
    assert "Duke" in [x["en"] for x in series["honorifics"]]


def test_promote_a_sorozat_alap_masolatat_is_frissiti(repo, monkeypatch):
    copy_dir = repo / "Sorozat" / "glossaries"
    copy_dir.mkdir()
    _write(copy_dir / "zh-historical.json", {"honorifics": [{"en": "Marquis", "hu": "márki"}]})
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit):
        bases.main(["promote", "Duke", "--to", "zh-historical", "--from", "Sorozat/glossary.json", "--yes"])
    copy = json.loads((copy_dir / "zh-historical.json").read_text(encoding="utf-8"))
    assert "Duke" in [x["en"] for x in copy["honorifics"]]


def test_check_az_erosebb_alapot_veszi_figyelembe(tmp_path):
    gdir = tmp_path / "glossaries"
    gdir.mkdir()
    _write(gdir / "zh-common.json", {"honorifics": [{"en": "Chief", "hu": "főnök"}]})
    _write(gdir / "zh-wuxia.json", {"honorifics": [{"en": "Chief", "hu": "vezér"}]})
    project = {"meta": {"bases": ["zh-common", "zh-wuxia"]}, "honorifics": [{"en": "Chief", "hu": "főnök"}]}
    result = bases.check(project, str(gdir), str(tmp_path))
    assert result["same"] == []
    assert [(b, e["hu"], hu) for b, e, hu in result["overridden"]] == [("zh-wuxia", "vezér", "főnök")]


def test_check_eltero_cueszamu_reszt_kihagyottkent_jelzi(repo):
    (repo / "Sorozat" / "output" / "X - S01E01.hun.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nA\n\n2\n00:00:02,000 --> 00:00:03,000\nB\n", encoding="utf-8")
    project = json.loads((repo / "Sorozat" / "glossary.json").read_text(encoding="utf-8"))
    result = bases.check(project, str(repo / "glossaries"), str(repo / "Sorozat"))
    assert result["compared"] == [] and result["skipped"] == ["X - S01E01.hun.srt"]


def test_list_hibas_alapfajlt_jelez(repo, monkeypatch, capsys):
    (repo / "glossaries" / "zh-historical.json").write_text("{hibás", encoding="utf-8")
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit):
        bases.main(["list"])
    assert "HIBÁS FÁJL" in capsys.readouterr().out
