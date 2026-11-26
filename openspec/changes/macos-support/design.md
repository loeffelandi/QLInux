# Design

## Context

Siehe proposal.md, Why. Beobachtet am Stand dieses Repos, auf einem Mac mit Python 3.10 und PySide6 6.12:

- Die Suite läuft bis auf drei Tests durch (822 grün). Qt bildet `ControlModifier` auf ⌘ ab, `QKeySequence.StandardKey` liefert die Mac-Belegung selbst. Kürzel und Mausgesten verhalten sich daher schon richtig; nur ihre **Anzeige** sagt „Strg“.
- Die Zoomgeste des Trackpads kommt als `QNativeGestureEvent` und ist in `canvas.py` schon behandelt.
- `printer.usb_devices()` fragt pyusb und `glob("/dev/usb/lp*")`. Ohne `/dev/usb` bleibt nur `usb://…`. pyusb findet libusb auf diesem Mac über Homebrew. `brother_ql`s pyusb-Backend fängt `NotImplementedError` aus `is_kernel_driver_active` ab, das macOS auslöst.
- `access.py`, `install-udev-rule.sh` und `usb_write_access` sind Linux (`/sys`, `/etc/udev`, `pkexec`). `failure_hint` verweist bei „Access denied“ auf einen Knopf, den es auf dem Mac nicht geben soll.
- `discovery.interface_broadcast` nutzt `ioctl 0x8919` (Linux). Der Wert gehört zur Linux-Header-Datei und passt auf macOS nicht; der Aufruf scheitert still und lässt nur `255.255.255.255` übrig.
- `templates.user_dir()` nimmt `XDG_CONFIG_HOME`/`~/.config`. `QSettings(_ORG, _APP)` landet auf dem Mac schon unter `~/Library/Preferences`.
- Der Start liest Dateien aus `argv`. Der Finder liefert sie aber als `QFileOpenEvent`, auch beim Start des Programms.
- `inspector.py` fordert `DejaVu Sans` an.
- Das AppImage entsteht über `packaging/ql_editor.spec` und `build_appimage.sh`. Das Rezept kennt nur Linux.
- Ohne Mac-Drucker lässt sich der USB-Weg hier nicht bis zum Papier prüfen.

## Goals / Non-Goals

**Goals:**

- Dieselbe Funktionsliste wie unter Linux, mit den im Proposal genannten, plattformbedingten Ausnahmen (kein Rechte-Knopf, kein Kernel-Weg).
- Plattformunterschiede an wenigen, benannten Stellen. Das übrige Programm fragt nicht selbst nach dem Betriebssystem.
- Linux ändert sich nicht: dieselben Texte, Pfade und Tests.

**Non-Goals:**

- Signieren, Notarisieren, Intel-Macs, universal2, Mac-App-Store, Sandbox.
- Ein eigener macOS-USB-Treiber oder ein Weg über CUPS statt libusb.
- Eine Umstellung der Oberfläche auf natives Aqua. Die Fusion-Palette und die Overlay-Sheets für eigene Inhalte (Hilfe, Druck, Auswahl) bleiben; nur Datei-, Meldungs- und Eingabedialoge sind auf dem Mac Systemdialoge (Entscheidung 15).

## Decisions

1. **Ein Modul `ql_editor/platform_support.py` für Plattformfragen.** (Nicht `platform.py`: das verdeckt die Standardbibliothek.) Es bietet `current()`, `is_mac()`, `user_data_dir()`, `supports_udev()` und `mac_keys()`. Die Funktionen lesen `sys.platform` bei jedem Aufruf, damit Tests die Plattform mit `_override` setzen können. Alternative: `sys.platform`-Abfragen an den Stellen. Das verstreut die Fälle und lässt sich schlecht prüfen.

