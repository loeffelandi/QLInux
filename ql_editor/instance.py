"""Eine laufende QLInux-Instanz: weitere Dateien landen in ihrem Fenster.

Doppelklickt man im Dateimanager eine zweite ``.qlx``, startet ein neuer
Prozess. Der prueft zuerst, ob schon eine Instanz lauscht. Ist das der Fall,
schickt er die Pfade dorthin (eine leere Liste nur zum Fokussieren) und
beendet sich - die laufende Instanz oeffnet die Dateien als neue Reiter.

Der Kanal ist ein lokaler Socket (QLocalServer/QLocalSocket). Eine Nachricht
ist eine JSON-Liste von Pfaden, abgeschlossen mit einem Zeilenende.

Wichtig: ``QLocalServer.UserAccessOption`` wird absichtlich nicht gesetzt.
Unter Unix loescht diese Option den Socket-Namen vor ``listen`` und erlaubt
damit einem zweiten Start, der Owner-Instanz den Kanal zu stehlen. Stattdessen
setzt ``listen`` nach erfolgreichem Bind die Rechte per ``chmod 0700``.
``removeServer`` nur bei verwaistem Socket (Absturz), nie gegen eine lebende
Owner-Instanz.
"""

from __future__ import annotations

import getpass
import json
import os
import time
from typing import Callable, Sequence

from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "user"


#: Socket-Name pro Benutzer - zwei Benutzer auf einem Rechner stoeren sich nicht.
SERVER_NAME = f"QLInux-{_user()}"

_CONNECT_MS = 500
_WRITE_MS = 1000


def _peer_alive(name: str, timeout_ms: int = _CONNECT_MS) -> bool:
    """True, wenn unter ``name`` schon jemand annimmt (lebende Owner-Instanz)."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(timeout_ms)
    return True


def _tighten_socket_permissions(server: QLocalServer) -> None:
    """Nur der eigene Benutzer darf den Socket oeffnen (Ersatz fuer UserAccessOption)."""
    path = server.fullServerName()
    if not path:
        return
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def forward(
    paths: Sequence[str],
    name: str = SERVER_NAME,
    *,
    attempts: int = 1,
    retry_ms: int = 50,
) -> bool:
    """Pfade an eine laufende Instanz schicken. ``False``, wenn keine lauscht
    oder Schreiben/Flush scheitert (dann Exit ≠ 0 bzw. lokales Öffnen).

    ``attempts`` > 1 hilft bei knappen TOCTOU-Rennen (zwei Starts mit Dateien).
    """
    payload = json.dumps(list(paths)).encode("utf-8") + b"\n"
    for attempt in range(max(1, attempts)):
        if _forward_once(payload, name):
            return True
        if attempt + 1 < attempts:
            time.sleep(max(0, retry_ms) / 1000.0)
    return False


def _forward_once(payload: bytes, name: str) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(_CONNECT_MS):
        return False
    written = socket.write(payload)
    if written < 0:
        socket.disconnectFromServer()
        return False
    if not socket.waitForBytesWritten(_WRITE_MS):
        socket.disconnectFromServer()
        return False
    # Teilweise geschrieben: restlichen Puffer noch abwarten.
    if written < len(payload) and not socket.waitForBytesWritten(_WRITE_MS):
        socket.disconnectFromServer()
        return False
    socket.disconnectFromServer()
    return True


def listen(
    on_paths: Callable[[list[str]], None], name: str = SERVER_NAME
) -> QLocalServer | None:
    """Auf Pfade von weiteren Starts warten. ``None``, wenn der Name belegt ist.

    Verwaiste Sockets (Absturz) werden einmalig entfernt und erneut versucht.
    Lebende Owner werden nicht verdraengt: zweiter Start bekommt ``None``.

    Der Aufrufer muss den Rueckgabewert behalten, sonst schliesst Qt den Server.
    """
    server = QLocalServer()
    if not server.listen(name):
        # Belegt durch lebende Instanz → nicht stehlen.
        if _peer_alive(name):
            return None
        # Verwaist nach Absturz: Name freigeben und einmal neu versuchen.
        QLocalServer.removeServer(name)
        if not server.listen(name):
            return None
    _tighten_socket_permissions(server)

    def serve() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.setParent(server)
        buffer = bytearray()
        done = False

        def read() -> None:
            nonlocal done
            if done:
                return
            buffer.extend(bytes(conn.readAll()))
            line, newline, _ = bytes(buffer).partition(b"\n")
            if not newline:
                return
            done = True
            conn.disconnectFromServer()
            try:
                paths = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return
            if isinstance(paths, list):
                on_paths([str(p) for p in paths])

        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)
        read()

    server.newConnection.connect(serve)
    return server
