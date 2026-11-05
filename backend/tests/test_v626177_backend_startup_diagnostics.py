from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_backend_launcher_writes_runtime_log_and_shows_exit_code():
    source = (ROOT / "run_backend.bat").read_text(encoding="utf-8")
    assert "backend_runtime.log" in source
    assert "--host 127.0.0.1 --port 8000" in source
    assert "Backend process exited with code" in source

def test_startup_checks_http_status_and_port_conflicts():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "curl.exe -k -fsS --max-time 1 %API%/health" in source
    assert "Port 8000 is already occupied" in source
    assert "diagnostics_backend.bat" in source

def test_diagnostics_script_collects_health_version_ports_and_runtime_log():
    source = (ROOT / "diagnostics_backend.bat").read_text(encoding="utf-8")
    for expected in ("netstat -ano", "/health", "/api/version", "backend_runtime.log", "backend_diagnostics.log"):
        assert expected in source