2. **Mac-Tasten am Rand von `tr()`, nicht an jeder Stelle.** Die deutschen Quelltexte und ihre englischen Gegenstücke enthalten Strg-Kürzel in rund sechzig Tooltips, in der Hilfe, in der Befehlssuche und in `paste_hint()`. Auf dem Mac wandelt eine Funktion in `i18n.py` das Ergebnis von `tr()` um: `Strg`/`Ctrl`→⌘, `Umschalt`/`Shift`→⇧, `Alt`→⌥, `Entf`/`Del`→⌫ (Qt löscht auf dem Mac mit beiden Tasten; die Anzeige nennt die Rücktaste). Kombinationen mit einer Taste werden zusammengezogen (`⇧⌘S`), Kombinationen mit einem Wort bekommen einen Strich (`⌘-Klick`, `⌘-Mausrad`). Folgende Fälle stehen in einer Tabelle und gehen vor: `Strg+Tab`→⌃Tab, `Strg+Umschalt+Tab`→⌃⇧Tab, `Strg+F4`→⌘W, `Strg+Y`→⇧⌘Z. Ein Test geht alle Einträge von `translations.py` durch und prüft, dass auf dem Mac weder „Strg“ noch „Ctrl“ übrig bleibt. Alternative: `QKeySequence.toString(NativeText)` an jedem Aufrufer. Das gibt Mac-Symbole, aber unter Linux Qts eigene Sprache statt der Sprache der Oberfläche, und es ändert rund sechzig Stellen.

3. **Tasten, die macOS selbst belegt, bekommen eine Mac-Belegung.** `Ctrl+Tab` meint in Qt auf dem Mac ⌘Tab (Programmwechsel). Darum wechseln die Reiter dort mit `Meta+Tab`, in Qt die Control-Taste. `Ctrl+F4` wird `Ctrl+W`. Die Belegung entsteht an einer Stelle in `app.py` aus `IS_MAC`. Die Befehlssuche und die Hilfe zeigen, was gilt. F9 und ⇧F9 bleiben, ihre Knöpfe in der Werkzeugleiste auch. „Wiederholen“ nimmt auf dem Mac `StandardKey.Redo` (⇧⌘Z).

4. **Finder-Öffnen über einen Eventfilter auf der `QApplication`.** Ein Filter nimmt `QEvent.FileOpen` an, filtert mit `_label_paths` und ruft `_open_from_outside`. Kommt das Ereignis vor dem Fenster, sammelt er die Pfade und öffnet sie nach `window.show()`. `QEvent.ApplicationActivate` ohne sichtbares Fenster holt das Fenster zurück (Dock-Klick). Der Eventfilter wird auf Linux nicht installiert. `instance.forward` bleibt für Starts aus dem Terminal (`open -n`, `python -m ql_editor`); auf dem Mac hält LaunchServices die Instanz sonst schon eindeutig. Alternative: `argv` allein. Der Finder übergibt dort nichts.

5. **Fenster schließen beendet das Programm, auch auf dem Mac.** Das Programm hat ein Fenster mit Reitern. Mac-Programme mit einem Hauptfenster bleiben nach dem Schließen oft laufen, hier würde das aber Reiter ohne Fenster bedeuten und das Öffnen-Verhalten verkomplizieren. `closeEvent` fragt schon nach ungespeicherten Änderungen; ⌘Q läuft über denselben Weg, weil Qt `quit` über `closeEvent` leitet. Das Menü „QLInux“ nimmt `QAction` mit `MenuRole.AboutRole` und `QuitRole`, dann stellt Qt sie an die übliche Stelle.

6. **Menüleiste: eine native Leiste mit dem App-Menü, sonst unverändert.** Die Aktionen für Über und Beenden stehen heute im Hamburger-Menü. Auf dem Mac entstehen sie als Menüleisten-Aktionen mit Rollen und fehlen im Hamburger. Die übrigen Menüs bleiben im Hamburger und in der Befehlssuche, damit die Anordnung auf allen Plattformen dieselbe ist. Alternative: das gesamte Menü auf die Leiste umlegen. Das verändert die Oberfläche für Mac-Nutzer stärker als nötig und lässt zwei Layouts pflegen.

7. **USB nur über libusb, kein neuer Code im Druckweg.** `usb_devices()` und `preferred_usb_address` liefern ohne `/dev/usb/lp*` schon `usb://…`; die Spec hält das jetzt fest. Auf dem Mac bleiben `access.py` und die Rechte-Prüfung inaktiv: `supports_udev()` ist falsch, `media_panel` blendet den Knopf aus, `usb_write_access` liefert `None`. `failure_hint` bekommt auf dem Mac einen eigenen Text. Alternative: ein Kernel-ähnlicher Weg über `/dev/cu.*`. macOS bietet für Brother-QL keinen solchen Knoten.

