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
        _wait_for(qapp, lambda: False, 0.3)
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
        monkeypatch.setattr(
            QLocalSocket, "write", lambda self, data: -1, raising=True
        )
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
        assert instance.forward(
            ["/tmp/handoff.qlx"], name, attempts=5, retry_ms=20
        )
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
