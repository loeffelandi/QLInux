"""Eine laufende QLInux-Instanz: weitere Dateien landen in ihrem Fenster.

Doppelklickt man im Dateimanager eine zweite ``.qlx``, startet ein neuer
Prozess. Der prueft zuerst, ob schon eine Instanz lauscht. Ist das der Fall,
schickt er die Pfade dorthin und beendet sich - die laufende Instanz oeffnet
die Dateien als neue Reiter.

Der Kanal ist ein lokaler Socket (QLocalServer/QLocalSocket). Eine Nachricht
ist eine JSON-Liste von Pfaden, abgeschlossen mit einem Zeilenende.
"""

from __future__ import annotations

import getpass
import json
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


def forward(paths: Sequence[str], name: str = SERVER_NAME) -> bool:
    """Pfade an eine laufende Instanz schicken. ``False``, wenn keine lauscht."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(_CONNECT_MS):
        return False
    socket.write(json.dumps(list(paths)).encode("utf-8") + b"\n")
    socket.flush()
    socket.waitForBytesWritten(_WRITE_MS)
    return True


def listen(
    on_paths: Callable[[list[str]], None], name: str = SERVER_NAME
) -> QLocalServer | None:
    """Auf Pfade von weiteren Starts warten. ``None``, wenn der Name belegt ist.

    Der Aufrufer muss den Rueckgabewert behalten, sonst schliesst Qt den Server.
    """
    server = QLocalServer()
    # Nur der eigene Benutzer darf den Socket oeffnen.
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    # Ein Socket von einem abgestuerzten Lauf ist sonst im Weg.
    QLocalServer.removeServer(name)
    if not server.listen(name):
        return None

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
            try:
                paths = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                paths = []
            conn.disconnectFromServer()
            if isinstance(paths, list) and paths:
                on_paths([str(p) for p in paths])

        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)
        read()

    server.newConnection.connect(serve)
    return server