8. **Broadcast je Schnittstelle über `getifaddrs`.** Auf dem Mac liefert `ifaddrs.ifa_dstaddr` die Broadcast-Adresse, und `ctypes` erreicht `getifaddrs` ohne neue Abhängigkeit. Die Linux-Variante über `ioctl 0x8919` bleibt. Eine gemeinsame Funktion `broadcast_targets()` ruft je nach Plattform eine der beiden. Alternative: `netifaces` hinzufügen. Das ist eine Abhängigkeit für zwei Zeilen Logik.

9. **Eigene Daten über `QStandardPaths`.** `templates.user_dir()` nimmt auf dem Mac `QStandardPaths.AppDataLocation`-Entsprechung `~/Library/Application Support/QLInux`; auf Linux bleibt `XDG_CONFIG_HOME`. `TEMPLATE_DIR_ENV` gewinnt weiterhin. Alternative: auch Linux auf `QStandardPaths` umstellen. Das würde `~/.local/share` statt `~/.config` bedeuten und bestehende Vorlagen verstecken.

10. **Paket: PyInstaller `BUNDLE`, dann `hdiutil`.** `ql_editor.spec` bekommt unter `sys.platform == "darwin"` einen `BUNDLE`-Abschnitt. `packaging/build_macos.sh` ruft PyInstaller auf, erzeugt `assets/ql-editor.icns` aus den PNG-Größen mit `iconutil` und packt `dist/QLInux-<version>-arm64.dmg`. Die Info.plist kommt aus der Spec: Bundle-ID `io.github.loeffelandi.QLInux`, `CFBundleDocumentTypes` für `.qlx` und `.lbx` mit je einer exportierten Typkennung, `NSHighResolutionCapable`, `NSLocalNetworkUsageDescription` und `NSBonjourServices` mit `_pdl-datastream._tcp`, `LSMinimumSystemVersion` aus den Mach-O-Dateien des Bundles. PyInstaller legt auf arm64 selbst eine Ad-hoc-Signatur an, ohne die der Kernel das Programm nicht startet. libusb kommt über `binaries` im Spec ins Bundle; der Hook für `usb` findet die Bibliothek nur, wenn Homebrew-libusb auf dem Build-Rechner liegt, das Skript prüft das vorher und bricht sonst ab. Alternative: `py2app`. Es ist ein zweites Rezept neben PyInstaller.

11. **Test-Abdeckung ohne Mac-Runner: Plattform setzen.** Alle Plattformfunktionen lesen `sys.platform` zur Laufzeit, Tests setzen sie mit `monkeypatch`. Die Hilfe wird so für beide Fälle geprüft. Zusätzlich läuft die Suite auf einem macOS-arm64-Job (`macos-latest`) neben den Linux-Jobs.

12. **Die drei Mac-Fehler werden vor der Arbeit am Rest geklärt.** `test_fitted_label_sits_at_the_top_left` liefert -52,4 statt -48; die Abweichung entsteht vermutlich in der Breite von Rahmen oder Scrollleiste im macOS-Stil. Die beiden Pinch-Tests stützen sich auf `QTest.touchEvent`; vermutlich verarbeitet Qt auf macOS synthetische Touch-Ereignisse nicht. Erst die Ursache entscheidet, ob das Programm oder der Test falsch ist.

13. **Die Schrift im Inspektor folgt `QFontDatabase`.** `inspector.py` fragt `DejaVu Sans`. Auf dem Mac fehlt sie. Ein Ersatz aus `QFontDatabase.systemFont` hält Größe und Zeilenhöhe, ohne die Ausgabe unter Linux zu ändern.

14. **ADR und README.** Die Entscheidungen zu Paket (1, 10), USB (7) und Tasten (2, 3) werden zwei ADRs: „macOS: unsigniertes `.app` für arm64 mit libusb“ und „Tasten in Mac-Schreibweise am Rand von `tr()`“. Die README bekommt den Abschnitt „macOS“ mit Installation, Gatekeeper-Schritt und Hinweis auf libusb, und die Tabelle „Modifier keys on the canvas“ die Mac-Spalte. Neue deutsche Texte laufen durch `tr()`.

## Risks / Trade-offs

