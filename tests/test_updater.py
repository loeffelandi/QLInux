"""Selbst-Update: Suche, Vergleich, Download, Ersetzen, Neustart (ql_editor.updater)."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from ql_editor import __version__, updater
from ql_editor.settings import AppSettings
from tests.update_server import _asset, _release, _Server


@pytest.fixture
def server(monkeypatch):
    srv = _Server()
    monkeypatch.setattr(updater, "_ALLOWED_SCHEMES", ("https", "http"))
    monkeypatch.setattr(updater, "RELEASES_URL", srv.base + "/latest")
    yield srv
    srv.shutdown()
    srv.server_close()


# --------------------------------------------------------------------------- #
# Version und Datei
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.5.1", (0, 5, 1)),
        ("0.5.1", (0, 5, 1)),
        ("v10.2.30", (10, 2, 30)),
        ("v0.5", None),
        ("v0.5.1-rc1", None),
        ("nightly", None),
        ("", None),
    ],
)
def test_parse_version(text, expected):
    assert updater.parse_version(text) == expected


def test_versions_compare_as_numbers_not_as_text():
    assert updater.parse_version("v0.10.0") > updater.parse_version("v0.9.0")


@pytest.mark.parametrize(
    ("kind", "machine", "expected"),
    [
        (updater.KIND_APPIMAGE, "x86_64", "QLInux-0.6.0-x86_64.AppImage"),
        (updater.KIND_APPIMAGE, "AMD64", "QLInux-0.6.0-x86_64.AppImage"),
        (updater.KIND_APPIMAGE, "aarch64", "QLInux-0.6.0-aarch64.AppImage"),
        (updater.KIND_APPIMAGE, "armv7l", None),
        (updater.KIND_APP, "arm64", "QLInux-0.6.0-arm64.dmg"),
        (updater.KIND_APP, "x86_64", None),
    ],
)
def test_asset_name(kind, machine, expected):
    assert updater.asset_name(kind, "0.6.0", machine) == expected


def test_newer_release_with_file_and_checksum_is_an_update():
    data = b"appimage"
    release = _release(
        "v0.6.0", [_asset("QLInux-0.6.0-x86_64.AppImage", data, "https://h/x")]
    )
    result = updater.evaluate(release, "0.5.1", updater.KIND_APPIMAGE, "x86_64")
    assert result.pending is False
    update = result.update
    assert update is not None
    assert update.version == "0.6.0"
    assert update.url == "https://h/x"
    assert update.sha256 == hashlib.sha256(data).hexdigest()
    assert update.size == len(data)
    assert update.page.endswith("/v0.6.0")


@pytest.mark.parametrize("tag", ["v0.5.1", "v0.5.0", "v0.4.9"])
def test_same_or_older_release_is_not_an_update(tag):
    release = _release(tag, [_asset(f"QLInux-{tag[1:]}-x86_64.AppImage")])
    result = updater.evaluate(release, "0.5.1", updater.KIND_APPIMAGE, "x86_64")
    assert result == updater.CheckResult()


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_drafts_and_prereleases_are_ignored(flag):
    release = _release("v0.6.0", [_asset("QLInux-0.6.0-x86_64.AppImage")])
    release[flag] = True
    result = updater.evaluate(release, "0.5.1", updater.KIND_APPIMAGE, "x86_64")
    assert result == updater.CheckResult()


def test_unreadable_tag_is_no_update():
    release = _release("nightly", [_asset("QLInux-0.6.0-x86_64.AppImage")])
    assert updater.evaluate(release, "0.5.1", updater.KIND_APPIMAGE, "x86_64") == (
        updater.CheckResult()
    )


def test_release_without_the_file_for_this_platform_is_pending():
    release = _release("v0.6.0", [_asset("QLInux-0.6.0-arm64.dmg")])
    result = updater.evaluate(release, "0.5.1", updater.KIND_APPIMAGE, "x86_64")
    assert result.update is None
    assert result.pending is True


def test_release_without_checksum_is_pending():
    asset = _asset("QLInux-0.6.0-x86_64.AppImage")
    del asset["digest"]
    result = updater.evaluate(
        _release("v0.6.0", [asset]), "0.5.1", updater.KIND_APPIMAGE, "x86_64"
    )
    assert result.update is None
    assert result.pending is True


def test_release_with_a_broken_checksum_is_pending():
    asset = _asset("QLInux-0.6.0-x86_64.AppImage")
    asset["digest"] = "sha1:abc"
    result = updater.evaluate(
        _release("v0.6.0", [asset]), "0.5.1", updater.KIND_APPIMAGE, "x86_64"
    )
    assert result.update is None
    assert result.pending is True


def test_intel_mac_gets_no_dmg_update():
    release = _release("v0.6.0", [_asset("QLInux-0.6.0-arm64.dmg")])
    assert updater.evaluate(release, "0.5.1", updater.KIND_APP, "x86_64") == (
        updater.CheckResult()
    )


# --------------------------------------------------------------------------- #
# Wer sich aktualisiert
# --------------------------------------------------------------------------- #
def test_source_checkout_is_not_updatable(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert updater.install_kind() is None
    assert updater.is_updatable() is False


def test_appimage_is_updatable_when_the_file_exists(monkeypatch, tmp_path):
    image = tmp_path / "QLInux-0.5.1-x86_64.AppImage"
    image.write_bytes(b"x")
    monkeypatch.setenv("APPIMAGE", str(image))
    assert updater.install_kind() == updater.KIND_APPIMAGE
    assert updater.install_path(updater.KIND_APPIMAGE) == image


def test_appimage_variable_to_a_missing_file_is_not_updatable(monkeypatch, tmp_path):
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "gone.AppImage"))
    assert updater.install_kind() is None


def test_packed_mac_bundle_is_updatable(monkeypatch, tmp_path, platform):
    platform("darwin")
    binary = tmp_path / "QLInux.app" / "Contents" / "MacOS" / "ql-editor"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    assert updater.install_kind() == updater.KIND_APP
    assert updater.install_path(updater.KIND_APP) == (tmp_path / "QLInux.app").resolve()


def test_mac_from_source_is_not_updatable(monkeypatch, platform):
    platform("darwin")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert updater.install_kind() is None


# --------------------------------------------------------------------------- #
# Einstellungen und Wann gesucht wird
# --------------------------------------------------------------------------- #
def _settings(tmp_path: Path) -> AppSettings:
    return AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))


def test_update_settings_defaults(tmp_path):
    settings = _settings(tmp_path)
    assert settings.update_check_on_start is True
    assert settings.update_last_check == 0.0
    assert settings.update_skipped_version == ""


def test_update_settings_are_saved(tmp_path):
    settings = _settings(tmp_path)
    settings.update_check_on_start = False
    settings.update_last_check = 1234.5
    settings.update_skipped_version = "0.6.0"
    settings.sync()
    again = _settings(tmp_path)
    assert again.update_check_on_start is False
    assert again.update_last_check == 1234.5
    assert again.update_skipped_version == "0.6.0"


def test_update_last_check_survives_garbage(tmp_path):
    settings = _settings(tmp_path)
    settings.set_value("updates/last_check", "gestern")
    assert settings.update_last_check == 0.0


@pytest.fixture
def packed(monkeypatch, tmp_path):
    image = tmp_path / "QLInux.AppImage"
    image.write_bytes(b"x")
    monkeypatch.setenv("APPIMAGE", str(image))
    monkeypatch.delenv(updater.DISABLE_ENV, raising=False)
    return image


def test_check_is_due_on_the_first_start(packed, tmp_path):
    assert updater.check_due(_settings(tmp_path), now=1_000_000.0) is True


def test_check_is_not_due_within_24_hours(packed, tmp_path):
    settings = _settings(tmp_path)
    settings.update_last_check = 1_000_000.0
    assert updater.check_due(settings, now=1_000_000.0 + 23 * 3600) is False
    assert updater.check_due(settings, now=1_000_000.0 + 24 * 3600) is True


def test_check_is_not_due_when_the_switch_is_off(packed, tmp_path):
    settings = _settings(tmp_path)
    settings.update_check_on_start = False
    assert updater.check_due(settings, now=1_000_000.0) is False


def test_check_is_not_due_with_the_environment_switch(packed, tmp_path, monkeypatch):
    monkeypatch.setenv(updater.DISABLE_ENV, "1")
    assert updater.check_due(_settings(tmp_path), now=1_000_000.0) is False


def test_check_is_not_due_from_source(monkeypatch, tmp_path):
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert updater.check_due(_settings(tmp_path), now=1_000_000.0) is False


# --------------------------------------------------------------------------- #
# Abfrage
# --------------------------------------------------------------------------- #
def test_fetch_latest_reads_the_release(server):
    release = _release("v0.6.0")
    server.body("/latest", json.dumps(release).encode())
    assert updater.fetch_latest()["tag_name"] == "v0.6.0"


def test_fetch_latest_sends_program_and_version_only(server):
    seen: dict[str, str] = {}

    def route(handler: BaseHTTPRequestHandler) -> None:
        seen.update({k.lower(): v for k, v in handler.headers.items()})
        data = b"{}"
        handler.send_response(200)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    server.routes["/latest"] = route
    updater.fetch_latest()
    assert seen["user-agent"] == f"QLInux/{__version__}"
    assert not {"cookie", "authorization", "referer"} & set(seen)


def test_fetch_latest_reports_http_errors(server):
    server.body("/latest", b"nope", status=500)
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest()


def test_fetch_latest_reports_unreadable_answers(server):
    server.body("/latest", b"<html>")
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest()
    server.body("/latest", b"[1, 2]")
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest()


def test_fetch_latest_gives_up_after_the_time_limit(server, monkeypatch):
    monkeypatch.setattr(updater, "REQUEST_TIMEOUT", 0.2)
    server.stall("/latest", 1.5)
    started = time.monotonic()
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest()
    assert time.monotonic() - started < 1.2


def test_fetch_latest_reports_a_missing_network(monkeypatch):
    monkeypatch.setattr(updater, "_ALLOWED_SCHEMES", ("https", "http"))
    monkeypatch.setattr(updater, "RELEASES_URL", "http://127.0.0.1:9/latest")
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest()


def test_unencrypted_address_is_refused(server):
    server.body("/latest", b"{}")
    updater._ALLOWED_SCHEMES = ("https",)
    with pytest.raises(updater.UpdateError, match="Unverschlüsselt"):
        updater.fetch_latest()


def test_redirect_to_an_unencrypted_address_is_refused(server, monkeypatch):
    monkeypatch.setattr(updater, "_ALLOWED_SCHEMES", ("https",))
    monkeypatch.setattr(updater, "RELEASES_URL", "https://127.0.0.1:9/latest")
    # Die Weiterleitung ist der Punkt; die Verbindung selbst scheitert vorher.
    handler = updater._SecureRedirects()
    with pytest.raises(updater.UpdateError, match="Unverschlüsselt"):
        handler.redirect_request(
            None, None, 302, "Found", {}, "http://evil.example/file"
        )


def test_check_without_a_packed_install_asks_nobody(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(updater, "fetch_latest", lambda: pytest.fail("kein Netz"))
    assert updater.check() == updater.CheckResult()


def test_check_finds_the_update_for_this_machine(server, monkeypatch, packed):
    data = b"new"
    server.body(
        "/latest",
        json.dumps(
            _release("v99.0.0", [_asset("QLInux-99.0.0-x86_64.AppImage", data)])
        ).encode(),
    )
    result = updater.check("x86_64")
    assert result.update is not None
    assert result.update.version == "99.0.0"


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def test_download_writes_and_checks_the_file(server, tmp_path):
    data = os.urandom(300_000)
    server.body("/file", data)
    target = tmp_path / "part"
    steps: list[tuple[int, int]] = []
    updater.download(
        server.base + "/file",
        target,
        hashlib.sha256(data).hexdigest(),
        progress=lambda done, total: steps.append((done, total)),
    )
    assert target.read_bytes() == data
    assert steps[-1] == (len(data), len(data))
    assert [done for done, _ in steps] == sorted(done for done, _ in steps)


def test_download_follows_a_redirect(server, tmp_path):
    data = b"hinter der weiterleitung"
    server.body("/real", data)
    server.redirect("/file", server.base + "/real")
    target = tmp_path / "part"
    updater.download(server.base + "/file", target, hashlib.sha256(data).hexdigest())
    assert target.read_bytes() == data


def test_download_with_a_wrong_checksum_removes_the_file(server, tmp_path):
    server.body("/file", b"echt")
    target = tmp_path / "part"
    with pytest.raises(updater.UpdateError, match="Prüfsumme"):
        updater.download(
            server.base + "/file", target, hashlib.sha256(b"anders").hexdigest()
        )
    assert not target.exists()


def test_truncated_download_removes_the_file(server, tmp_path):
    data = b"a" * 1000
    server.truncated("/file", data, claimed=5000)
    target = tmp_path / "part"
    with pytest.raises(updater.UpdateError):
        updater.download(
            server.base + "/file", target, hashlib.sha256(data).hexdigest()
        )
    assert not target.exists()


def test_download_error_leaves_no_file(server, tmp_path):
    target = tmp_path / "part"
    with pytest.raises(updater.UpdateError):
        updater.download(server.base + "/missing", target, "0" * 64)
    assert not target.exists()


def test_cancelled_download_removes_the_half_file(server, tmp_path):
    data = os.urandom(1_000_000)
    server.body("/file", data)
    target = tmp_path / "part"
    cancel = threading.Event()
    with pytest.raises(updater.UpdateCancelled):
        updater.download(
            server.base + "/file",
            target,
            hashlib.sha256(data).hexdigest(),
            progress=lambda done, total: cancel.set(),
            cancel=cancel,
        )
    assert not target.exists()


def test_download_refuses_an_unencrypted_address(tmp_path):
    target = tmp_path / "part"
    with pytest.raises(updater.UpdateError, match="Unverschlüsselt"):
        updater.download("http://example.org/file", target, "0" * 64)
    assert not target.exists()


# --------------------------------------------------------------------------- #
# AppImage ersetzen
# --------------------------------------------------------------------------- #
def test_install_appimage_replaces_in_one_step_and_keeps_it_executable(tmp_path):
    target = tmp_path / "QLInux-0.5.1-x86_64.AppImage"
    target.write_bytes(b"alt")
    target.chmod(0o750)
    new = updater.staging_path(target)
    new.write_bytes(b"neu")
    new.chmod(0o600)
    updater.install_appimage(new, target)
    assert target.read_bytes() == b"neu"
    assert target.stat().st_mode & 0o111 == 0o111 & target.stat().st_mode
    assert os.access(target, os.X_OK)
    assert not new.exists()


def test_install_appimage_leaves_the_old_file_when_replacing_fails(
    tmp_path, monkeypatch
):
    target = tmp_path / "QLInux.AppImage"
    target.write_bytes(b"alt")
    new = updater.staging_path(target)
    new.write_bytes(b"neu")

    def boom(*args):
        raise PermissionError("kein Zugriff")

    monkeypatch.setattr(updater.os, "replace", boom)
    with pytest.raises(updater.UpdateError, match="QLInux.AppImage"):
        updater.install_appimage(new, target)
    assert target.read_bytes() == b"alt"
    assert not new.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root darf in jeden Ordner schreiben")
def test_unwritable_folder_is_reported_with_its_path(tmp_path):
    folder = tmp_path / "ro"
    folder.mkdir()
    target = folder / "QLInux.AppImage"
    target.write_bytes(b"alt")
    folder.chmod(0o500)
    try:
        with pytest.raises(updater.UpdateError) as caught:
            updater.ensure_writable(target)
        assert str(folder) in str(caught.value)
    finally:
        folder.chmod(0o700)
    assert target.read_bytes() == b"alt"


def test_cleanup_removes_leftovers_of_an_aborted_appimage_update(packed):
    leftover = updater.staging_path(packed)
    leftover.write_bytes(b"halb")
    other = packed.with_name("notizen.txt")
    other.write_text("bleibt")
    updater.cleanup_leftovers(updater.KIND_APPIMAGE)
    assert not leftover.exists()
    assert packed.exists()
    assert other.exists()


def test_cleanup_removes_leftovers_of_an_aborted_app_update(
    monkeypatch, tmp_path, platform
):
    platform("darwin")
    binary = tmp_path / "QLInux.app" / "Contents" / "MacOS" / "ql-editor"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"x")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(binary))
    base = tmp_path.resolve()
    for name in (".QLInux-update-1.app", ".QLInux-old-2.app"):
        (base / name / "Contents").mkdir(parents=True)
    (base / "Andere.app").mkdir()
    updater.cleanup_leftovers(updater.KIND_APP)
    assert sorted(path.name for path in base.iterdir()) == ["Andere.app", "QLInux.app"]


# --------------------------------------------------------------------------- #
# Neustart
# --------------------------------------------------------------------------- #
def test_restart_command_for_an_appimage():
    command = updater.restart_command(
        updater.KIND_APPIMAGE, Path("/opt/QLInux.AppImage"), ["/a.qlx", "/b.qlx"], 42
    )
    assert command[:3] == ["sh", "-c", updater._WAIT_THEN_RUN]
    assert command[3:] == [
        "sh",
        "42",
        "/opt/QLInux.AppImage",
        "/a.qlx",
        "/b.qlx",
    ]


def test_restart_command_for_the_app_opens_a_new_instance():
    command = updater.restart_command(
        updater.KIND_APP, Path("/Applications/QLInux.app"), ["/a.qlx"], 7
    )
    assert command[4:] == [
        "7",
        "open",
        "-n",
        "/Applications/QLInux.app",
        "--args",
        "/a.qlx",
    ]


def test_restart_helper_starts_the_new_file_after_the_old_process_ended(tmp_path):
    out = tmp_path / "args.txt"
    script = tmp_path / "QLInux.AppImage"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{out}"\n')
    script.chmod(0o755)
    finished = subprocess.Popen(["true"])
    finished.wait()
    updater.start_restart(
        updater.restart_command(
            updater.KIND_APPIMAGE, script, ["/eins.qlx", "/zwei.qlx"], finished.pid
        )
    )
    deadline = time.monotonic() + 5
    while not out.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert out.read_text().split() == ["/eins.qlx", "/zwei.qlx"]


def test_restart_helper_waits_for_the_running_process(tmp_path):
    out = tmp_path / "args.txt"
    script = tmp_path / "QLInux.AppImage"
    script.write_text(f'#!/bin/sh\nprintf "ok" > "{out}"\n')
    script.chmod(0o755)
    running = subprocess.Popen(["sleep", "1.2"])
    updater.start_restart(
        updater.restart_command(updater.KIND_APPIMAGE, script, [], running.pid)
    )
    time.sleep(0.5)
    assert not out.exists()
    running.wait()
    deadline = time.monotonic() + 5
    while not out.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert out.read_text() == "ok"


def test_fresh_environment_drops_the_old_appimage(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/old")
    monkeypatch.setenv("APPDIR", "/tmp/.mount_old")
    monkeypatch.setenv("ARGV0", "old")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_old/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/local/lib")
    env = updater._fresh_environment()
    assert "APPIMAGE" not in env and "APPDIR" not in env and "ARGV0" not in env
    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_fresh_environment_without_a_saved_library_path(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_old/lib")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    assert "LD_LIBRARY_PATH" not in updater._fresh_environment()


# --------------------------------------------------------------------------- #
# QLInux.app ersetzen (nur macOS: hdiutil, ditto, codesign)
# --------------------------------------------------------------------------- #
mac_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="hdiutil, ditto und codesign gibt es nur auf dem Mac",
)


def _make_app(folder: Path, version: str, *, sign: bool = True) -> Path:
    app = folder / "QLInux.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "ql-editor").write_text("#!/bin/sh\nexit 0\n")
    (macos / "ql-editor").chmod(0o755)
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleName": "QLInux",
                "CFBundleExecutable": "ql-editor",
                "CFBundleIdentifier": "io.github.loeffelandi.QLInux.test",
                "CFBundleShortVersionString": version,
            }
        )
    )
    if sign:
        subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", str(app)],
            check=True,
            capture_output=True,
        )
    return app


def _make_dmg(folder: Path, version: str, *, sign: bool = True) -> Path:
    stage = folder / "stage"
    stage.mkdir()
    _make_app(stage, version, sign=sign)
    dmg = folder / f"QLInux-{version}-arm64.dmg"
    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "QLInux",
            "-srcfolder",
            str(stage),
            "-fs",
            "HFS+",
            "-format",
            "UDZO",
            "-ov",
            str(dmg),
        ],
        check=True,
        capture_output=True,
    )
    return dmg


def _version_of(app: Path) -> str:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    return info["CFBundleShortVersionString"]


@pytest.fixture
def installed_app(tmp_path):
    folder = tmp_path / "Programme"
    folder.mkdir()
    return _make_app(folder, "0.5.1")


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


@mac_only
def test_install_app_replaces_the_running_bundle(installed_app, tmp_path):
    dmg = _make_dmg(tmp_path, "0.6.0")
    updater.install_app(dmg, installed_app, "0.6.0")
    assert _version_of(installed_app) == "0.6.0"
    assert _names(installed_app.parent) == ["QLInux.app"]


@mac_only
def test_install_app_detaches_the_image(installed_app, tmp_path):
    dmg = _make_dmg(tmp_path, "0.6.0")
    updater.install_app(dmg, installed_app, "0.6.0")
    info = subprocess.run(
        ["hdiutil", "info"], check=False, capture_output=True, text=True
    ).stdout
    assert str(dmg) not in info


@mac_only
def test_install_app_refuses_the_wrong_version(installed_app, tmp_path):
    dmg = _make_dmg(tmp_path, "0.6.0")
    with pytest.raises(updater.UpdateError, match="0.6.0"):
        updater.install_app(dmg, installed_app, "0.7.0")
    assert _version_of(installed_app) == "0.5.1"
    assert _names(installed_app.parent) == ["QLInux.app"]


@mac_only
def test_install_app_refuses_a_broken_signature(installed_app, tmp_path):
    dmg = _make_dmg(tmp_path, "0.6.0", sign=False)
    with pytest.raises(updater.UpdateError):
        updater.install_app(dmg, installed_app, "0.6.0")
    assert _version_of(installed_app) == "0.5.1"
    assert _names(installed_app.parent) == ["QLInux.app"]


@mac_only
def test_install_app_refuses_a_file_that_is_no_image(installed_app, tmp_path):
    fake = tmp_path / "QLInux-0.6.0-arm64.dmg"
    fake.write_bytes(b"kein dmg")
    with pytest.raises(updater.UpdateError):
        updater.install_app(fake, installed_app, "0.6.0")
    assert _version_of(installed_app) == "0.5.1"


@mac_only
def test_install_app_puts_the_old_app_back_when_the_swap_fails(
    installed_app, tmp_path, monkeypatch
):
    dmg = _make_dmg(tmp_path, "0.6.0")
    real_rename = os.rename
    calls: list[int] = []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("zweites Umbenennen scheitert")
        real_rename(src, dst)

    monkeypatch.setattr(updater.os, "rename", flaky)
    with pytest.raises(updater.UpdateError):
        updater.install_app(dmg, installed_app, "0.6.0")
    assert _version_of(installed_app) == "0.5.1"
    assert _names(installed_app.parent) == ["QLInux.app"]


@pytest.mark.skipif(
    sys.platform != "darwin" or os.geteuid() == 0, reason="Ordnerrechte auf dem Mac"
)
def test_install_app_in_an_unwritable_folder_changes_nothing(installed_app, tmp_path):
    dmg = _make_dmg(tmp_path, "0.6.0")
    folder = installed_app.parent
    folder.chmod(0o500)
    try:
        with pytest.raises(updater.UpdateError):
            updater.install_app(dmg, installed_app, "0.6.0")
    finally:
        folder.chmod(0o700)
    assert _version_of(installed_app) == "0.5.1"
    assert _names(folder) == ["QLInux.app"]
