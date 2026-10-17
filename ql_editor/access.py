"""Systemzugriff fuer USB-Drucker: udev-Regel, Rechte, Passwort-Dialog.

USB-Drucker gehoeren auf Linux root (``/dev/usb/lpN`` bzw. der rohe
Geraeteknoten ``/dev/bus/usb/BBB/DDD``). Dagegen hilft genau eine Sache:
eine udev-Regel mit ``TAG+="uaccess"``, die dem Benutzer der aktiven Sitzung
einen ACL-Eintrag gibt. Das Einrichten braucht einmal root - entweder bei der
Installation (postinst des Pakets) oder zur Laufzeit ueber ``pkexec``, das den
Passwort-Dialog des Systems zeigt. Ohne Passwort-Dialog bleibt der Einzeiler
fuer das Terminal (:func:`manual_command`); siehe
:func:`auth_agent_running` fuer den Grund.

Dieses Modul bleibt bewusst ohne Qt und ohne Nebenwirkungen: es sagt, was zu
tun ist und wie das Ergebnis zu lesen ist. Ausgefuehrt wird der Befehl von der
Oberflaeche (``QProcess``), damit sie dabei nicht blockiert.
"""

from __future__ import annotations

from pathlib import Path
import shutil

from .i18n import tr

#: Ablage der Regel, die der Helfer schreibt (gilt fuer alle Benutzer).
UDEV_RULE_FILE = "/etc/udev/rules.d/99-brother-ql.rules"

#: Helfer im installierten Paket.
INSTALLED_HELPER = "/usr/lib/ql-editor/install-udev-rule"

#: Helfer im Projektverzeichnis (Entwicklung / Start aus dem Checkout).
PROJECT_HELPER = Path(__file__).resolve().parent.parent / "scripts" / "install-udev-rule.sh"

#: Rueckgabewerte von pkexec (siehe ``man pkexec``).
PKEXEC_DISMISSED = 126
PKEXEC_FAILED = 127

#: Prozessnamen, die den Passwort-Dialog des Systems (polkit-Agent) anbieten.
#:
#: Bewusst eine Heuristik: ``pkexec`` **wartet endlos**, wenn kein Agent
#: erreichbar ist (am System nachgemessen: kein Prompt, kein Abbruch), und ein
#: haengender Dialog ist die schlechteste Bedienung. Ohne erkannten Agent wird
#: pkexec deshalb gar nicht erst gestartet - dann bleibt der Einzeiler.
AGENT_PROCESSES = frozenset(
    {
        "polkit-gnome-authentication-agent-1",
        "lxpolkit",
        "lxqt-policykit-agent",
        "polkit-kde-authentication-agent-1",
        "mate-polkit",
        "xfce-polkit",
        "gnome-shell",
    }
)


def helper_path() -> Path | None:
    """Der Helfer, der die udev-Regel setzt - aus dem Paket oder aus dem Projekt."""
    for candidate in (Path(INSTALLED_HELPER), PROJECT_HELPER):
        if candidate.is_file():
            return candidate
    return None


def rule_installed() -> bool:
    """Ist die udev-Regel bereits eingerichtet?"""
    return Path(UDEV_RULE_FILE).is_file()


def pkexec_path() -> str | None:
    """Pfad zu ``pkexec`` (polkit) - ``None``, wenn es fehlt."""
    return shutil.which("pkexec")


def install_command() -> list[str] | None:
    """Befehl (argv), der die udev-Regel als root einrichtet.

    ``None``, wenn das hier nicht geht: kein Helfer, kein ``pkexec`` oder kein
    Passwort-Dialog (:func:`auth_agent_running`). Dann bleibt der Einzeiler
    fuer die Hand (:func:`manual_command`).
    """
    helper = helper_path()
    pkexec = pkexec_path()
    if helper is None or pkexec is None or not auth_agent_running():
        return None
    return [pkexec, str(helper)]


def auth_agent_running(*, proc_root: str = "/proc") -> bool:
    """Laeuft ein Passwort-Dialog (polkit-Agent)?

    Nur eine Heuristik ueber die Prozessnamen - polkit verraet seine Agenten
    nicht. Sie ist bewusst vorsichtig: ein uebersehener Agent kostet nur den
    Einzeiler, ein ueberschaetzter kostet einen haengenden Dialog.
    """
    for entry in Path(proc_root).glob("[0-9]*"):
        try:
            name = (entry / "comm").read_text().strip()
        except OSError:
            continue
        if name in AGENT_PROCESSES:
            return True
    return False


def reason_no_prompt() -> str:
    """Warum kein Passwort-Dialog gestartet wird (fuer die Meldung)."""
    if helper_path() is None:
        return tr("Der Helfer für die udev-Regel fehlt.")
    if pkexec_path() is None:
        return tr("pkexec (polkit) ist nicht installiert.")
    if not auth_agent_running():
        return tr("Kein Passwort-Dialog (polkit-Agent) vorhanden.")
    return ""


def manual_command() -> str:
    """Der Einzeiler fuer das Terminal (wenn kein Passwort-Dialog verfuegbar ist)."""
    helper = helper_path()
    if helper is None:
        return f"sudo install -m 0644 <regel> {UDEV_RULE_FILE}"
    return f"sudo {helper}"


def describe_failure(returncode: int, stderr: str = "") -> str:
    """Exit-Code/stderr von pkexec in einen Satz uebersetzen, der weiterhilft."""
    text = (stderr or "").strip()
    if returncode == PKEXEC_DISMISSED:
        return tr("Abgebrochen.")
    if returncode == PKEXEC_FAILED:
        if "agent" in text.lower():
            return tr(
                "Kein Passwort-Dialog (polkit-Agent) vorhanden.\n\n"
                "Einmalig im Terminal:\n\n    {command}"
            ).format(command=manual_command())
        return tr("Einrichten fehlgeschlagen:\n\n{error}").format(
            error=text or tr("unbekannter Fehler")
        )
    if text:
        return tr("Einrichten fehlgeschlagen (Code {code}):\n\n{error}").format(
            code=returncode, error=text
        )
    return tr("Einrichten fehlgeschlagen (Code {code}).").format(code=returncode)


def failure_hint(message: str) -> str | None:
    """Ergaenzung fuer Fehlermeldungen, die nach fehlenden Rechten klingen."""
    lowered = (message or "").lower()
    if "permission denied" not in lowered and "access denied" not in lowered:
        return None
    return tr(
        "Fehlende Rechte am USB-Drucker.\n"
        "Im Panel unter „Drucker“: „Zugriff einrichten“."
    )


__all__ = [
    "AGENT_PROCESSES",
    "INSTALLED_HELPER",
    "PKEXEC_DISMISSED",
    "PKEXEC_FAILED",
    "PROJECT_HELPER",
    "UDEV_RULE_FILE",
    "auth_agent_running",
    "describe_failure",
    "failure_hint",
    "helper_path",
    "install_command",
    "manual_command",
    "pkexec_path",
    "reason_no_prompt",
    "rule_installed",
]
