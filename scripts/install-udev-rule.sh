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

set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Bitte als root ausfuehren (z. B. ueber pkexec oder sudo)." >&2
    exit 1
fi

RULE_FILE=/etc/udev/rules.d/99-brother-ql.rules

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

udevadm control --reload-rules
udevadm trigger --subsystem-match=usbmisc --action=add
udevadm trigger --subsystem-match=usb --action=add

echo "udev-Regel eingerichtet: $RULE_FILE"
