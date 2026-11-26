# Tasks

## 1. Grundlage und Mac-Testfehler

- [x] 1.1 `ql_editor/platform_support.py` anlegen (`is_mac()`, `current()`, `user_data_dir()`, `supports_udev()`; liest `sys.platform` je Aufruf, Tests setzen `_override`). In `tests/test_platform_support.py` mit `monkeypatch` für `darwin` und `linux` prüfen. Prüfen: der Test läuft grün.
- [x] 1.2 Die Ursache von `test_fitted_label_sits_at_the_top_left` auf macOS finden (-52,4 statt -48) und im Programm oder im Test beheben. Prüfen: der Test ist auf macOS und auf Linux grün.
- [x] 1.3 Die Ursache der beiden `test_touch_pinch_zooms_by_finger_distance` auf macOS finden und beheben, oder die Tests auf macOS begründet überspringen, wenn Qt dort keine synthetischen Touch-Ereignisse auswertet. Die native Zoomgeste bekommt einen eigenen Test mit `QNativeGestureEvent`. Prüfen: die Suite ist auf macOS ohne Fehler (`.venv/bin/python -m pytest -q`).
- [x] 1.4 Die Schrift in `inspector.py` aus `QFontDatabase` wählen, wenn `DejaVu Sans` fehlt. Prüfen: ein Test setzt eine fehlende Schrift voraus und erwartet eine gültige Ersatzschrift.
- [x] 1.5 Die Tests schreiben auf macOS nicht mehr in die echten Einstellungen: `tests/conftest.py` setzt das Standardformat auf Ini unter `XDG_CONFIG_HOME`, `settings.user_settings()` liefert dieselbe Ablage für Tests und Programm, eine autouse-Fixture setzt die Plattform auf Linux (`platform("darwin")` schaltet um). Prüfen: nach der Suite bleibt `~/Library/Preferences/com.qlinux.QLInux.plist` unverändert.
- [x] 1.6 `ImageItem.to_dict` fällt auf PNG zurück, wenn Qt das eigene WebP nicht wieder lesen kann (sehr kleine einfarbige Bilder). Prüfen: der Roundtrip-Test mit einem weißen Bild ist deterministisch grün.

## 2. Tasten in Mac-Schreibweise

- [x] 2.1 In `ql_editor/i18n.py` eine Funktion anlegen, die auf dem Mac `Strg`/`Ctrl`, `Umschalt`/`Shift`, `Alt` und `Entf`/`Del` in ⌘, ⇧, ⌥ und ⌦ umsetzt, Tastenkombinationen zusammenzieht (`⇧⌘S`) und Wörter mit Strich anhängt (`⌘-Klick`), samt Tabelle für `Strg+Tab`, `Strg+Umschalt+Tab`, `Strg+F4`, `Strg+Y`. `tr()` und `paste_hint()` rufen sie auf. Prüfen: neue Tests in `tests/test_i18n.py` für die Tabelle, beide Sprachen und Linux unverändert.
- [x] 2.2 Einen Test ergänzen, der alle Einträge aus `translations.py` auf dem Mac durch `tr()` schickt und verlangt, dass „Strg“ und „Ctrl“ nirgends übrig bleiben (außer in einer Ausnahmeliste). Prüfen: der Test läuft grün, bei einer Absicht-Ausnahme steht sie im Test.
- [x] 2.3 `tests/test_help.py` erweitern: Auf dem Mac zeigt die Hilfe ⌘S und ⌘D und kein „Strg“, unter Linux weiter `Strg+S`. Die Zeile `assert "macOS" not in german` bleibt gültig, weil „macOS“ nicht im Hilfetext steht. Prüfen: der Test läuft grün.
- [x] 2.4 In `ql_editor/app.py` Reiter-Wechsel (`Meta+Tab`, `Meta+Shift+Tab`), „Reiter schließen“ (`Ctrl+W`) und Rücktaste/Entf zum Löschen auf dem Mac setzen. Die Werkzeugleistenknöpfe für die Panels prüfen. Prüfen: Tests in `tests/test_gui.py` lösen die Kürzel mit gesetzter Plattform aus und erwarten den Reiterwechsel; unter Linux gilt `Ctrl+Tab`.
- [x] 2.5 README: Tabelle „Modifier keys on the canvas“ um die Mac-Spalte ergänzen (⌘ statt Ctrl, ⌃Tab für Reiter). Prüfen: die Tabelle nennt jeden Modifier, den ein Mausrad-, Klick- oder Ziehen-Befehl nutzt.

