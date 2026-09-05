"""subtr.cli — parancs-diszpécser: --help, ismeretlen parancs, továbbadás."""

import sys
import types

import pytest

from subtr import cli


def test_no_args_and_help_print_usage(capsys):
    cli.main([])
    out = capsys.readouterr().out
    assert "Használat" in out and "translate" in out and "apply-auto" in out
    cli.main(["--help"])
    assert "Parancsok" in capsys.readouterr().out


def test_unknown_command_exits_2(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["fordits"])
    assert exc.value.code == 2
    assert "ismeretlen parancs" in capsys.readouterr().out


def test_dispatch_sets_prog_name_and_calls_module_main(monkeypatch):
    seen = {}
    fake = types.SimpleNamespace(main=lambda: seen.update(argv=list(sys.argv)))
    monkeypatch.setattr(cli.importlib, "import_module",
                        lambda name: seen.update(module=name) or fake)
    monkeypatch.setattr(sys, "argv", ["subtr.py", "verify", "a.srt", "b.srt"])
    cli.main(["verify", "a.srt", "b.srt"])
    assert seen["module"] == "subtr.tasks.verify"
    assert seen["argv"] == ["subtr verify", "a.srt", "b.srt"]


def test_every_command_module_imports_and_has_main():
    import importlib
    for name, (module, _desc) in cli.COMMANDS.items():
        mod = importlib.import_module(module)
        assert callable(mod.main), name
