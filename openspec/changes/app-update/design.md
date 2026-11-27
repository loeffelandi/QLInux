# Design

## Context

Siehe proposal.md, Why. QLInux hat heute keinen Code, der das Netz im Internet anfasst: `discovery.py` spricht nur das lokale Netz, `about.py` kennt nur eine Adresse als Link. Das ist die erste Verbindung zu einem Dritten.

Es gibt zwei Auslieferungen. Das AppImage (Linux, x86_64 und aarch64) setzt beim Start `APPIMAGE` auf den Pfad der Datei und trägt `gh-releases-zsync` als Update-Info für externe Werkzeuge wie GearLever (`packaging/build_appimage.sh`). `QLInux.app` (macOS, arm64) liegt als ad hoc signiertes Bündel in einer `.dmg` (ADR 0020, Branch `feature/macos-support`). Beide Dateien hängen an derselben Release: `appimage.yml` und `macos.yml` laden sie erst nach der Veröffentlichung hoch. Ein Nutzer kann die Release also sehen, bevor seine Datei da ist.

Dialoge sind Sheets im Hauptfenster (ADR 0014), auf dem Mac Systemdialoge (ADR 0022). Einstellungen liegen in `AppSettings` (`QSettings`). Das Beenden läuft über `closeEvent`, das nach ungespeicherten Änderungen fragt.

## Goals / Non-Goals

**Goals:**

- Beim Start nachsehen, ohne den Start zu verzögern oder zu stören.
- Das Update ohne Handgriff einspielen und die installierte Version dabei nie halb kaputt hinterlassen.
- Nur Dateien einspielen, deren Prüfsumme GitHub für die Release nennt.

**Non-Goals:**

- Kein Code-Signing, keine Notarisierung. Die Apps bleiben unsigniert (ADR 0020); die Prüfsumme schützt vor beschädigten Dateien, nicht vor einem gekaperten GitHub-Konto.
- Keine Delta-Updates. Das AppImage behält seine zsync-Datei für GearLever und `AppImageUpdate`, QLInux selbst lädt die ganze Datei (rund 50–70 MB).
- Kein Zurückrollen auf die Vorversion nach einem erfolgreichen Update.
- Keine Update-Kanäle, keine Vorabversionen, kein Windows.
- Quelltext-, `.deb`- und Paketmanager-Installationen aktualisieren sich nicht selbst.

## Decisions

1. **Quelle ist die GitHub-REST-Schnittstelle `GET /repos/loeffelandi/QLInux/releases/latest`.** Sie liefert nur veröffentlichte Releases ohne Entwürfe und Vorabversionen, dazu je Datei `browser_download_url` und `digest` (`sha256:…`). Ohne Anmeldung gilt ein Limit von 60 Anfragen je Stunde und Adresse; bei höchstens einer Suche am Tag und gelegentlichem Handsuchen reicht das. Alternative: der Atom-Feed der Releases. Er kennt weder Dateien noch Prüfsummen.

2. **Nur gepackte Programme.** Ein Programm gilt als aktualisierbar, wenn `APPIMAGE` auf eine vorhandene Datei zeigt oder `sys.frozen` gesetzt ist und das Bündel auf macOS `…/QLInux.app` heißt. Sonst fehlen Suche, Menüeintrag und Schalter. Alternative: auch den Quelltext hinweisen lassen. Ein Entwickler holt Updates per `git pull`, und ein Hinweis ohne Handlung wäre Lärm.

3. **Zeitpunkt und Grenzen.** Der Hintergrundlauf startet, nachdem das Fenster steht. Er ist ein eigener Thread mit 5 Sekunden Zeitlimit und meldet über ein Qt-Signal zurück. `updates/last_check` bekommt den Zeitstempel nur nach einer vollständigen Antwort mit passender Datei; fehlt die Datei noch, fragt der nächste Start erneut (Entscheidung 5). Die Suche von Hand ignoriert Sperre, Start-Schalter und übersprungene Version. `QLINUX_NO_UPDATE_CHECK=1` schaltet die Suche beim Start ab (für Tests und CI), nicht die von Hand.

