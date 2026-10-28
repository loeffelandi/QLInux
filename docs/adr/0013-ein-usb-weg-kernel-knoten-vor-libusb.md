# 13. Ein USB-Weg, Kernel-Knoten vor libusb

Date: 2026-10-28

## Status

Accepted

Setzt voraus [11. USB-Zugriff über udev uaccess](0011-usb-zugriff-ueber-udev-uaccess.md)

## Kontext

Dieselbe USB-Verbindung lässt sich über `/dev/usb/lp*` und über `usb://` öffnen. pyusb hängt beim Öffnen den Kernel-Treiber ab. Danach antwortet der Kernel-Knoten ein bis drei Sekunden nicht. `usb://` nimmt immer das erste Gerät derselben Produktkennung. Die Kennung aus der Geräteliste trägt eine Seriennummer, die der Backend-Konstruktor nicht parst.

## Entscheidung

Pro Drucker bietet die Liste einen Weg an. Das ist der Kernel-Knoten, solange er existiert. libusb bleibt nur, wenn `usblp` keinen Knoten angelegt hat. Die Kennung wird auf Hersteller und Produkt gekürzt. Das Modell kommt aus `printer.USB_MODELS` oder, am Kernel-Knoten, aus `idVendor`/`idProduct` im sysfs. Eine Netzwerkadresse verrät das Modell nicht.

## Konsequenzen

Zwei gleiche Modelle am selben Rechner sind über libusb nicht unterscheidbar. Der Kernel-Weg ist es. Massenspeicher-Modi derselben Hardware stehen nicht in der Liste, dort wird nicht gedruckt.