- [USB-Druck ohne Drucker am Mac nicht prüfbar] → Die Tasks halten fest, welche Schritte nur mit Gerät laufen (Liste, Band lesen, Druck, Hinweis bei gesperrtem Drucker). Bis dahin gilt der Weg als nicht abgenommen.
- [macOS belegt den Drucker über CUPS, `set_configuration` scheitert mit „Access denied“] → Die Meldung nennt den Weg über „Drucker & Scanner“ (Spec `usb-access`). Ob ein Auslesen ohne Entfernen des Systemdruckers geht, zeigt erst der Test mit Gerät.
- [Mac-Tasten als Textersetzung greifen eine Stelle zu viel] → Der Test über alle Übersetzungen fängt fehlende Fälle, und die Tabelle der Sonderfälle bleibt klein. Ein Treffer in Fließtext („Strg“ als Wort) wird in der Tabelle geführt.
- [Lokales Netz: macOS zeigt die Erlaubnis nur einmal; eine Ablehnung bleibt] → Die Druckerleiste nennt die Systemeinstellung. Ob UDP-Broadcast und mDNS ohne `NSBonjourServices`-Eintrag trotzdem gehen, wird mit einem Drucker im Netz geprüft.
- [Nicht signiert: Gatekeeper warnt, Quarantäne-Attribut verhindert den Start aus Downloads] → Die README beschreibt „Rechtsklick, Öffnen“ und den Befehl `xattr -dr com.apple.quarantine`. Signieren bleibt ein eigener, späterer Change.
- [PyInstaller nimmt libusb nicht mit] → Das Skript sucht die Bibliothek vorher und prüft das fertige `.app` mit `otool -L` und einem Start im Offscreen-Modus.
- [Der macOS-CI-Job ist langsamer und fällt aus anderen Gründen] → Er läuft als eigener Job mit `fail-fast: false`; Lint bleibt auf Linux.

## Migration Plan

Keine Datenwanderung. Einstellungen und `.qlx` bleiben austauschbar. Unter Linux ändert sich nichts. Rückbau heißt, `platform.py`, die macOS-Teile im Spec-Rezept, das Skript und den CI-Job zu entfernen.

## Open Questions

- Mindestversion von macOS: bestimmt das neueste `minos` der Mach-O-Dateien im Bundle (PySide6-Bindungen, Qt, libusb). Der Wert gehört in `LSMinimumSystemVersion` und wird beim Bauen mit `otool` gelesen; ein auf neuerem macOS gebautes libusb hebt ihn an. Er ändert weder Specs noch Aufgaben.

15. **Systemdialoge auf dem Mac, Overlay nur für eigene Inhalte.** Die Overlay-Sheets entstanden für Wayland (ADR 0014); auf dem Mac gibt es echte Sheets. `sheet._open_sheet` leitet dort jeden `QDialog` (`QFileDialog`, `QMessageBox`, `QInputDialog`) an `_open_native`: Elternfenster, `WindowModal`, `open()`. Qt nimmt dann `NSOpenPanel`, `NSSavePanel` und `NSAlert`. Der Rückgabewert `_NativeSheet` hat `closed`, `close_sheet()` und `isVisible()` wie `Sheet`, sodass die Aufrufer unverändert bleiben; `closed` kommt erst aus `close_sheet()`, weil die Aufrufer zuerst über `finished` entscheiden. NSAlert hat keine Titelleiste: der Titel wird zur Überschrift, der Text zum Erläuterungstext. `show_widget` bleibt ein Overlay. Alternative: überall Overlay. Das ist auf dem Mac fremd (kein Finder-Seitenleiste, keine Tags, kein iCloud-Ordner) und macht den Dateidialog zur größten Abweichung von dem, was ein Mac-Nutzer erwartet. Ein ADR ergänzt ADR 0014.

16. **Die Zoomgeste setzt den Anker selbst.** `AnchorUnderMouse` kennt auf macOS bei `QNativeGestureEvent` den Zeiger nicht (der Ausschnitt sprang in die obere linke Ecke). `LabelCanvas.zoom_at(factor, anchor)` nutzt `apply_pinch` mit dem Zeiger aus `globalPosition()`. Das Mausrad zoomt weiter mit dem Qt-Anker, der dort stimmt.

17. **Die Menüleiste des Systems ist ein eigenes `QMenuBar` ohne Eltern.** `self.menuBar()` ersetzt das Menü-Widget des Fensters, hier die Reiterleiste, und löscht sie. Ein `QMenuBar` ohne Eltern ist auf dem Mac die Leiste des Systems und lässt die Reiterleiste stehen.
