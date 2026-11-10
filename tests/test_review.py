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


# ────────────────────────────────────────────────────────────────────────────
# Folytatás megszakadás után: részeredmény (.partial), korai leállás, hiányos riport
# ────────────────────────────────────────────────────────────────────────────

import json

import pytest

from subtr import reports
from subtr.tasks import apply_review, review


def _finding(n):
    return {"sorszam": n, "eredeti": f"rossz {n}", "hiba": "hiba", "javaslat": f"jó {n}"}


def test_run_chunks_ment_es_sorrendben_fut():
    chunks = [["a"], ["b"], ["c"]]
    saved = []
    results, errors, interrupted = review.run_chunks(
        chunks, [1, 3], 3, lambda text, i, total: ([_finding(i)], None),
        on_done=lambda i, f: saved.append(i))
    assert sorted(results) == [1, 3] and not errors and not interrupted
    assert saved == [1, 3]


def test_run_chunks_kvotanal_azonnal_leall():
    calls = []

    def executor(text, i, total):
        calls.append(i)
        if i == 2:
            return None, review.ChunkError("[API hiba: 429 RESOURCE_EXHAUSTED]", quota=True)
        return [], None

    results, errors, _ = review.run_chunks([["x"]] * 5, [1, 2, 3, 4, 5], 5, executor)
    assert calls == [1, 2]                       # a 3–5. chunkot már nem próbálja
    assert sorted(results) == [1] and sorted(errors) == [2, 3, 4, 5]
    assert "KIHAGYVA" in errors[5] and "kerete kimerült" in errors[5]


def test_run_chunks_ket_egymast_koveto_hiba_utan_leall():
    calls = []

    def executor(text, i, total):
        calls.append(i)
        return (None, "[TIMEOUT]") if i in (2, 3) else ([], None)

    results, errors, _ = review.run_chunks([["x"]] * 5, [1, 2, 3, 4, 5], 5, executor)
    assert calls == [1, 2, 3]
    assert sorted(errors) == [2, 3, 4, 5] and "KIHAGYVA" in errors[4]


def test_run_chunks_egyetlen_hiba_nem_allit_meg():
    def executor(text, i, total):
        return (None, "[Nem JSON válasz]") if i == 2 else ([], None)

    results, errors, _ = review.run_chunks([["x"]] * 4, [1, 2, 3, 4], 4, executor)
    assert sorted(results) == [1, 3, 4] and sorted(errors) == [2]


def test_run_chunks_megszakitas():
    def executor(text, i, total):
        if i == 2:
            raise KeyboardInterrupt
        return [], None

    results, errors, interrupted = review.run_chunks([["x"]] * 3, [1, 2, 3], 3, executor)
    assert interrupted and sorted(results) == [1] and not errors


def test_quota_signal():
    from subtr.providers import quota_signal
    for text in ("You've hit your usage limit", "You've hit your limit · resets 3pm",
                 "Claude AI usage limit reached|1760000000", "5-hour limit reached",
                 "Weekly limit reached", "rate_limit_error", "rate_limit_exceeded",
                 "You exceeded your current quota",
                 "You have exhausted your capacity on this model, quota will reset"):
        assert quota_signal(text), text
    # átmeneti kapacitáshiány nem a felhasználó kerete
    for text in ("429 RESOURCE_EXHAUSTED: No capacity available for model x",
                 "503 No capacity available", "Overloaded, try again later",
                 "rate limit reached, try again in a minute"):
        assert not quota_signal(text), text
    # magában álló szó vagy szám nem elég
    for text in ('{"sorszam": 429, "eredeti": "x"}', "tokens used | 12,429",
                 "error in cue 429", "We filled our quota. What is the rate limit?",
                 "[TIMEOUT a chunkban 3 (10 perc)]", "", None):
        assert not quota_signal(text), text