4. **Versionsvergleich.** Der Tag `v<a>.<b>.<c>` wird als Zahlentupel gelesen und mit `ql_editor.__version__` verglichen; alles andere zählt als „kein Update“. Alternative: `packaging.version`. Eine weitere Abhängigkeit für ein einfaches Format.

5. **Dateivertrag.** Gesucht werden `QLInux-<version>-<arch>.AppImage` mit `arch` aus `platform.machine()` (`x86_64`, `aarch64`) und `QLInux-<version>-arm64.dmg`. Fehlt die Datei oder ihr `digest`, ist das kein Update und kein Fehler: die Workflows laden nach der Veröffentlichung hoch, und der Nutzer soll nie ein halbes Release angeboten bekommen.

6. **Prüfsumme statt Signatur.** SHA-256 wird beim Laden mitgerechnet und gegen `digest` der Release verglichen. Fehlt `digest` oder stimmt die Summe nicht, bricht das Update ab. Übertragung nur über HTTPS (Weiterleitungen auf `http` werden abgelehnt), Zertifikate werden geprüft. Das schützt vor beschädigten und abgeschnittenen Dateien und vor einem Mittelsmann im Netz. Es schützt nicht vor einem Angreifer mit Schreibrecht auf die Release; das ist ein Non-Goal (siehe oben). Alternative: eine eigene Signatur der Releases, etwa mit Minisign. Sie brauchte einen Schlüssel und eine zweite Datei je Release, und der erste Schritt wäre ohnehin der Schlüssel in der App.

7. **CA-Zertifikate aus `certifi`.** Der HTTPS-Kontext nimmt `certifi.where()`. Die Vorgabe von Python sucht im Bündel unter Linux am Ort der Build-Maschine (Debian/Ubuntu) und unter macOS gar keine Zertifikate. Alternativen: `QNetworkAccessManager` (braucht ein passendes TLS-Backend zur Laufzeit und eine zweite Netzwerkschicht neben `urllib`) oder die Systemzertifikate (fehlen im macOS-Bündel). `certifi` wird in `requirements.txt` gepinnt und in die Spec aufgenommen.

8. **Ersetzen des AppImage.** Die neue Datei wird im selben Ordner wie das laufende AppImage unter einem Punktnamen angelegt, mit den Rechten der alten (plus Ausführen), und dann mit `os.replace` an den Pfad aus `APPIMAGE` gesetzt. Das ist atomar und geht auch, solange das alte AppImage läuft: sein Mount hält die alte Datei offen. Ein Ordner ohne Schreibrecht ergibt eine Meldung mit dem Pfad, ohne Änderung. Alternative: in einen anderen Ordner schreiben und der Nutzer verschiebt. Das ist das Handarbeiten, das wegfallen soll.

9. **Ersetzen von `QLInux.app`.** Die `.dmg` wird mit `hdiutil attach -nobrowse -readonly` an einen eigenen Mountpunkt gehängt, die App mit `ditto` neben die laufende kopiert (Punktname im selben Ordner, selbes Dateisystem), `Info.plist` auf die erwartete Version und `codesign --verify --deep` geprüft. Dann wird die laufende App umbenannt, die neue an ihren Platz gesetzt und die alte gelöscht; schlägt der zweite Schritt fehl, wird zurückbenannt. `hdiutil detach` läuft immer. Die Datei kommt aus Python und nicht aus einem Browser, trägt also kein Quarantäne-Attribut und löst keine Gatekeeper-Abfrage aus. Alternative: den Tausch einem Hilfsprozess überlassen, der nach dem Beenden läuft. Das spart nichts: die laufende App kann ihr eigenes Bündel ersetzen, solange sie danach nur noch beendet wird, und Fehler zeigt sie dem Nutzer noch im Sheet an.

