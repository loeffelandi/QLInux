"""Packaging-Dateien, die im Repo liegen muessen."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_spec_is_in_the_repository():
    spec = ROOT / "packaging" / "ql_editor.spec"
    assert spec.is_file()
    text = spec.read_text(encoding="utf-8")
    assert "entrypoint.py" in text
    assert "ql-editor" in text
    # ql_editor.resources erwartet das Symbol im Bundle unter assets/.
    assert "ql-editor.png" in text and '"assets"' in text
