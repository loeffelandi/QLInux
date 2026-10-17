"""Windows-Druckwarteschlange (RAW) fuer Brother QL.

pyusb brauchte unter Windows einen WinUSB-Treiber und wuerde den
Brother-Treiber verdraengen. Stattdessen gehen die Rasterdaten als RAW-Job
an die bereits installierte Warteschlange. Einen Rueckkanal gibt es dabei
nicht: Band-Erkennung bleibt aus, wie beim Netzwerkanschluss.

``win32print`` (pywin32) wird erst in den Funktionen importiert, damit das
Modul auf Linux und macOS geladen werden kann - noetig ist es nur unter
Windows, und dort zieht ``requirements.txt`` pywin32 mit.
"""

from __future__ import annotations

SPOOLER_PREFIX = "spooler://"


def queue_name(address: str) -> str:
    """``spooler://Brother QL-820NWB`` -> ``Brother QL-820NWB``."""
    value = (address or "").strip()
    if value.lower().startswith(SPOOLER_PREFIX):
        return value[len(SPOOLER_PREFIX) :]
    return value


def list_printers() -> list[str]:
    """Installierte Warteschlangen, deren Name eine QL-Baureihe nennt.

    Lokal installierte Drucker und verbundene Freigaben. Andere Drucker
    (Buero-Laser, PDF) bleiben draussen - die Liste ist die USB-Auswahl.
    """
    import win32print

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    found: list[str] = []
    for entry in win32print.EnumPrinters(flags):
        name = entry[2] if len(entry) > 2 else ""
        if not name or "QL-" not in name.upper():
            continue
        if name not in found:
            found.append(name)
    return found


def send_raw(name: str, data: bytes) -> None:
    """``data`` als RAW-Auftrag an die Warteschlange ``name`` geben.

    Der Brother-Treiber reicht RAW unveraendert an den Drucker weiter -
    genau die Rasterbefehle, die ``brother_ql`` auch ueber USB schickt.
    """
    import win32print

    queue = (name or "").strip()
    if not queue:
        raise OSError("Warteschlangenname fehlt")
    handle = win32print.OpenPrinter(queue)
    try:
        win32print.StartDocPrinter(handle, 1, ("QLInux", None, "RAW"))
        try:
            win32print.StartPagePrinter(handle)
            written = win32print.WritePrinter(handle, data)
            # pywin32 liefert die Bytezahl oder None, wenn der Aufruf nur
            # Erfolg/Fehler kennt. None ist kein Teilschreiben.
            if written is not None and written != len(data):
                raise OSError(
                    f"Warteschlange hat {written} von {len(data)} Bytes uebernommen"
                )
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)


__all__ = ["SPOOLER_PREFIX", "list_printers", "queue_name", "send_raw"]