## 3. Finder, Dock und Menüleiste

- [x] 3.1 Einen Eventfilter für `QEvent.FileOpen` und `QEvent.ApplicationActivate` auf der `QApplication` bauen, der Pfade vor dem Fenster sammelt, `_label_paths` anwendet und sie nach `window.show()` öffnet. Eine schon offene Datei wählt ihren Reiter. Nur auf dem Mac installieren. Prüfen: Tests in `tests/test_instance.py` senden `QFileOpenEvent` vor und nach dem Fenster, mit `.qlx`, `.lbx` und einer fremden Endung.
- [x] 3.2 Das Menü „QLInux“ in der Menüleiste anlegen (Über mit `AboutRole`, Beenden mit `QuitRole`); die Einträge fehlen im Hamburger-Menü auf dem Mac. Prüfen: ein Test baut das Fenster mit gesetzter Plattform, erwartet die Aktionen mit Rollen und kein Duplikat im Hamburger-Menü; ⌘Q mit ungespeicherten Änderungen fragt nach.
- [x] 3.3 Dock-Klick: ist das Fenster verkleinert oder verborgen, holt `ApplicationActivate` es zurück. Prüfen: ein Test verkleinert das Fenster, sendet das Ereignis und erwartet ein sichtbares Fenster.
- [x] 3.4 Der Reiterleiste bleibt das Menü-Widget des Fensters: die Menüleiste des Systems ist ein `QMenuBar` ohne Eltern, nicht `self.menuBar()` (das ersetzte die Reiterleiste und löschte sie). Prüfen: ein Test erwartet `menuWidget() is _tab_chrome`; ein echter Start öffnet eine Datei aus dem Finder in einem Reiter.
- [x] 3.5 Die Zoomgeste des Trackpads zoomt um den Zeiger (`LabelCanvas.zoom_at`), weil `AnchorUnderMouse` auf macOS den Zeiger nicht kennt. Das Mausrad bleibt beim Qt-Anker. Prüfen: ein Test sendet `QNativeGestureEvent` und erwartet, dass der Punkt unter dem Zeiger bleibt.
- [x] 3.6 Datei-, Meldungs- und Eingabedialoge sind auf dem Mac Systemdialoge als Sheet am Fenster (`sheet._open_native`, Rückgabe `_NativeSheet` mit `closed`/`close_sheet`). Linux bleibt beim Overlay. Prüfen: Tests in `tests/test_sheet.py` mit `platform("darwin")` für Öffnen, Speichern, Meldung, Rückfrage, Esc und Eingabe; ein echter Start zeigt NSOpenPanel und NSAlert.

## 4. USB und Netzwerk

- [x] 4.1 `media_panel` blendet „Zugriff einrichten“ auf dem Mac aus (`supports_udev()`), `usb_write_access` liefert dort `None`, `access.failure_hint` bekommt den Mac-Text zu „Drucker & Scanner“ ohne Verweis auf den Knopf. Prüfen: Tests in `tests/test_access.py` und `tests/test_gui.py` für Mac und Linux.
- [x] 4.2 `usb_devices` und `preferred_usb_address` auf dem Mac prüfen: `usb://…` ohne Kernel-Knoten, leere Liste bei libusb-Fehler. Prüfen: neue Tests in `tests/test_printer.py` mit gesetzter Plattform und einer pyusb-Attrappe ohne `/dev/usb`.
- [x] 4.3 `interface_broadcast` über `getifaddrs` per `ctypes` auf dem Mac, Linux behält `ioctl`. Prüfen: Tests in `tests/test_discovery.py` mit einer Attrappe für `getifaddrs`, die zwei Schnittstellen und `lo0` liefert; die Zieladressen sind eindeutig.
- [x] 4.4 Die Druckerleiste zeigt bei verweigertem Zugriff auf das lokale Netz einen Hinweis auf „Lokales Netzwerk“; die Suche endet in der üblichen Zeit. Prüfen: ein Test mit einer Suche, die `OSError(EHOSTUNREACH)` meldet, erwartet eine leere Liste und den Hinweis.
- [x] 4.5 `templates.user_dir()` nimmt auf dem Mac `~/Library/Application Support/QLInux/templates/`. `TEMPLATE_DIR_ENV` gewinnt weiter. Prüfen: neue Tests in `tests/test_templates.py` für beide Plattformen.