10. **Neustart über den normalen Beenden-Weg.** Ein losgelöster Hilfsprozess (`sh -c`) wartet, bis die laufende PID verschwunden ist, und startet dann die neue Datei mit den gespeicherten Pfaden der offenen Reiter als Argumente. Dann ist der Socket der Einzelinstanz (ADR 0018) frei. QLInux ruft dafür `close()` auf; die Frage nach ungespeicherten Änderungen kommt aus `closeEvent`. Bricht der Nutzer ab, startet der Hilfsprozess nicht, und das Update bleibt für den nächsten Start. Alternative: `os.execv` im selben Prozess. Das umgeht `closeEvent`, den Socket und das Aufräumen der Threads.

11. **Anzeige und Einstellungen.** Hinweis, Fortschritt, Fehler und Neustartfrage sind Sheets über die bestehenden Helfer (auf dem Mac Systemdialoge). Neue Texte laufen durch `tr()` und stehen in `translations.py`. `updates/check_on_start` (Vorgabe an), `updates/last_check` und `updates/skipped_version` liegen in `AppSettings`. Menüeintrag und Schalter stehen im Hamburger-Menü und in der Befehlspalette; der Schalter ist eine abhakbare Aktion wie die Sprachwahl.

12. **Testbarkeit.** `updater.py` bekommt die Basisadresse als Modulvariable. Die Tests starten einen lokalen HTTP-Server (Release-JSON, Datei, falsche Prüfsumme, Abbruch mittendrin) und rufen die Ersetz-Schritte mit temporären Ordnern auf. Auf macOS-CI läuft der echte `hdiutil`-Pfad mit einer kleinen Test-`.dmg`.

## Risks / Trade-offs

- [Die Prüfsumme kommt vom selben Ort wie die Datei] → Dokumentiert; ein Kaperer der Release kann beides ändern. Eine Signatur wäre ein eigener Schritt (Non-Goal).
- [Die macOS-App ist ad hoc signiert, jede Version hat eine andere Signatur] → macOS fragt nach einem Update erneut nach dem Zugriff aufs lokale Netz und nach der Firewall. README und Hinweis nach dem Update sagen das. USB ist nicht betroffen.
- [Release veröffentlicht, Datei fehlt noch] → Entscheidung 5: kein Hinweis, nächster Start fragt erneut.
- [GitHub-Limit oder GitHub nicht erreichbar] → Still beim Start, Meldung bei der Suche von Hand.
- [Ein Ordner wie `/Applications` oder ein Systemverzeichnis ist nicht beschreibbar] → Meldung mit Pfad, keine Änderung, kein Umweg über Administratorrechte.
- [Ein Absturz zwischen den Umbenennungen der `.app`] → Der zweite Schritt ist ein einzelnes Umbenennen im selben Ordner; der Startpfad prüft beim nächsten Start, ob ein Rest (`.QLInux-update`, `.old`) liegt, und räumt ihn auf.
- [Die laufende Instanz liest nach dem Austausch von `QLInux.app` Dateien der neuen Version] → Der Neustart ist die Vorgabe und wird sofort angeboten; wer „Später“ wählt, arbeitet bis zum Schließen weiter, und Qt-Plugins werden beim Start geladen.
- [Unter Wayland kann der Compositor das Anheben des neuen Fensters ignorieren] → Wie bei ADR 0018, kein zweiter Mechanismus.

## Migration Plan

Das erste Programm mit dieser Funktion kommt von Hand (Release laden), danach aktualisiert es sich selbst. Versionen davor kennen die Funktion nicht und bekommen den Hinweis nicht. Zurück: Funktion abschalten über den Schalter oder `QLINUX_NO_UPDATE_CHECK=1`; das Entfernen des Moduls ändert keine Datei des Nutzers.
