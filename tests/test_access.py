"""Tests fuer :mod:`ql_editor.access`.

Das Modul kuemmert sich um die Rechte fuer USB-Drucker: wo die udev-Regel
liegt, welcher Befehl sie als root einrichtet und wie ein Fehlschlag zu lesen
ist. Hier laeuft **nichts** als root - geprueft wird nur, was das Modul sagt.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from ql_editor import access
from ql_editor.platform import IS_LINUX


def test_the_helper_ships_with_the_project():
    helper = access.helper_path()
    assert helper is not None
    assert helper.name == "install-udev-rule.sh"
    assert helper.is_file()
    assert os.access(helper, os.X_OK), "Helfer muss ausfuehrbar sein"


@pytest.mark.skipif(not IS_LINUX, reason="udev-Helfer nur unter Linux")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="als root wuerde der Helfer wirklich installieren",
)
def test_the_helper_is_valid_shell_and_needs_root():
    helper = access.helper_path()
    assert helper is not None

    # Syntaxpruefung ohne Ausfuehrung.
    assert subprocess.run(["sh", "-n", str(helper)], capture_output=True).returncode == 0

    # Ohne root bricht er ab, ohne etwas zu installieren.
    rule_before = access.rule_installed()
    done = subprocess.run(["sh", str(helper)], capture_output=True, text=True)
    assert done.returncode == 1
    assert "root" in done.stderr
    assert access.rule_installed() == rule_before


def test_the_helper_rule_targets_only_brother_devices():
    helper = access.helper_path()
    assert helper is not None
    text = helper.read_text()

    # Herstellerkennung, beide Anschlusswege und uaccess-ACL.
    assert 'idVendor}=="04f9"' in text
    assert 'SUBSYSTEM=="usbmisc"' in text
    assert 'SUBSYSTEM=="usb"' in text
    assert 'TAG+="uaccess"' in text
    assert access.UDEV_RULE_FILE in text


@pytest.mark.skipif(not IS_LINUX, reason="pkexec nur unter Linux")
def test_install_command_needs_helper_pkexec_and_agent(monkeypatch):
    monkeypatch.setattr(access, "helper_path", lambda: Path("/x/install-udev-rule"))
    monkeypatch.setattr(access, "pkexec_path", lambda: "/usr/bin/pkexec")

    monkeypatch.setattr(access, "auth_agent_running", lambda: False)
    assert access.install_command() is None

    monkeypatch.setattr(access, "auth_agent_running", lambda: True)
    assert access.install_command() == ["/usr/bin/pkexec", "/x/install-udev-rule"]

    monkeypatch.setattr(access, "pkexec_path", lambda: None)
    assert access.install_command() is None

    monkeypatch.setattr(access, "pkexec_path", lambda: "/usr/bin/pkexec")
    monkeypatch.setattr(access, "helper_path", lambda: None)
    assert access.install_command() is None


@pytest.mark.skipif(not IS_LINUX, reason="polkit nur unter Linux")
def test_reason_no_prompt_names_the_missing_piece(monkeypatch):
    monkeypatch.setattr(access, "helper_path", lambda: None)
    assert "Helfer" in access.reason_no_prompt()

    monkeypatch.setattr(access, "helper_path", lambda: Path("/x/helper"))
    monkeypatch.setattr(access, "pkexec_path", lambda: None)
    assert "pkexec" in access.reason_no_prompt()

    monkeypatch.setattr(access, "pkexec_path", lambda: "/usr/bin/pkexec")
    monkeypatch.setattr(access, "auth_agent_running", lambda: False)
    assert "Passwort-Dialog" in access.reason_no_prompt()

    monkeypatch.setattr(access, "auth_agent_running", lambda: True)
    assert access.reason_no_prompt() == ""


@pytest.mark.skipif(not IS_LINUX, reason="/proc-Scan nur unter Linux")
def test_auth_agent_running_reads_the_process_names(tmp_path):
    proc_root = tmp_path / "proc"
    (proc_root / "1").mkdir(parents=True)
    (proc_root / "1" / "comm").write_text("init\n")
    (proc_root / "2").mkdir()
    (proc_root / "2" / "comm").write_text("cosmic-term\n")
    # Ein Prozess ohne lesbares comm darf die Suche nicht abbrechen.
    (proc_root / "3").mkdir()

    assert access.auth_agent_running(proc_root=str(proc_root)) is False

    (proc_root / "4711").mkdir()
    (proc_root / "4711" / "comm").write_text("lxpolkit\n")
    assert access.auth_agent_running(proc_root=str(proc_root)) is True


def test_describe_failure_explains_what_happened():
    assert "Abgebrochen" in access.describe_failure(access.PKEXEC_DISMISSED)

    text = access.describe_failure(
        access.PKEXEC_FAILED, "Error: No authentication agent found"
    )
    assert "Passwort-Dialog" in text
    assert "install-udev-rule.sh" in text

    text = access.describe_failure(access.PKEXEC_FAILED, "boom")
    assert "boom" in text

    # Unbekannter Code ohne Ausgabe nennt wenigstens die Nummer.
    assert "Code 5" in access.describe_failure(5)


def test_failure_hint_only_answers_permission_errors():
    assert access.failure_hint("sent ok") is None
    assert access.failure_hint("") is None

    for message in (
        "[Errno 13] Permission denied: '/dev/usb/lp1'",
        "Access denied (insufficient permissions)",
        "libusb: PERMISSION DENIED",
    ):
        hint = access.failure_hint(message)
        assert hint is not None
        assert "Zugriff einrichten" in hint


def test_non_linux_does_not_offer_a_udev_prompt(monkeypatch):
    monkeypatch.setattr(access, "IS_LINUX", False)
    monkeypatch.setattr(access, "IS_MAC", True)
    monkeypatch.setattr(access, "IS_WINDOWS", False)
    assert access.install_command() is None
    assert access.rule_installed() is False
    assert access.auth_agent_running() is False
    assert "libusb" in access.reason_no_prompt()

    monkeypatch.setattr(access, "IS_MAC", False)
    monkeypatch.setattr(access, "IS_WINDOWS", True)
    assert "Druckerwarteschlange" in access.reason_no_prompt()


def test_manual_command_is_a_copyable_one_liner():
    command = access.manual_command()
    assert command.startswith("sudo ")
    assert "install-udev-rule.sh" in command