## 5. Paket

- [x] 5.1 `packaging/ql_editor.spec` um einen `BUNDLE`-Abschnitt für `darwin` erweitern (Bundle-ID `io.github.loeffelandi.QLInux`, Dokumenttypen für `.qlx` und `.lbx`, `NSHighResolutionCapable`, `NSLocalNetworkUsageDescription`, `NSBonjourServices`, `LSMinimumSystemVersion` aus den Mach-O-Dateien des Bundles, libusb in `binaries`). `hidden` und `excludes` bleiben für beide Plattformen. Prüfen: `tests/test_packaging.py` erwartet die neuen Schlüssel in der Spec-Datei.
- [x] 5.2 `packaging/make_icon.py` erzeugt zusätzlich `assets/ql-editor.icns` und Dateitypsymbole für `.qlx`/`.lbx`, ohne das Linux-Ergebnis zu ändern (`.venv/bin/python packaging/make_icon.py`). Prüfen: das Skript läuft auf macOS und Linux durch, die PNGs bleiben bytegleich.
- [x] 5.3 `packaging/build_macos.sh` anlegen: prüft Homebrew-libusb und Architektur, ruft PyInstaller auf, packt `dist/QLInux-<version>-arm64.dmg` mit `hdiutil`. Prüfen: `bash packaging/build_macos.sh` erzeugt das `.dmg`; `otool -L` am Programm zeigt libusb im Bundle; das `.app` startet ohne Homebrew-Pfad (`DYLD_*` leer) und öffnet das Hauptfenster.
- [ ] 5.4 Das `.app` von Hand mit einem Brother-QL abnehmen: Liste, Bandlesen, Druck eines Etiketts per USB, Netzwerksuche mit der Erlaubnis zum lokalen Netz, Doppelklick einer `.qlx`/`.lbx` im Finder, Dock-Klick, ⌘Q mit offenen Änderungen. Prüfen: Ergebnisse stehen im Pull-Request; was ohne Gerät nicht lief, ist als solches vermerkt.

## 6. Doku, Entscheidungen, CI

- [x] 6.1 README: Abschnitt „macOS“ (Download, Gatekeeper-Schritt, libusb im Paket, was auf dem Mac entfällt), Lizenzliste um libusb ergänzen, `docs/hilfe.md` und `docs/tests.md` auf Mac-Besonderheiten prüfen. Prüfen: die README beschreibt den Start so, dass er nach `build_macos.sh` auf einem frischen Konto klappt.
- [x] 6.2 Drei ADRs mit `adr new`: „macOS: unsigniertes `.app` für arm64 mit libusb“ (0020), „Tasten in Mac-Schreibweise am Rand von `tr()`“ (0021) und „Auf dem Mac Systemdialoge statt Sheets“ (0022, ergänzt 0014), auf Deutsch. Prüfen: `docs/adr/` enthält beide Dateien in der nächsten Nummernfolge und der Index stimmt.
- [x] 6.3 `.github/workflows/tests.yml` um einen Job `macos-latest` (arm64, Python 3.12) mit derselben Suite erweitern; kein Lint dort. Der Kommentar zu Python 3.10 auf macOS wird aktualisiert. Der Job baut außerdem das `.app`. Prüfen: der Job läuft grün (erst nach dem Push sichtbar); die Linux-Jobs bleiben unverändert.
- [ ] 6.4 Zum Abschluss `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy` und `.venv/bin/python -m pytest -q` auf macOS und Linux. Prüfen: keine Fehler, jeder Fehler wird gemeldet.

## Workflow follow-up

- Nach der Abnahme mit Gerät `/opsx-archive` für `macos-support`, damit die Specs in `openspec/specs/` zusammengeführt werden.