def test_gemini_csak_a_napi_limit_allitja_meg(monkeypatch):
    """A percenkénti 429, ami túlélte az adapter újrapróbálkozásait, egyetlen
    hibás chunk — a napi (PerDay) limit viszont a keret kimerülése."""
    minute = ("[API hiba: 429 RESOURCE_EXHAUSTED. {'quotaId': "
              "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]")
    day = ("[API hiba: 429 RESOURCE_EXHAUSTED. {'quotaId': "
           "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]")
    replies = iter([(None, minute), (None, day)])
    monkeypatch.setattr(review.gemini_provider, "call_json", lambda *a, **k: next(replies))
    executor = review._make_gemini_executor(None, "m", "utasítás")
    assert not executor("x", 1, 2)[1].quota
    assert executor("x", 2, 2)[1].quota


def test_cli_executor_a_kvota_jelzot_az_adaptertol_veszi():
    """A tasks réteg nem keresgél a hibaszövegben: a „quota” szó a kimenet
    végében (modellválasz) semmit nem jelent, az adapter jelzője viszont igen —
    és kimerült keretnél nincs újrapróbálás."""
    adapter = _FakeAdapter()
    calls = []

    def run_json(prompt, schema, *, timeout, model, cli_bin):
        calls.append(1)
        raise adapter.RunError('Codex hiba (exit 1): ... "eredeti": "usage limit '
                               'reached, quota exceeded", cue 429', quota=flag[0])

    adapter.run_json = run_json
    executor = review._make_cli_executor(adapter, "fake", None, "utasítás", 10, 3)
    flag = [False]
    err = executor("x", 1, 1)[1]
    assert isinstance(err, review.ChunkError) and not err.quota and len(calls) == 3
    flag[0] = True
    calls.clear()
    assert executor("x", 1, 1)[1].quota and len(calls) == 1


def test_adapterek_csak_a_provider_uzenetebol_jeleznek_kvotat():
    from subtr.providers import antigravity_cli, grok_cli
    from tests.test_antigravity_cli import _stream
    with pytest.raises(antigravity_cli.AntigravityRunError) as e:
        antigravity_cli.parse_agy_response(_stream(
            {"status": "ERROR", "error": "You have exhausted your capacity, quota will reset"}), {})
    assert e.value.quota
    with pytest.raises(antigravity_cli.AntigravityRunError) as e:
        antigravity_cli.parse_agy_response(_stream(
            {"status": "ERROR", "error": "429 RESOURCE_EXHAUSTED: No capacity available"}), {})
    assert not e.value.quota
    assert grok_cli.GrokRunError("x").quota is False


def test_run_chunks_ujraprobalt_chunkok_eltero_hibaja_nem_allit_meg():
    """A 4. és 5. chunk mindig hibázik (más-más okból), a 9. javítható."""
    calls = []
    fails = {4: "[TIMEOUT]", 5: "[Nem JSON válasz]"}

    def executor(text, i, total):
        calls.append(i)
        return (None, review.ChunkError(fails[i])) if i in fails else ([], None)

    results, errors, _ = review.run_chunks([["x"]] * 9, [4, 5, 9], 9, executor,
                                           retry={4, 5, 9})
    assert calls == [4, 5, 9] and sorted(results) == [9] and sorted(errors) == [4, 5]


def test_run_chunks_ujraprobalt_chunkok_azonos_hibaja_megallit():
    """Fel nem ismert limit-üzenet: minden újrapróbált chunk ugyanúgy bukik —
    ne próbáljuk végig mindet teljes timeouttal."""
    calls = []

    def executor(text, i, total):
        calls.append(i)
        return None, review.ChunkError("Ismeretlen limit-üzenet\nrészletek " + str(i))

    results, errors, _ = review.run_chunks([["x"]] * 5, [1, 2, 3, 4, 5], 5, executor,
                                           retry={1, 2, 3, 4, 5})
    assert calls == [1, 2] and errors[5].startswith(review.SKIPPED_PREFIX)


def test_claude_executor_limit_uzenet_sikeres_kilepessel(monkeypatch):
    class Proc:
        returncode, stderr = 0, ""
        stdout = "You've hit your limit · resets 3pm"

    monkeypatch.setattr(review.subprocess, "run", lambda *a, **k: Proc())
    err = review._make_claude_executor("claude", "sys.txt", "opus")("x", 1, 1)[1]
    assert err.quota and "hit your limit" in err


