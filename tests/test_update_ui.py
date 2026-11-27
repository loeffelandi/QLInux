"""Selbst-Update in der Oberflaeche: Hinweis beim Start, Menue, Installation, Neustart."""

from __future__ import annotations

import json
import platform as platform_module
import time

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox
from ql_editor import app as app_module
from ql_editor import updater
from ql_editor.settings import AppSettings
from tests.update_server import _asset, _release, _Server

pytestmark = pytest.mark.usefixtures("qapp")

NEW = "99.0.0"
NEW_NAME = f"QLInux-{NEW}-x86_64.AppImage"


@pytest.fixture
def server(monkeypatch):
    srv = _Server()
    monkeypatch.setattr(updater, "_ALLOWED_SCHEMES", ("https", "http"))
    monkeypatch.setattr(updater, "RELEASES_URL", srv.base + "/latest")
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def packed(monkeypatch, tmp_path):
    """Eine ersetzbare AppImage-Installation auf einem x86_64-Rechner."""
    folder = tmp_path / "Programme"
    folder.mkdir()
    image = folder / "QLInux-0.5.1-x86_64.AppImage"
    image.write_bytes(b"alt")
    image.chmod(0o755)
    monkeypatch.setenv("APPIMAGE", str(image))
    monkeypatch.delenv(updater.DISABLE_ENV, raising=False)
    monkeypatch.setattr(platform_module, "machine", lambda: "x86_64")
    monkeypatch.setattr(app_module, "_restart_command", None)
    return image


def _publish(server, data: bytes = b"neues AppImage", version: str = NEW) -> bytes:
    name = f"QLInux-{version}-x86_64.AppImage"
    server.body("/file", data)
    release = _release(f"v{version}", [_asset(name, data, url=server.base + "/file")])
    server.body("/latest", json.dumps(release).encode())
    return data


def _window(qapp, tmp_path):
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    win = app_module.MainWindow(settings=settings)
    win.show()
    qapp.processEvents()
    return win


