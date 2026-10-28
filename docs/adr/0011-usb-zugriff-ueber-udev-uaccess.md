# 11. USB-Zugriff über udev uaccess

Date: 2026-10-28

## Status

Accepted

Wird vorausgesetzt von [13. Ein USB-Weg, Kernel-Knoten vor libusb](0013-ein-usb-weg-kernel-knoten-vor-libusb.md)

## Kontext

Status und Druck über USB brauchen Schreibrecht auf den Geräteknoten. Die Gruppe `lp` wirkt erst nach einem neuen Login und deckt libusb nicht ab. `MODE="0666"` öffnet das Gerät für jeden Benutzer. Eine Regel in `99-` kommt nach `73-seat-late.rules`; der Tag `uaccess` setzt dann keine ACL. `pkexec` ohne Authentifizierungs-Agent wartet endlos, statt abzubrechen.

## Entscheidung

`scripts/install-udev-rule.sh` legt `/etc/udev/rules.d/70-brother-ql.rules` an. Zwei Zeilen setzen `TAG+="uaccess"` für Hersteller `04f9`: eine für `usbmisc`/`lp*`, eine für das USB-Gerät. Die `70-` steht vor der Seat-Regel, damit die ACL für die aktive Sitzung entsteht.

QLInux bietet „Zugriff einrichten“ an. `pkexec` startet nur, wenn ein Agent läuft. Sonst bleibt der Terminal-Einzeiler. Der Prozess wird nach 90 Sekunden abgebrochen.

## Konsequenzen

Die Regel gilt sofort und nach dem Umstecken wieder, ohne neuen Login und ohne das Gerät für alle zu öffnen. Einmalig ist ein Passwort nötig, wenn ein Agent da ist. Ohne Agent gibt es keinen hängenden Dialog.
