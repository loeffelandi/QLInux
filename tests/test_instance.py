"""Einzel-Instanz: weitere Dateien gehen an die laufende QLInux-Instanz."""

from __future__ import annotations

import time
import uuid

import pytest
from PySide6.QtNetwork import QLocalSocket
from ql_editor import instance

pytestmark = pytest.mark.usefixtures("qapp")


def _unique_name() -> str:
    return f"QLInux-test-{uuid.uuid4().hex}"


def _wait_for(qapp, predicate, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_forward_without_a_running_instance_reports_failure(qapp):
    assert instance.forward(["/tmp/x.qlx"], _unique_name()) is False


def test_paths_reach_the_running_instance(qapp):
    name = _unique_name()
    received: list[list[str]] = []
    server = instance.listen(received.append, name)
    assert server is not None
    try:
        assert instance.forward(["/tmp/a.qlx", "/tmp/b.lbx"], name) is True
        assert _wait_for(qapp, lambda: received)
        assert received == [["/tmp/a.qlx", "/tmp/b.lbx"]]
    finally:
        server.close()


def test_only_label_files_are_forwarded_or_opened(qapp):
    from ql_editor.app import _label_paths

    assert _label_paths(["/x/a.qlx", "/x/b.LBX", "/x/c.txt", "--foo"]) == [
        "/x/a.qlx",
        "/x/b.LBX",
    ]


def test_label_paths_resolve_symlinks(tmp_path):
    from ql_editor.app import _label_paths

    target = tmp_path / "design.qlx"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.qlx"
    link.symlink_to(target)
    resolved = str(target.resolve())
    assert _label_paths([str(link), str(target)]) == [resolved, resolved]


def test_empty_forward_reaches_the_running_instance(qapp):
    """Zweiter Start ohne Datei: leere Liste, die Instanz fokussiert."""
    name = _unique_name()
    received: list[list[str]] = []
    server = instance.listen(received.append, name)
    assert server is not None
    try:
        assert instance.forward([], name) is True
        assert _wait_for(qapp, lambda: received)
        assert received == [[]]
    finally:
        server.close()


def test_second_start_without_files_exits_after_focus(qapp, monkeypatch):
    from ql_editor import app as app_module

    forwarded: list[list[str]] = []

    def forward(paths, **_kwargs):
        forwarded.append(list(paths))
        return True

    monkeypatch.setattr(app_module.instance, "forward", forward)
    assert app_module.main(["ql-editor"]) == 0
    assert forwarded == [[]]


def test_a_broken_message_is_ignored(qapp):
    name = _unique_name()
    received: list[list[str]] = []
    server = instance.listen(received.append, name)
    assert server is not None
    try:
        socket = QLocalSocket()
        socket.connectToServer(name)
        assert socket.waitForConnected(1000)
        socket.write(b"das ist kein json\n")
        socket.flush()
        socket.waitForBytesWritten(1000)
        # readyRead laeuft ueber den Event-Loop; danach darf nichts angekommen sein.
        for _ in range(5):
            qapp.processEvents()
        assert received == []
    finally:
        server.close()


def test_second_listen_does_not_steal_the_owner_socket(qapp):
    """B1: leerer Zweitstart darf den Socket nicht entreissen."""
    name = _unique_name()
    received_a: list[list[str]] = []
    received_b: list[list[str]] = []
    owner = instance.listen(received_a.append, name)
    assert owner is not None
    try:
        interloper = instance.listen(received_b.append, name)
        assert interloper is None

        assert instance.forward(["/tmp/still-a.qlx"], name) is True
        assert _wait_for(qapp, lambda: received_a)
        assert received_a == [["/tmp/still-a.qlx"]]
        assert received_b == []

        # Nach „Schliessen“ des zweiten Starts bleibt A Owner.
        assert instance.forward(["/tmp/after-b.qlx"], name) is True
        assert _wait_for(qapp, lambda: len(received_a) >= 2)
        assert received_a[-1] == ["/tmp/after-b.qlx"]
    finally:
        owner.close()


def test_stale_socket_is_replaced_so_a_new_owner_can_listen(qapp):
    """Absturz-Rest: removeServer nur wenn niemand mehr annimmt."""
    name = _unique_name()
    stale = instance.listen(lambda _paths: None, name)
    assert stale is not None
    # Simuliert Absturz: Server-Objekt weg, Name ggf. noch belegt.
    stale.close()
    stale.deleteLater()
    qapp.processEvents()

    received: list[list[str]] = []
    owner = instance.listen(received.append, name)
    assert owner is not None
    try:
        assert instance.forward(["/tmp/after-crash.qlx"], name) is True
        assert _wait_for(qapp, lambda: received)
        assert received == [["/tmp/after-crash.qlx"]]
    finally:
        owner.close()


def test_forward_returns_false_when_write_fails(qapp, monkeypatch):
    """M1: Schreibfehler → False (Aufrufer oeffnet lokal / Exit ≠ 0)."""
    name = _unique_name()
    server = instance.listen(lambda _paths: None, name)
    assert server is not None
    try:
        monkeypatch.setattr(QLocalSocket, "write", lambda self, data: -1, raising=True)
        assert instance.forward(["/tmp/lost.qlx"], name) is False
    finally:
        server.close()


def test_forward_returns_false_when_flush_wait_fails(qapp, monkeypatch):
    """M1: waitForBytesWritten scheitert → Forward gilt als fehlgeschlagen."""
    name = _unique_name()
    server = instance.listen(lambda _paths: None, name)
    assert server is not None
    try:
        monkeypatch.setattr(
            QLocalSocket,
            "waitForBytesWritten",
            lambda self, msecs=-1: False,
            raising=True,
        )
        assert instance.forward(["/tmp/lost.qlx"], name) is False
    finally:
        server.close()


def test_parallel_listen_only_one_owner_loser_can_forward(qapp):
    """M2: zwei listen() — nur einer haelt den Socket; Verlierer reicht weiter."""
    name = _unique_name()
    received_a: list[list[str]] = []
    received_b: list[list[str]] = []

    first = instance.listen(received_a.append, name)
    second = instance.listen(received_b.append, name)
    # Reihenfolge egal: genau einer ist Owner.
    owners = [s for s in (first, second) if s is not None]
    assert len(owners) == 1
    owner = owners[0]
    owner_received = received_a if first is owner else received_b
    try:
        assert instance.forward(["/tmp/race.qlx"], name, attempts=3, retry_ms=20)
        assert _wait_for(qapp, lambda: owner_received)
        assert owner_received == [["/tmp/race.qlx"]]
        assert (received_a + received_b).count(["/tmp/race.qlx"]) == 1
    finally:
        owner.close()


def test_loser_of_listen_race_hands_paths_to_owner(qapp):
    """M2/main: listen() None + forward(attempts=…) wie nach TOCTOU-Fensteraufbau."""
    name = _unique_name()
    received: list[list[str]] = []
    owner = instance.listen(received.append, name)
    assert owner is not None
    try:
        assert instance.listen(lambda _p: None, name) is None
        assert instance.forward(["/tmp/handoff.qlx"], name, attempts=5, retry_ms=20)
        assert _wait_for(qapp, lambda: received)
        assert received == [["/tmp/handoff.qlx"]]
    finally:
        owner.close()


def test_listen_socket_is_user_only(qapp):
    """Rechte 0700 — ohne UserAccessOption (die den Socket stehlen wuerde)."""
    import os
    import stat

    name = _unique_name()
    server = instance.listen(lambda _p: None, name)
    assert server is not None
    try:
        path = server.fullServerName()
        assert path
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o700
    finally:
        server.close()


# --- macOS: der Finder meldet Dateien als Ereignis ---------------------------


def _file_open_event(path: str):
    from PySide6.QtGui import QFileOpenEvent

    return QFileOpenEvent(path)


@pytest.fixture
def opener(qapp, monkeypatch):
    """Der Filter aus ``main`` auf der QApplication, ohne Fenster."""
    from ql_editor import app as app_module

    monkeypatch.setattr(app_module, "_current_window", None)
    flt = app_module._SystemOpenFilter(qapp)
    qapp.installEventFilter(flt)
    try:
        yield flt
    finally:
        qapp.removeEventFilter(flt)
        flt.deleteLater()


def test_file_open_before_the_window_waits_for_it(qapp, opener, monkeypatch):
    from ql_editor import app as app_module

    opened: list[tuple[object, list[str]]] = []
    monkeypatch.setattr(
        app_module, "_open_from_outside", lambda w, paths: opened.append((w, paths))
    )
    qapp.sendEvent(qapp, _file_open_event("/tmp/a.qlx"))
    qapp.sendEvent(qapp, _file_open_event("/tmp/b.lbx"))
    assert opened == []

    window = object()
    monkeypatch.setattr(app_module, "_current_window", window)
    opener.attach()
    assert opened == [(window, ["/tmp/a.qlx", "/tmp/b.lbx"])]

    qapp.sendEvent(qapp, _file_open_event("/tmp/c.qlx"))
    assert opened[-1] == (window, ["/tmp/c.qlx"])


def test_finder_open_creates_tabs_and_ignores_other_files(
    qapp, opener, tmp_path, monkeypatch
):
    from ql_editor import document, templates
    from ql_editor.app import MainWindow

    first, second = tmp_path / "eins.qlx", tmp_path / "zwei.qlx"
    for path in (first, second):
        document.save(path, templates.builtins()[0][1])
    other = tmp_path / "notiz.txt"
    other.write_text("x", encoding="utf-8")

    from ql_editor import app as app_module

    win = MainWindow(discover=False)
    monkeypatch.setattr(app_module, "_current_window", win)
    try:
        qapp.sendEvent(qapp, _file_open_event(str(first)))  # vor attach: wartet
        opener.attach()
        paths = lambda: [t.path for t in win._ordered_tabs()]
        assert paths() == [str(first.resolve())]

        qapp.sendEvent(qapp, _file_open_event(str(second)))
        qapp.sendEvent(qapp, _file_open_event(str(other)))
        assert paths() == [str(first.resolve()), str(second.resolve())]

        qapp.sendEvent(qapp, _file_open_event(str(first)))  # schon offen
        assert len(paths()) == 2
        assert win._active.path == str(first.resolve())
    finally:
        win._accept_close = True
        win.deleteLater()


def test_dock_click_restores_a_minimized_window(qapp, opener, monkeypatch):
    from PySide6.QtCore import Qt
    from ql_editor import app as app_module

    class Window:
        def __init__(self):
            self.minimized = True
            self.raised = 0

        def isMinimized(self):  # noqa: N802
            return self.minimized

        def showNormal(self):  # noqa: N802
            self.minimized = False

        def raise_(self):
            self.raised += 1

    window = Window()
    monkeypatch.setattr(app_module, "_current_window", window)
    opener._on_state_changed(Qt.ApplicationState.ApplicationInactive)
    assert window.minimized is True
    opener._on_state_changed(Qt.ApplicationState.ApplicationActive)
    assert window.minimized is False
    assert window.raised == 1