def _wait(qapp, condition, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "Zeitlimit"
        qapp.processEvents()
        time.sleep(0.01)


def _box(win, containing: str = "") -> QMessageBox | None:
    for box in win.findChildren(QMessageBox):
        if box.isVisible() and containing in box.text():
            return box
    return None


def _press(win, label: str) -> None:
    box = _box(win)
    assert box is not None
    next(button for button in box.buttons() if button.text() == label).click()


def _close(qapp, win) -> None:
    win._accept_close = True
    win.close()
    qapp.processEvents()
    app_module._wait_for_orphans()


# --------------------------------------------------------------------------- #
# Start
# --------------------------------------------------------------------------- #
def test_start_offers_the_update_and_notes_the_time(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    box = _box(win, NEW)
    assert "0.5" in box.text() or "Installiert" in box.text()
    assert {button.text() for button in box.buttons()} == {
        "Jetzt aktualisieren",
        "Später",
        "Diese Version überspringen",
    }
    assert win._settings.update_last_check > 0
    _close(qapp, win)


def test_start_without_network_is_silent_and_asks_again_next_time(
    qapp, tmp_path, monkeypatch, packed
):
    monkeypatch.setattr(updater, "_ALLOWED_SCHEMES", ("https", "http"))
    monkeypatch.setattr(updater, "RELEASES_URL", "http://127.0.0.1:9/latest")
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: win._updates._check_worker is None)
    qapp.processEvents()
    assert _box(win) is None
    assert win._settings.update_last_check == 0.0
    _close(qapp, win)


def test_second_start_on_the_same_day_does_not_ask(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._settings.update_last_check = time.time()
    win._updates.check_on_start()
    assert win._updates._check_worker is None
    assert _box(win) is None
    _close(qapp, win)


def test_start_switch_off_does_not_ask(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._settings.update_check_on_start = False
    win._updates.check_on_start()
    assert win._updates._check_worker is None
    _close(qapp, win)


def test_up_to_date_start_is_silent_but_remembers_the_check(
    qapp, tmp_path, server, packed
):
    _publish(server, version="0.0.1")
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: win._updates._check_worker is None)
    assert _box(win) is None
    assert win._settings.update_last_check > 0
    _close(qapp, win)


def test_missing_platform_file_is_silent_and_not_remembered(
    qapp, tmp_path, server, packed
):
    release = _release(f"v{NEW}", [_asset(f"QLInux-{NEW}-arm64.dmg")])
    server.body("/latest", json.dumps(release).encode())
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: win._updates._check_worker is None)
    assert _box(win) is None
    assert win._settings.update_last_check == 0.0
    _close(qapp, win)


# --------------------------------------------------------------------------- #
# Knoepfe des Hinweises
# --------------------------------------------------------------------------- #
def test_later_keeps_the_version_open(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _press(win, "Später")
    qapp.processEvents()
    assert win._settings.update_skipped_version == ""
    assert packed.read_bytes() == b"alt"
    _close(qapp, win)


def test_skip_silences_this_version_but_not_a_newer_one(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _press(win, "Diese Version überspringen")
    qapp.processEvents()
    assert win._settings.update_skipped_version == NEW

    win._settings.update_last_check = 0.0
    win._updates.check_on_start()
    _wait(qapp, lambda: win._updates._check_worker is None)
    assert _box(win) is None

    _publish(server, version="99.1.0")
    win._settings.update_last_check = 0.0
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, "99.1.0") is not None)
    _close(qapp, win)


def test_manual_check_shows_a_skipped_version_again(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._settings.update_skipped_version = NEW
    win._updates.check_now()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _close(qapp, win)


# --------------------------------------------------------------------------- #
# Installation und Neustart
# --------------------------------------------------------------------------- #
def _install(qapp, win) -> None:
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _press(win, "Jetzt aktualisieren")
    _wait(qapp, lambda: _box(win, "neu starten") is not None)


def test_update_now_replaces_the_file_and_asks_for_a_restart(
    qapp, tmp_path, server, packed
):
    data = _publish(server)
    win = _window(qapp, tmp_path)
    _install(qapp, win)
    assert packed.read_bytes() == data
    assert packed.stat().st_mode & 0o100
    _press(win, "Später")
    qapp.processEvents()
    assert win.isVisible()
    assert win._restart_request is None
    _close(qapp, win)
    assert app_module._restart_command is None


def test_restart_closes_the_window_and_prepares_the_new_start(
    qapp, tmp_path, server, packed
):
    from ql_editor.items import TextItem

    _publish(server)
    win = _window(qapp, tmp_path)
    saved = tmp_path / "eins.qlx"
    win._add_item(TextItem("Eins", font_pixel_size=20))
    win._active.path = str(saved)
    win._active.document_dirty = False
    win._active.undo.setClean()
    _install(qapp, win)
    _press(win, "Jetzt neu starten")
    qapp.processEvents()
    assert not win.isVisible()
    command = app_module._restart_command
    assert command is not None
    assert str(packed) in command
    assert command[-1] == str(saved)
    app_module._wait_for_orphans()


def test_restart_with_unsaved_changes_cancelled_stays_open(
    qapp, tmp_path, server, packed
):
    from ql_editor.items import TextItem

    _publish(server)
    win = _window(qapp, tmp_path)
    _install(qapp, win)
    win._add_item(TextItem("Ungespeichert", font_pixel_size=20))
    assert win._active.is_dirty()
    _press(win, "Jetzt neu starten")
    qapp.processEvents()
    assert win.isVisible()
    _wait(qapp, lambda: _box(win, "speichern") is not None)
    _press(win, "Abbrechen")
    qapp.processEvents()
    assert win.isVisible()
    assert win._restart_request is None
    assert app_module._restart_command is None
    _close(qapp, win)


def test_wrong_checksum_is_reported_and_the_old_file_stays(
    qapp, tmp_path, server, packed
):
    _publish(server)
    server.body("/file", b"etwas ganz anderes")
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _press(win, "Jetzt aktualisieren")
    _wait(qapp, lambda: _box(win, "Prüfsumme") is not None)
    assert packed.read_bytes() == b"alt"
    assert sorted(path.name for path in packed.parent.iterdir()) == [packed.name]
    _close(qapp, win)


def test_unwritable_folder_is_reported_before_downloading(
    qapp, tmp_path, server, packed, monkeypatch
):
    _publish(server)

    def refuse(target):
        raise updater.UpdateError(
            f"In den Ordner {target.parent} darf QLInux nicht schreiben."
        )

    monkeypatch.setattr(updater, "ensure_writable", refuse)
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _press(win, "Jetzt aktualisieren")
    _wait(qapp, lambda: _box(win, str(packed.parent)) is not None)
    assert packed.read_bytes() == b"alt"
    _close(qapp, win)


# --------------------------------------------------------------------------- #
# Menue und Suche von Hand
# --------------------------------------------------------------------------- #
def _palette_texts(win) -> list[str]:
    texts: list[str] = []

    def walk(entries) -> None:
        for entry in entries:
            texts.append(entry.title)
            walk(entry.children or [])

    walk(win._palette_entries())
    return texts


def test_update_entries_appear_only_in_a_packed_install(qapp, tmp_path, monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    win = _window(qapp, tmp_path)
    assert win._act_check_updates not in win._menu_button.menu().actions()
    assert "Nach Updates suchen…" not in _palette_texts(win)
    _close(qapp, win)


def test_update_entries_are_in_the_menu_and_the_palette(qapp, tmp_path, packed):
    win = _window(qapp, tmp_path)
    actions = win._menu_button.menu().actions()
    assert win._act_check_updates in actions
    assert win._act_update_on_start in actions
    texts = _palette_texts(win)
    assert "Nach Updates suchen…" in texts
    assert "Beim Start nach Updates suchen" in texts
    _close(qapp, win)


def test_start_switch_writes_the_setting(qapp, tmp_path, packed):
    win = _window(qapp, tmp_path)
    assert win._act_update_on_start.isChecked()
    win._act_update_on_start.trigger()
    assert win._settings.update_check_on_start is False
    win._act_update_on_start.trigger()
    assert win._settings.update_check_on_start is True
    _close(qapp, win)


def test_switch_follows_the_stored_setting(qapp, tmp_path, packed):
    settings = AppSettings(
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    settings.update_check_on_start = False
    win = app_module.MainWindow(settings=settings)
    win.show()
    qapp.processEvents()
    assert not win._act_update_on_start.isChecked()
    _close(qapp, win)


def test_manual_check_reports_up_to_date(qapp, tmp_path, server, packed):
    _publish(server, version="0.0.1")
    win = _window(qapp, tmp_path)
    win._settings.update_check_on_start = False
    win._act_check_updates.trigger()
    _wait(qapp, lambda: _box(win, "aktuell") is not None)
    _close(qapp, win)


def test_manual_check_reports_a_missing_network(qapp, tmp_path, monkeypatch, packed):
    monkeypatch.setattr(updater, "_ALLOWED_SCHEMES", ("https", "http"))
    monkeypatch.setattr(updater, "RELEASES_URL", "http://127.0.0.1:9/latest")
    win = _window(qapp, tmp_path)
    win._act_check_updates.trigger()
    _wait(qapp, lambda: _box(win, "GitHub") is not None)
    _close(qapp, win)


def test_manual_check_offers_the_update(qapp, tmp_path, server, packed):
    _publish(server)
    win = _window(qapp, tmp_path)
    win._settings.update_check_on_start = False
    win._act_check_updates.trigger()
    _wait(qapp, lambda: _box(win, NEW) is not None)
    _close(qapp, win)


def test_closing_during_the_check_does_not_crash(qapp, tmp_path, server, packed):
    server.stall("/latest", 0.6)
    win = _window(qapp, tmp_path)
    win._updates.check_on_start()
    qapp.processEvents()
    _close(qapp, win)
    time.sleep(0.8)
    qapp.processEvents()
