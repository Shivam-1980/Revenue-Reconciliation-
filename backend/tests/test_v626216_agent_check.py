"""The connection checker for the other computer says PASS only when every step really works."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_agent_connection", Path(__file__).resolve().parents[2] / "check_agent_connection.py")
chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)


def _run(monkeypatch, capsys, answers):
    def fake(url, key, ctx):
        r = answers(url, key)
        if isinstance(r, Exception): raise r
        return r
    monkeypatch.setattr(chk, "call", fake)
    monkeypatch.setattr("sys.argv", ["x", "--url", "https://h:8000", "--key", "k"])
    code = chk.main()
    return code, capsys.readouterr().out


def test_all_steps_pass(monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, lambda u, k: (200, '{"status":"healthy"}') if u.endswith("/health") else ((200, '{"items":[{}]}') if k else (401, "")))
    assert code == 0 and out.count("PASS") == 3 and "FAIL" not in out


def test_open_data_without_a_key_fails(monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, lambda u, k: (200, '{"status":"healthy","items":[]}'))
    assert code == 1 and "FAIL  2." in out


def test_unreachable_pc_stops_early(monkeypatch, capsys):
    code, out = _run(monkeypatch, capsys, lambda u, k: OSError("timed out"))
    assert code == 1 and "FAIL  1." in out and "2." not in out.split("Nothing else")[0].split("FAIL  1.")[-1]
