from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_backend_is_started_and_health_checked_before_frontend_install_or_build():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    backend_start = source.index('start "EKO Backend"')
    backend_ready = source.index(":BACKEND_READY")
    frontend_install = source.index("npm.cmd install")
    frontend_build = source.index("npm.cmd run build")
    assert backend_start < backend_ready < frontend_install < frontend_build
    assert "Backend is healthy." in source
    assert "Backend is still running and healthy." in source

def test_launcher_waits_for_health_and_distinguishes_backend_frontend_failures():
    source = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "%API%/health" in source
    assert ":BACKEND_FAILED" in source
    assert ":BACKEND_DROPPED" in source
    assert ":FRONTEND_FAILED" in source
