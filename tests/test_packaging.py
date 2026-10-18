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


def test_mime_types_are_declared_and_installed_by_the_appimage_build():
    mime = (ROOT / "packaging" / "ql-editor-mime.xml").read_text(encoding="utf-8")
    assert 'type="application/x-qlinux-label"' in mime
    assert 'type="application/x-brother-lbx"' in mime
    assert "*.qlx" in mime and "*.lbx" in mime
    build = (ROOT / "packaging" / "build_appimage.sh").read_text(encoding="utf-8")
    assert "ql-editor-mime.xml" in build
    assert "assets/mimetypes" in build


def test_desktop_file_opens_files_and_claims_both_types():
    desktop = (ROOT / "packaging" / "ql-editor.desktop").read_text(encoding="utf-8")
    assert "Exec=ql-editor %F" in desktop
    mime_line = next(
        line for line in desktop.splitlines() if line.startswith("MimeType=")
    )
    assert "application/x-qlinux-label" in mime_line
    assert "application/x-brother-lbx" in mime_line


def test_mime_icons_exist_for_both_types():
    icons = ROOT / "assets" / "mimetypes"
    for name in (
        "application-x-qlinux-label.png",
        "application-x-brother-lbx.png",
    ):
        assert (icons / name).is_file()


def test_metainfo_lists_the_mediatypes():
    meta = (ROOT / "packaging" / "ql-editor.metainfo.xml").read_text(encoding="utf-8")
    assert "<mediatype>application/x-qlinux-label</mediatype>" in meta
    assert "<mediatype>application/x-brother-lbx</mediatype>" in meta