def test_run_chunks_kvota_az_ujraprobalasi_sorban_is_megallit():
    def executor(text, i, total):
        return None, review.ChunkError("usage limit reached", quota=True)

    results, errors, _ = review.run_chunks([["x"]] * 3, [1, 2, 3], 3, executor,
                                           retry={1, 2, 3})
    assert not results and errors[3].startswith(review.SKIPPED_PREFIX)


def test_run_chunks_sima_szoveges_hiba_nem_kvota():
    """A kvóta-jelzőt csak az executor adhatja: a modell nyers válaszában lévő
    „kvóta” / „quota” szó vagy a 429-es sorszám nem állíthatja meg a futást."""
    def executor(text, i, total):
        if i == 2:
            return None, ("[Nem JSON válasz — nyers kimenet megőrizve:]\n"
                          '#429: "elfogyott a kvóta, rate limit, quota exceeded"')
        return [], None

    results, errors, _ = review.run_chunks([["x"]] * 4, [1, 2, 3, 4], 4, executor)
    assert sorted(results) == [1, 3, 4] and sorted(errors) == [2]


def test_claude_executor_kvota_csak_a_cli_uzenetebol(monkeypatch):
    class Proc:
        def __init__(self, rc, out, err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    replies = iter([Proc(1, "Claude AI usage limit reached|1760000000"),
                    Proc(0, "nem JSON, de szerepel benne: quota, rate limit, 429")])
    monkeypatch.setattr(review.subprocess, "run", lambda *a, **k: next(replies))
    executor = review._make_claude_executor("claude", "sys.txt", "opus")
    _, err = executor("x", 1, 2)
    assert err.quota                          # a CLI saját üzenete
    _, err = executor("x", 2, 2)
    assert err and not getattr(err, "quota", False)   # a modell válasza


def test_run_chunks_megszakitas_a_mentes_kozben():
    """Ctrl+C nem csak a provider hívása alatt jöhet."""
    def on_done(i, findings):
        if i == 2:
            raise KeyboardInterrupt

    results, errors, interrupted = review.run_chunks(
        [["x"]] * 3, [1, 2, 3], 3, lambda t, i, n: ([], None), on_done=on_done)
    assert interrupted and sorted(results) == [1] and not errors


def test_partial_kor(tmp_path):
    p = tmp_path / "x.hun_REVIEW_CODEX.partial"
    fp = {"model": "m"}
    hashes = {1: "h1", 2: "h2", 3: "h3"}
    assert reports.load_partial(p, fp, hashes) == reports.PartialState()
    reports.start_partial(p, fp)
    reports.append_partial(p, 2, "h2", [_finding(7)])
    reports.append_partial(p, 1, "h1", [])
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"chunk": 3, "hash": "h3", "findings": [{"sorsz')       # félbeírt sor
    st = reports.load_partial(p, fp, hashes)
    assert st.changed is None and sorted(st.done) == [1, 2] and st.done[2][0]["sorszam"] == 7
    assert st.failed == {} and st.outdated == []
    # más beállítás: az egész más futáshoz tartozik
    assert reports.load_partial(p, {"model": "MÁS"}, hashes) == reports.PartialState(
        changed=["model"])
    # egy chunk szövege megváltozott: csak az évül el
    st = reports.load_partial(p, fp, {**hashes, 2: "ÚJ"})
    assert sorted(st.done) == [1] and st.outdated == [2] and st.changed is None
    stale = reports.set_aside_partial(p)
    assert stale.name == "x.hun_REVIEW_CODEX.partial.stale" and not p.exists()
    assert stale == reports.stale_path(p)
    assert reports.set_aside_partial(p) is None


def test_partial_felbeirt_sor_utan_is_ervenyes_marad(tmp_path):
    """A csonka sor után írt chunk nem ragadhat hozzá (különben mindkettő elveszne)."""
    p = tmp_path / "x.partial"
    fp, hashes = {"model": "m"}, {i: f"h{i}" for i in range(1, 5)}
    reports.start_partial(p, fp)
    reports.append_partial(p, 1, "h1", [])
    with open(p, "a", encoding="utf-8") as fh:
        fh.write('{"chunk": 2, "hash": "h2", "findings": [{"sorsz')   # nincs sorvég
    reports.append_partial(p, 3, "h3", [_finding(5)])
    raw = "[Nem JSON válasz]\nnyers szöveg, ami kell"
    reports.append_partial_error(p, 4, "h4", raw)
    st = reports.load_partial(p, fp, hashes)
    assert st.changed is None and sorted(st.done) == [1, 3]
    assert st.failed == {4: [raw]} and st.attempts == {4: 1}       # a TELJES üzenet
    reports.append_partial_error(p, 4, "h4", "usage limit reached")
    reports.append_partial_error(p, 4, "h4", "usage limit reached")
    st = reports.load_partial(p, fp, hashes)
    assert st.failed[4] == [raw, "usage limit reached"] and st.attempts[4] == 3
    reports.append_partial(p, 4, "h4", [])                           # később sikerült
    st = reports.load_partial(p, fp, hashes)
    assert st.failed == {} and st.attempts == {}


def test_partial_tobb_bajtos_karakter_kozepen_szakadt_iras(tmp_path):
    """Egy „ő” közepén megszakadt írás nem dobhat UnicodeDecodeError-t."""
    p = tmp_path / "x.partial"
    fp, hashes = {"model": "m"}, {1: "h1", 2: "h2"}
    reports.start_partial(p, fp)
    reports.append_partial(p, 1, "h1", [])
    torn = '{"chunk": 2, "hash": "h2", "findings": [{"eredeti": "ő'.encode("utf-8")[:-1]
    with open(p, "ab") as fh:
        fh.write(torn)
    st = reports.load_partial(p, fp, hashes)
    assert sorted(st.done) == [1] and st.changed is None
    reports.append_partial(p, 2, "h2", [])
    assert sorted(reports.load_partial(p, fp, hashes).done) == [1, 2]


def test_partial_neve_nem_riport(tmp_path):
    srt = tmp_path / "x.hun.srt"
    srt.write_text("", encoding="utf-8")
    _, js = reports.report_paths(srt, "antigravity", "_part2")
    p = reports.partial_path(js)
    assert p.name == "x.hun_REVIEW_ANTIGRAVITY_part2.partial"
    p.write_text("{}", encoding="utf-8")
    assert apply_review.find_reports(srt) == []       # az apply nem veszi fel


def test_hianyos_riport_json(tmp_path):
    srt = tmp_path / "x.hun.srt"
    txt, js = reports.report_paths(srt, "gemini")
    reports.write_reports(srt, txt, js, reviewer="gemini", model_label="m",
                          finding_blocks=[], json_findings=[],
                          errors={3: "kihagyva", 2: "hiba"}, total_chunks=3)
    data = json.loads(js.read_text(encoding="utf-8"))       # találat nélkül is elkészül
    assert data["missing_chunks"] == [2, 3] and data["total_chunks"] == 3
    assert data["findings"] == []
    # teljes riportban nincs ilyen mező
    reports.write_reports(srt, txt, js, reviewer="gemini", model_label="m",
                          finding_blocks=["b"], json_findings=[_finding(1)])
    assert "missing_chunks" not in json.loads(js.read_text(encoding="utf-8"))
    assert reports.chunk_ranges([1, 2, 3, 6, 8, 9]) == "1–3, 6, 8–9"
    assert reports.chunk_ranges("elrontott") == "?"
    assert reports.chunk_ranges({4: ["x"], 2: ["y"], 3: ["z"]}) == "2–4"     # dict kulcsai
    assert reports.chunk_ranges(None) == "?"


def test_apply_figyelmeztet_a_hianyos_riportra(tmp_path, capsys):
    js = tmp_path / "x.hun_REVIEW_GEMINI.json"
    js.write_text(json.dumps({"reviewer": "gemini", "total_chunks": 45,
                              "missing_chunks": list(range(3, 46)),
                              "findings": [_finding(1)]}), encoding="utf-8")
    assert len(apply_review.load_json_report(js)) == 1
    out = capsys.readouterr().out
    assert "hiányos riport" in out and "3–45 / 45" in out
    js.write_text(json.dumps({"missing_chunks": "kézzel elrontva", "findings": []}),
                  encoding="utf-8")
    apply_review.load_json_report(js)               # nem száll el


# --- végigfuttatás hamis CLI-providerrel ---------------------------------------

class _FakeAdapter:
    LABEL = "Fake"
    MISSING_HINT = "nincs"

    from subtr.providers import CliRunError as RunError

    def __init__(self):
        self.calls = []
        self.fail = set()          # ezek a chunkok hibáznak
        self.interrupt_at = None

    def find_cli(self):
        return "fake"

    def run_json(self, prompt, schema, *, timeout, model, cli_bin):
        i = int(prompt.split("=== REVIEW BLOKK (")[1].split("/")[0])
        self.calls.append(i)
        if i == self.interrupt_at:
            raise KeyboardInterrupt
        if i in self.fail:
            raise self.RunError("usage limit reached", quota=True)
        return {"errors": [_finding(i * 10)]}


@pytest.fixture
def episode(tmp_path, monkeypatch):
    for key in [k for k in __import__("os").environ if k.startswith("SUBTR_")]:
        monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    srt = tmp_path / "x.hun.srt"
    srt.write_text("\n\n".join(
        f"{n}\n00:00:{n:02d},000 --> 00:00:{n:02d},900\nsor {n}" for n in range(1, 7)) + "\n",
        encoding="utf-8")
    adapter = _FakeAdapter()
    monkeypatch.setattr(review, "get_provider", lambda name: adapter)
    args = [str(srt), "--provider", "codex", "--chunk-size", "2", "--no-source",
            "--max-retries", "1"]
    js = tmp_path / "x.hun_REVIEW_CODEX.json"
    return srt, adapter, args, js, js.with_suffix(".partial")


def _run(args):
    try:
        review.main(args)
    except SystemExit as e:
        return e.code
    return 0


def test_review_sikeres_futas_utan_nincs_partial(episode):
    srt, adapter, args, js, partial = episode
    assert _run(args) == 0
    assert adapter.calls == [1, 2, 3] and not partial.exists()
    data = json.loads(js.read_text(encoding="utf-8"))
    assert [f["chunk"] for f in data["findings"]] == [1, 2, 3]
    assert "missing_chunks" not in data


def test_review_megszakitas_utan_folytat(episode, capsys):
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 2
    assert _run(args) == 130
    assert partial.exists() and not js.exists()       # félkész riport nem készül
    assert "MEGSZAKÍTVA" in capsys.readouterr().out
    adapter.interrupt_at, adapter.calls = None, []
    assert _run(args) == 0
    assert adapter.calls == [2, 3]                    # az 1. chunk nem megy újra
    data = json.loads(js.read_text(encoding="utf-8"))
    assert [f["sorszam"] for f in data["findings"]] == [10, 20, 30]   # chunk-sorrend
    assert not partial.exists()


def test_review_from_partial_megszakitas_utan(episode):
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 2
    assert _run(args) == 130
    adapter.calls = []
    assert _run(args + ["--from-partial"]) == 1       # hiányos → nem-nulla
    assert adapter.calls == []                        # a provider nem fut
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["missing_chunks"] == [2, 3] and len(data["findings"]) == 1
    assert partial.exists()                           # később még folytatható


def test_review_kvotanal_hianyos_riport_majd_potlas(episode):
    srt, adapter, args, js, partial = episode
    adapter.fail = {2, 3}
    assert _run(args) == 1
    assert adapter.calls == [1, 2]                    # kvóta: a 3. már nem megy
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["missing_chunks"] == [2, 3] and data["total_chunks"] == 3
    assert partial.exists()
    adapter.fail, adapter.calls = set(), []
    assert _run(args) == 0                            # csak a hiányzók;
    assert adapter.calls == [3, 2]                    # a korábban hibás a végén
    data = json.loads(js.read_text(encoding="utf-8"))
    assert "missing_chunks" not in data and len(data["findings"]) == 3
    assert not partial.exists()


def test_review_ket_makacs_chunk_nem_zarja_el_a_tobbit(tmp_path, monkeypatch, episode, capsys):
    """A 2. és 3. chunk mindig hibázik (nem kvóta): az első futás megáll utánuk,
    a második előbb a még meg sem próbáltakat futtatja, a makacsokat a végén."""
    srt, adapter, args, js, partial = episode
    srt.write_text("\n\n".join(
        f"{n}\n00:00:{n:02d},000 --> 00:00:{n:02d},900\nsor {n}" for n in range(1, 11)) + "\n",
        encoding="utf-8")                          # 5 chunk

    def run_json(prompt, schema, *, timeout, model, cli_bin):
        i = int(prompt.split("=== REVIEW BLOKK (")[1].split("/")[0])
        adapter.calls.append(i)
        if i in (2, 3):
            raise adapter.RunError("Timeout (15 perc)")
        return {"errors": []}

    monkeypatch.setattr(adapter, "run_json", run_json)
    assert _run(args) == 1
    assert adapter.calls == [1, 2, 3]              # két egymást követő hiba: megáll
    adapter.calls.clear()
    assert _run(args) == 1
    assert adapter.calls == [4, 5, 2, 3]           # a 4–5. chunk most lefut
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["missing_chunks"] == [2, 3]


def test_review_resz_tartomany_folytathato_suffix_nelkul(episode, capsys):
    srt, adapter, args, js, partial = episode
    adapter.fail = {3}
    ranged = args + ["--start-chunk", "2"]
    assert _run(ranged) == 1                       # hiányos riport + .partial
    assert js.exists() and partial.exists()
    adapter.fail, adapter.calls = set(), []
    assert _run(ranged) == 0                       # a védelem nem állja útját
    assert adapter.calls == [3]
    # érvényes részeredmény nélkül a védelem továbbra is él
    capsys.readouterr()
    assert _run(ranged) == 1
    assert "rész-tartomány" in capsys.readouterr().out


def test_review_from_partial_tanacsa(episode, capsys):
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 2
    assert _run(args) == 130
    capsys.readouterr()
    assert _run(args + ["--from-partial"]) == 1
    out = capsys.readouterr().out
    assert "--from-partial NÉLKÜL" in out and "ugyanez a parancs" not in out


def test_review_megvaltozott_chunk_ujra_fut_a_tobbi_marad(episode, capsys):
    """Átvezetett javítás után csak az érintett chunk megy újra, plusz a hiányzók."""
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 3
    assert _run(args) == 130                          # 1. és 2. chunk kész
    srt.write_text(srt.read_text(encoding="utf-8").replace("sor 1", "javított sor 1"),
                   encoding="utf-8")
    adapter.interrupt_at, adapter.calls = None, []
    capsys.readouterr()
    assert _run(args) == 0
    assert adapter.calls == [1, 3]                    # a 2. chunk eredménye megmaradt
    assert "Megváltozott szövegű chunk" in capsys.readouterr().out
    assert len(json.loads(js.read_text(encoding="utf-8"))["findings"]) == 3


def test_review_mas_beallitas_felreteszi_a_reszeredmenyt(episode, capsys):
    """Ctrl+C után a .partial az egyetlen példány: más modellel futtatva nem
    törlődik, hanem .partial.stale néven megmarad."""
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 3
    assert _run(args) == 130
    saved = partial.read_text(encoding="utf-8")
    adapter.interrupt_at, adapter.calls = None, []
    capsys.readouterr()
    assert _run(args + ["--from-partial", "--model", "mas"]) == 1     # nem ehhez tartozik
    assert partial.exists()
    adapter.fail = {2}
    assert _run(args + ["--model", "mas"]) == 1       # elölről, de megint hiányos
    assert adapter.calls == [1, 2]
    out = capsys.readouterr().out
    assert "a modell" in out and ".partial.stale" in out
    stale = reports.stale_path(partial)
    assert stale.read_text(encoding="utf-8") == saved
    adapter.fail = set()
    assert _run(args + ["--model", "mas"]) == 0
    assert not stale.exists() and not partial.exists()    # sikeres futás után egyik sem marad


def test_review_no_resume_elutasitott_futas_nem_dob_el_semmit(episode, capsys):
    srt, adapter, args, js, partial = episode
    adapter.fail = {3}
    ranged = args + ["--start-chunk", "2"]
    assert _run(ranged) == 1                          # hiányos riport + .partial
    saved = partial.read_text(encoding="utf-8")
    capsys.readouterr()
    assert _run(ranged + ["--no-resume"]) == 1        # a védelem elutasítja…
    assert "rész-tartomány" in capsys.readouterr().out
    assert partial.read_text(encoding="utf-8") == saved   # …és a részeredmény megvan
    adapter.fail, adapter.calls = set(), []
    assert _run(ranged) == 0 and adapter.calls == [3]


def test_review_irhatatlan_reszeredmeny_nem_allitja_meg(episode, monkeypatch, capsys):
    srt, adapter, args, js, partial = episode

    def boom(*a, **k):
        raise PermissionError("zárolt fájl")

    monkeypatch.setattr(reports, "append_partial", boom)
    assert _run(args) == 0
    assert adapter.calls == [1, 2, 3]
    assert len(json.loads(js.read_text(encoding="utf-8"))["findings"]) == 3
    assert capsys.readouterr().out.count("a részeredmény nem írható") == 1


def test_review_a_megorzott_nyers_valasz_nem_vesz_el(episode, monkeypatch):
    """Egy chunk nem értelmezhető választ adott (a nyers szöveg a riportban);
    a következő futás kvótára fut, mielőtt újrapróbálná — az üzenet megmarad."""
    srt, adapter, args, js, partial = episode
    txt = js.with_suffix(".txt")
    state = {"mode": "first"}

    def run_json(prompt, schema, *, timeout, model, cli_bin):
        i = int(prompt.split("=== REVIEW BLOKK (")[1].split("/")[0])
        if state["mode"] == "first" and i == 1:
            raise adapter.RunError("A válasz nem érvényes JSON: NYERS-VÁLASZ-RÉSZLET")
        if state["mode"] == "first" and i == 2:
            return {"errors": []}
        raise adapter.RunError("usage limit reached", quota=True)

    monkeypatch.setattr(adapter, "run_json", run_json)
    assert _run(args) == 1
    assert "NYERS-VÁLASZ-RÉSZLET" in txt.read_text(encoding="utf-8")
    state["mode"] = "quota"
    assert _run(args) == 1                            # 3. chunk: kvóta → az 1. kimarad
    report = txt.read_text(encoding="utf-8")
    assert "NYERS-VÁLASZ-RÉSZLET" in report and "KIHAGYVA" in report
    assert _run(args + ["--from-partial"]) == 1
    assert "NYERS-VÁLASZ-RÉSZLET" in txt.read_text(encoding="utf-8")


def test_review_no_resume(episode):
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 2
    assert _run(args) == 130
    adapter.interrupt_at, adapter.calls = None, []
    assert _run(args + ["--no-resume"]) == 0
    assert adapter.calls == [1, 2, 3]


def test_review_from_partial_reszeredmeny_nelkul(episode, capsys):
    srt, adapter, args, js, partial = episode
    assert _run(args + ["--from-partial"]) == 1
    assert "nincs felhasználható részeredmény" in capsys.readouterr().out


def test_review_kiirja_a_korabban_hibas_chunkokat(episode, capsys):
    srt, adapter, args, js, partial = episode

    def run_json(prompt, schema, *, timeout, model, cli_bin):
        i = int(prompt.split("=== REVIEW BLOKK (")[1].split("/")[0])
        if i == 2:
            raise adapter.RunError("Timeout (15 perc)")
        return {"errors": []}

    adapter.run_json = run_json
    assert _run(args) == 1
    capsys.readouterr()
    assert _run(args) == 1
    assert "újrapróbálva: 2." in capsys.readouterr().out


def test_review_ujraprobalasi_sorrend_a_legkevesebbszer_elbukottal_kezd(episode):
    """Három korábban hibás chunk közül a kétszer elbukott kerül a sor végére."""
    srt, adapter, args, js, partial = episode
    attempts = []
    behaviour = {"fail": {1, 2, 3}}

    def run_json(prompt, schema, *, timeout, model, cli_bin):
        i = int(prompt.split("=== REVIEW BLOKK (")[1].split("/")[0])
        attempts.append(i)
        if i in behaviour["fail"]:
            raise adapter.RunError(f"hiba {i} #{len(attempts)}")     # mindig más szöveg
        return {"errors": []}

    adapter.run_json = run_json
    assert _run(args) == 1                 # 1., 2. hibás → megáll, a 3. kimarad
    assert attempts == [1, 2]
    attempts.clear()
    assert _run(args) == 1                 # előbb a még meg sem próbált 3., aztán 1., 2.
    assert attempts == [3, 1, 2]
    attempts.clear()
    behaviour["fail"] = {1, 2}
    assert _run(args) == 1                 # a 3. (1 bukás) megelőzi az 1., 2.-at (2 bukás)
    assert attempts == [3, 1, 2]
    assert json.loads(js.read_text(encoding="utf-8"))["missing_chunks"] == [1, 2]


def test_review_szojegyzek_szures_nem_dobja_el_a_reszeredmenyt(episode, tmp_path):
    """Egy átvezetett javítás eltünteti egy szójegyzék-terminus egyetlen
    előfordulását: a promptba szűrt szójegyzék megváltozik, de a beállítás nem —
    csak az érintett chunk megy újra."""
    srt, adapter, args, js, partial = episode
    (tmp_path / "glossary.json").write_text(json.dumps(
        {"special_terms": [{"en": "line five", "hu": "sor 5", "context": ""}]}), encoding="utf-8")
    adapter.fail = {2}
    assert _run(args) == 1                 # 1. és 3. kész, a 2. hibás
    srt.write_text(srt.read_text(encoding="utf-8").replace("sor 5", "ötödik"),
                   encoding="utf-8")       # a 3. chunkban volt a terminus
    adapter.fail, adapter.calls = set(), []
    assert _run(args) == 0
    assert adapter.calls == [3, 2]         # az 1. chunk eredménye megmaradt


def test_review_zarolt_reszeredmeny_nem_buktatja_a_kesz_futast(episode, monkeypatch, capsys):
    srt, adapter, args, js, partial = episode

    def locked(path):
        raise PermissionError("zárolt")

    monkeypatch.setattr(reports, "discard_partial", locked)
    assert _run(args) == 0
    assert js.exists() and "nem kezelhető" in capsys.readouterr().out


def test_review_olvashatatlan_reszeredmeny(episode, monkeypatch, capsys):
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 2
    assert _run(args) == 130

    def locked(*a, **k):
        raise PermissionError("zárolt")

    monkeypatch.setattr(reports, "load_partial", locked)
    adapter.interrupt_at, adapter.calls = None, []
    assert _run(args) == 0                 # nélküle fut végig, nem száll el
    assert adapter.calls == [1, 2, 3] and "nem olvasható" in capsys.readouterr().out


def test_review_from_partial_megvaltozott_chunk_uzenete(episode, capsys):
    srt, adapter, args, js, partial = episode
    adapter.interrupt_at = 3
    assert _run(args) == 130
    srt.write_text(srt.read_text(encoding="utf-8").replace("sor 1", "javított sor 1"),
                   encoding="utf-8")
    capsys.readouterr()
    assert _run(args + ["--from-partial"]) == 1
    out = capsys.readouterr().out
    assert "nem használható: 1." in out and "újra lektorálva" not in out
    assert json.loads(js.read_text(encoding="utf-8"))["missing_chunks"] == [1, 3]


def test_review_resz_tartomany_riport_jelzi_a_lefedettseget(episode, capsys):
    srt, adapter, args, js, partial = episode
    part = js.with_name("x.hun_REVIEW_CODEX_part2.json")
    assert _run(args + ["--start-chunk", "2", "--suffix", "_part2"]) == 0
    data = json.loads(part.read_text(encoding="utf-8"))
    assert data["chunk_range"] == [2, 3] and data["total_chunks"] == 3
    assert "missing_chunks" not in data
    apply_review.load_json_report(part)
    assert "rész-tartomány riport" in capsys.readouterr().out
    assert _run(args) == 0                 # a teljes riportban nincs ilyen mező
    assert "chunk_range" not in json.loads(js.read_text(encoding="utf-8"))
