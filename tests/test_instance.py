"""Einzel-Instanz: weitere Dateien gehen an die laufende QLInux-Instanz."""

from __future__ import annotations

import time
import uuid

import pytest

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


def test_a_broken_message_is_ignored(qapp):
    from PySide6.QtNetwork import QLocalSocket

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
