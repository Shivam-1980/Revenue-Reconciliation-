"""Milestone 5 UI layer: the design stylesheet and UX helpers are wired into the app (presentation only)."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def test_theme_and_ux_modules_are_loaded_by_the_app():
    main = (SRC / "main.jsx").read_text(encoding="utf-8")
    assert 'import "./theme.css";' in main and 'from "./ux.jsx"' in main
    assert main.index('import "./styles.css";') < main.index('import "./theme.css";')      # theme overrides the base styles
    for hook in ("<CommandPalette", "<TextSizeControl", "<SearchTrigger", "<NavToggle"):
        assert hook in main


def test_text_size_choice_is_safe_without_storage_and_mobile_drawer_overrides_hidden_sidebar():
    ux = (SRC / "ux.jsx").read_text(encoding="utf-8")
    assert "try {" in ux and "DEFAULT_SCALE" in ux
    css = (SRC / "theme.css").read_text(encoding="utf-8")
    assert ".enterprise-sidebar{display:flex;transform:translateX(-102%)" in css      # styles.css hides it at <=900px
    assert "prefers-reduced-motion" in css and "@media print" in css


def test_upload_page_has_guided_steps_and_friendly_cards():
    main = (SRC / "main.jsx").read_text(encoding="utf-8")
    ux = (SRC / "ux.jsx").read_text(encoding="utf-8")
    assert "<UploadSteps" in main and "export function UploadSteps" in ux
    assert "onDrop" in main and "Only CSV or XLSX files can be uploaded." in main       # drag-and-drop and inline (not alert) errors
    assert "alert(" not in main[main.index("function UploadCard("):main.index("function AuditView(")]
    assert 'sourceStatus?.sources' in main                                              # step state comes from the server, not guessed
