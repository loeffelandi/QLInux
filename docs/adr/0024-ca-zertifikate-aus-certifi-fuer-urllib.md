# 24. CA-Zertifikate aus certifi für urllib

Date: 2026-11-27

## Status

Accepted

Ergänzt [23. Updates aus GitHub-Releases mit SHA-256-Prüfsumme](0023-updates-aus-github-releases-mit-sha-256-pruefsumme.md)

## Kontext

Die Update-Suche spricht HTTPS mit GitHub und muss das Zertifikat prüfen. Die Vorgabe von Python sucht die Zertifikate dort, wo OpenSSL beim Bau der Python-Version hinzeigte. Im gepackten AppImage ist das der Ort der Build-Maschine (Debian und Ubuntu: `/etc/ssl`); auf Fedora oder Arch liegen die Zertifikate woanders. Im macOS-Bündel gibt es gar keine Systemzertifikate für OpenSSL. Qt bringt eine eigene Netzwerkschicht mit, braucht aber zur Laufzeit ein passendes TLS-Backend und wäre neben `urllib` ein zweiter Weg.

## Entscheidung

`urllib` nimmt einen SSL-Kontext mit `certifi.where()`. `certifi` steht in `requirements.txt` gepinnt, PyInstaller packt `cacert.pem` in AppImage und `QLInux.app` (ein Selbsttest `QLINUX_SELFTEST=certifi` prüft das beim Bau). Fehlt `certifi` in einer Entwicklungsumgebung, fällt der Kontext auf die Vorgabe von Python zurück.

## Konsequenzen

Die Update-Suche funktioniert auf jeder Distribution und auf dem Mac, ohne dass der Nutzer Zertifikate einrichtet. Die Zertifikatsliste ist so alt wie das Release; ein sehr altes Programm kann ein neues GitHub-Zertifikat nicht mehr prüfen, dann meldet die Suche von Hand, dass GitHub nicht erreichbar war. `certifi` (MPL-2.0) gehört in die Lizenzliste der README. Eine neue Version von `certifi` kommt wie jede andere Abhängigkeit über Dependabot.
