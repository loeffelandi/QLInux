#!/bin/sh
# Gibt QLInux Zugriff auf angeschlossene Brother-QL-Drucker.
#
# Wird von QLInux ueber pkexec als root gestartet (Passwort-Dialog) und in der
# Paketinstallation zusaetzlich vom postinst aufgerufen. Bewusst ohne Argumente
# und mit festem Inhalt: als root laeuft hier nichts, was von aussen kommt.
#
# Warum TAG+="uaccess": systemd-logind setzt dann einen ACL-Eintrag fuer den
# Benutzer der aktiven Sitzung. Das wirkt sofort (kein Neuanmelden), gilt nach
# dem Umstecken wieder und braucht keine Gruppenmitgliedschaft.
#
# Der Dateiname muss *vor* 73-seat-late.rules sortieren: dort steht
#   TAG=="uaccess", ENV{MAJOR}!="", RUN{builtin}+="uaccess"
# - die Regel liest das Tag also erst aus, wenn es schon gesetzt ist. In einer
# 99-Datei kommt das Tag zu spaet, der ACL-Eintrag entsteht nie (die Regel
# greift dann zwar sichtbar als Tag, aber ohne Wirkung).

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte als root ausfuehren (z. B. ueber pkexec oder sudo)." >&2
    exit 1
fi

RULE_FILE=/etc/udev/rules.d/70-brother-ql.rules
# Alte Ablage (falsche Sortierung) aufraeumen, falls vorhanden.
OLD_RULE_FILE=/etc/udev/rules.d/99-brother-ql.rules

cat > "$RULE_FILE" <<'RULES'
# Brother-QL-Drucker fuer den Benutzer der aktiven Sitzung freigeben (QLInux).
# Hersteller 04f9 = Brother. Betrifft nur diese Geraete.
#
# Kernel-Anschluss (usblp): /dev/usb/lpN
SUBSYSTEM=="usbmisc", KERNEL=="lp*", ATTRS{idVendor}=="04f9", TAG+="uaccess"
# libusb/pyusb: rohes USB-Geraet /dev/bus/usb/BBB/DDD
SUBSYSTEM=="usb", ATTR{idVendor}=="04f9", ENV{DEVTYPE}=="usb_device", TAG+="uaccess"
RULES
chmod 0644 "$RULE_FILE"
rm -f "$OLD_RULE_FILE"

udevadm control --reload-rules
udevadm trigger --subsystem-match=usbmisc --action=add
udevadm trigger --subsystem-match=usb --action=add

echo "udev-Regel eingerichtet: $RULE_FILE"
