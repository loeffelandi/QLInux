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
    assert "128x128/mimetypes" in build


def test_desktop_file_opens_files_and_claims_both_types():
    desktop = (ROOT / "packaging" / "ql-editor.desktop").read_text(encoding="utf-8")
    assert "Exec=ql-editor %F" in desktop
    mime_line = next(
        line for line in desktop.splitlines() if line.startswith("MimeType=")
    )
    assert "application/x-qlinux-label" in mime_line
    assert "application/x-brother-lbx" in mime_line


def test_mime_icons_exist_for_both_types():
    from PIL import Image

    icons = ROOT / "assets" / "mimetypes"
    for name in (
        "application-x-qlinux-label.png",
        "application-x-brother-lbx.png",
    ):
        large = Image.open(icons / name)
        small = Image.open(icons / "128" / name)
        assert large.size == (256, 256)
        assert small.size == (128, 128)


def test_metainfo_lists_the_mediatypes():
    meta = (ROOT / "packaging" / "ql-editor.metainfo.xml").read_text(encoding="utf-8")
    assert "<mediatype>application/x-qlinux-label</mediatype>" in meta
    assert "<mediatype>application/x-brother-lbx</mediatype>" in meta


def test_pyinstaller_spec_builds_the_mac_bundle():
    text = (ROOT / "packaging" / "ql_editor.spec").read_text(encoding="utf-8")
    assert "BUNDLE(" in text and "QLInux.app" in text
    assert "io.github.loeffelandi.QLInux" in text
    for key in (
        "NSHighResolutionCapable",
        "NSLocalNetworkUsageDescription",
        "NSBonjourServices",
        "_pdl-datastream._tcp",
        "CFBundleDocumentTypes",
        "LSMinimumSystemVersion",
    ):
        assert key in text
    assert '"qlx"' in text and '"lbx"' in text
    # libusb gehoert ins Bundle; ohne sie bricht der Bau ab.
    assert "libusb" in text and "binaries" in text
    # Die Mindestversion kommt aus den Bundle-Dateien, nicht aus einer Zahl im Rezept.
    assert "_minimum_macos(a.binaries)" in text
    # Linux-Teil des Rezepts bleibt: COLLECT ohne BUNDLE ausserhalb von darwin.
    assert "COLLECT(" in text


def test_mac_build_script_checks_libusb_and_architecture():
    script = (ROOT / "packaging" / "build_macos.sh").read_text(encoding="utf-8")
    assert "arm64" in script and "hdiutil" in script
    assert "libusb" in script and "otool" in script
    assert "QLINUX_SELFTEST=libusb" in script
    entry = (ROOT / "packaging" / "entrypoint.py").read_text(encoding="utf-8")
    assert "QLINUX_SELFTEST" in entry


def test_icns_files_exist_for_the_app_and_both_file_types():
    icons = [
        ROOT / "assets" / "ql-editor.icns",
        ROOT / "assets" / "mimetypes" / "application-x-qlinux-label.icns",
        ROOT / "assets" / "mimetypes" / "application-x-brother-lbx.icns",
    ]
    for icon in icons:
        data = icon.read_bytes()
        assert data[:4] == b"icns", icon
        assert len(data) > 10_000, icon
    spec = (ROOT / "packaging" / "ql_editor.spec").read_text(encoding="utf-8")
    for icon in icons:
        assert icon.name in spec
