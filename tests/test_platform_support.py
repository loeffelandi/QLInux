"""Plattformfunktionen: Linux und macOS lassen sich im Test setzen."""

from __future__ import annotations

from pathlib import Path

import pytest
from ql_editor import platform_support


@pytest.mark.parametrize(
    ("system", "mac", "udev"),
    [("darwin", True, False), ("linux", False, True), ("win32", False, False)],
)
def test_platform_flags_follow_the_platform(platform, system, mac, udev):
    platform(system)
    assert platform_support.is_mac() is mac
    assert platform_support.supports_udev() is udev


def test_user_data_dir_on_linux_follows_xdg(platform, monkeypatch, tmp_path):
    platform("linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert platform_support.user_data_dir() == tmp_path / "QLInux"


def test_user_data_dir_on_linux_falls_back_to_dot_config(
    platform, monkeypatch, tmp_path
):
    platform("linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert platform_support.user_data_dir() == Path(tmp_path, ".config", "QLInux")


def test_user_data_dir_on_the_mac_is_application_support(
    platform, monkeypatch, tmp_path
):
    platform("darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "ignored"))
    assert platform_support.user_data_dir() == Path(
        tmp_path, "Library", "Application Support", "QLInux"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Strg+S", "⌘S"),
        ("Ctrl+Shift+P", "⇧⌘P"),
        ("Strg+Umschalt+S", "⇧⌘S"),
        ("Strg++", "⌘+"),
        ("Strg +-", "⌘-"),
        ("Strg+0", "⌘0"),
        ("Umschalt+F9", "⇧F9"),
        ("Löschen (Entf)", "Löschen (⌫)"),
        ("Delete (Del)", "Delete (⌫)"),
        ("Strg+Klick: zur Auswahl hinzufügen", "⌘-Klick: zur Auswahl hinzufügen"),
        ("Strg + Mausrad (oder Zoomgeste)", "⌘-Mausrad (oder Zoomgeste)"),
        ("Strg und das Mausrad zoomen", "⌘ und das Mausrad zoomen"),
        ("Strg/Umschalt für mehrere", "⌘/⇧ für mehrere"),
        ("Umschalt-Klick markiert", "⇧-Klick markiert"),
        ("mit gehaltener Umschalttaste", "mit gehaltener ⇧-Taste"),
        ("Shift+arrow keys", "⇧-arrow keys"),
        ("Alternative", "Alternative"),
        ("Esc", "Esc"),
    ],
)
def test_mac_keys_rewrites_shortcuts(text, expected):
    assert platform_support.mac_keys(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Strg+Tab gehoert auf dem Mac dem Programmwechsel (Cmd+Tab).
        ("Strg+Tab", "⌃Tab"),
        ("Ctrl+Shift+Tab", "⌃⇧Tab"),
        ("Strg+F4", "⌘W"),
        ("Ctrl+Y", "⇧⌘Z"),
    ],
)
def test_mac_keys_uses_mac_bindings_for_taken_keys(text, expected):
    assert platform_support.mac_keys(text) == expected
