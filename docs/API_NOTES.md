# API-Notizen: verifizierte `brother_ql`-Fakten (0.9.4)

Diese Datei dokumentiert die **tatsaechlich installierte** API. Sie wurde vor
dem ersten Code-Schritt verifiziert (siehe `scripts/verify_api.py`). Das ist
bewusst *die einzige Quelle der Wahrheit* - der uebrige Code raet nie.

Reproduzierbar mit:

```bash
source .venv/bin/activate
python scripts/verify_api.py
```

## Umgebung

| Punkt | Wert |
| --- | --- |
| OS | Pop!_OS (Ubuntu 24.04), Python 3.12.3 |
| Projekt-venv | `./.venv` (eigene venv, Web-venv bleibt unangetastet) |
| `brother_ql` | **0.9.4** (gepinnt, nicht upgraden) |
| Pillow | 12.3.0 |
| PySide6 | 6.12.0 |
| Drucker | QL-820NWB, `tcp://192.168.178.62:9100` |
| Auflosung | 300 dpi → `DOTS_PER_MM = 300/25.4 ≈ 11.811` |

> Hinweis: Der Drucker war aus der Build-Umgebung **nicht** per TCP erreichbar
> (`192.168.178.62:9100`). Der Druckpfad ist daher gegen die Bibliothek
> unit-getestet, aber nicht live gegen den Drucker.

### Live-Statusabfrage (Readback)

Port `9100` des QL-820NWB ist offen (TCP-Connect erfolgreich), liefert aber
**keine Statusantwort** auf `ESC i S` (`1B 69 53`) - weder allein noch nach
`ESC @` / Moduswechsel. Das deckt sich mit der Notiz in
`brother_ql.backends.helpers.send`, dass das Netzwerk-Backend kein Readback
unterstuetzt.

Konsequenz fuer die App: die Funktion "Band erkennen" versucht die Abfrage
(`ql_editor.printer.detect_label`) und faellt bei fehlender Antwort **sauber
auf manuelle Auswahl zurueck** (Rueckgabe ``None``, kein Absturz).

## Abweichungen zur Aufgabenbeschreibung (wichtig!)

Die Aufgabenbeschreibung nennt eine aeltere API-Oberflaeche. Real vorhanden ist:

1. **`brother_ql.devicedependent` existiert noch, ist aber deprecated** und nur
   ein Shim ueber die modernen Module `brother_ql.labels` und
   `brother_ql.models`. Beim Import wird eine Deprecation-Warnung geloggt.
   → Unser Code importiert **direkt** aus `brother_ql.labels` /
   `brother_ql.models` (keine Warnung, keine Shimbruchstelle).
2. `from brother_ql.devicedependent import label_specs` **gibt es nicht**.
   Vorhanden sind `label_type_specs`, `label_sizes`, `models`.
3. `brother_ql.__version__` existiert **nicht** → Version via
   `importlib.metadata.version("brother_ql")` (ergibt `0.9.4`).
4. In `label_type_specs[i]` sind `kind` (ein `FormFactor`) und `color`
   (ein `Color`) **Enums**, keine Strings. `restrict_printers` ist eine
   **leere Liste** `[]` (nicht `None`) bei uneingeschraenkten Baendern.

## Verifizierte Signaturen

```python
BrotherQLRaster.__init__(self, model='QL-500')

convert(qlr, images, label, **kwargs)
#   kwargs: cut, dither, compress, red, rotate, dpi_600, hq, threshold
#   threshold-Default = 70 (wird intern invertiert: 100-x)

send(instructions, printer_identifier=None, backend_identifier=None, blocking=True)
#   -> dict: instructions_sent, outcome, printer_state, did_print, ready_for_next_job
#   Netzwerk-Backend hat kein Readback: kehrt nach write() zurueck (outcome='sent')
```

Importe, die real funktionieren:

```python
from brother_ql.raster import BrotherQLRaster
from brother_ql.conversion import convert
from brother_ql.backends.helpers import send
from brother_ql.labels import LabelsManager, FormFactor, Color
from brother_ql.models import ModelsManager
```

## Band-Datenmodell (`label_type_specs` → `LabelSpec`)

| Aufgabenfeld | reales Feld | Beispiel "50" |
| --- | --- | --- |
| `tape_size` | `tape_size` | `(50, 0)` |
| `dots_printable` | `dots_printable` | `(554, 0)` → **Canvas-Breite** |
| `dots_total` | `dots_total` | `(590, 0)` |
| `feed_margin` | `feed_margin` | `35` |
| `right_margin_dots` | `offset_r` / `right_margin_dots` | `12` |
| `kind` | `form_factor` (`FormFactor`) | `ENDLESS` |
| `restrict_printers` | `restricted_to_models` | `[]` (= alle Modelle) |
| `color` | `color` (`Color`) | `BLACK_WHITE` |

Verifizierte druckbare Breiten bei 300 dpi (nur Kontrolle, Code liest dynamisch):

| Band | Dots | | Band | Dots |
| --- | --- | --- | --- | --- |
| 12 mm | 106 | | 62 mm | 696 |
| 29 mm | 306 | | 102 mm | 1164 |
| 38 mm | 413 | | | |
| 50 mm | 554 | | | |
| 54 mm | 590 | | | |

## Kernprinzip (Resize vermeiden)

`convert()` behandelt den Bildpfad je Bandtyp unterschiedlich:

* **Endlos:** ist `im.size[0] != dots_printable[0]`, wird mit `Image.LANCZOS`
  resized **und gewarnt** (`'Need to resize the image...'`). Das ist genau der
  Pfad, der den ANTIALIAS-Patch beruehrt.
* **Die-cut/Rund:** die Bildmasse muessen **exakt** `dots_printable` entsprechen,
  sonst `ValueError("Bad image dimensions: ...")`.

→ **Das gerenderte Bild ist immer exakt `dots_printable[0]` px breit.**
Intern polstert `convert()` auf die Geraetebreite
`number_bytes_per_row * 8 = 720` px (QL-820NWB) und setzt den Offset
`720 - breite - right_margin_dots`. Die Bildhoehe bestimmt die Etikettenlaenge.

## 600-dpi-Modus (`dpi_600`)

`convert()` setzt mit `dpi_600=True` das Bit 6 des Expanded-Mode-Kommandos
(`ESC i K`, `add_expanded_mode`). Laut Raster Command Reference der QL-800-Reihe
ist das Bit 7 (0-basiert Bit 6) **"High resolution printing"**:

> 1: It prints at 600 dpi in the paper length direction
> 0: It prints at 300 dpi in the paper length direction (default)

und im Kapitel "Resolution": *"600 dpi high, 300 dpi wide"* mit
Hoehen-Breiten-Verhaeltnis **2:1**. Quer zur Bandbreite bleibt es also bei
300 dpi; feiner wird nur die Bandlaufrichtung.

Konsequenzen (in `printer.DPI_600_SCALE` / `canvas.render_printable(scale=…)`):

1. Fuer **dieselbe Laenge** braucht das Bild doppelt so viele Zeilen - der
   Drucker setzt die Zeilen mit halbem Abstand. Genau das erwartet `convert()`
   auch: `dots_expected = [el*2 for el in dots_printable]` (die-cut: die Masse
   werden geprueft, endlos: nur die Breite).
2. `convert()` halbiert bei Endlosbaendern die **Breite** des Bildes
   (`im.resize((im.size[0]//2, im.size[1]))`), bevor es auf die Geraetebreite
   polstert. Deshalb rendert QLInux die Designflaeche in **beiden** Achsen mit
   Faktor 2: nach dem Halbieren bleibt exakt die Bandbreite uebrig (kein
   zweiter Resize, keine "Need to resize"-Warnung) und die Zeilenzahl bleibt
   doppelt.
3. Die Vorschau rendert mit demselben Faktor und mittelt das 1-bit-Bild fuer
   das Canvas-Overlay herunter (Box-Filter) - sie zeigt also weiterhin die
   echten Druckdaten.

**Am Geraet geprueft** (QL-820NWB, 50 mm Endlosband, `scripts/print_resolution_test.py`):
dasselbe Design einmal mit `dpi_600=False` und einmal mit `True` gedruckt ergibt
**dieselbe Etikettenlaenge** (Lineal auf dem Etikett: 30,0 mm fertig; 271
Rasterzeilen bei 300 dpi, 542 bei 600 dpi). Der High-Resolution-Modus setzt die
Zeilen also wirklich mit halbem Abstand, statt das Etikett zu verdoppeln - und
die hoehere Aufloesung druckt sauber.

Unterstuetzte Modelle stehen in `printer.DPI_600_MODELS` (QL-800, QL-810W,
QL-820NWB; belegt ueber die Brother-Datenblaetter "High resolution mode:
300 x 600 dpi"). Fuer die uebrigen Modelle der Bibliothek nennen die
Datenblaetter nur den 300-dpi-Druckkopf und keinen High-Resolution-Modus
(QL-500/550/560/570/580N/650TD, QL-700/710W/720NW, QL-1050/1060N - geprueft).
`brother_ql` 0.9.4 fuehrt diese Faehigkeit nicht mit - daher die gepflegte
Liste.

Die Aufloesung ist **keine** Qualitaetsstufe: `printer.resolution_options()`
liefert nur Aufloesungen, und `pquality`/`hq` ("Qualitaet vor Tempo") ist ein
eigener Schalter in der Oberflaeche. Abfragen laesst sich beides nicht - die
Statusantwort (32 Byte) kennt nur Band und Fehler.

## Anschluesse und Status-Rueckkanal

`brother_ql.backends.guess_backend()` leitet das Backend aus der Kennung ab:
`usb://`/`0x…` → `pyusb`, `file://`/`/dev/usb/`/`lp…` → `linux_kernel`,
`tcp://` → `network`. `PrinterConfig.backend` bleibt deshalb standardmaessig
leer und wird in `__post_init__` ueber `printer.backend_for_address()` gesetzt
(ergaenzt nacktes `host:port` als Netzwerk; Unbekanntes faellt auf `network`
zurueck, damit ein Tippfehler nicht still das falsche Backend waehlt).

**Nur USB hat einen Rueckkanal.** `brother_ql` sagt es selbst
(`backends/helpers.py`):

```python
if selected_backend == 'network':
    """ No need to wait for completion. The network backend doesn't support readback. """
    return status
```

Am QL-820NWB nachgemessen: `ESC i S` an `tcp://…:9100` gesendet, 2 s gewartet
→ **keine Antwort** (Port 9100 ist eine reine Druckschnittstelle). Ueber USB
kommen die 32 Statusbytes, aus denen `reader.interpret_response()` Bandtyp,
Bandbreite und -laenge liest - die Grundlage von `printer.detect_label()`.
`printer.READBACK_BACKENDS` haelt das fest (`pyusb`, `linux_kernel`).

Falle bei pyusb: `list_available_devices()` liefert
`usb://0x04f9:0x2015_C5Z315686`, aber der Konstruktor des Backends parst
`int(vendor_product, 16)` nach dem Trennen an `:` - mit angehaengter
Seriennummer also `int("0x2015_C5Z315686", 16)` → `ValueError`. Die Kennung aus
der Liste ist damit **nicht** rueckuebersetzbar; `printer.usb_devices()` kuerzt
sie deshalb auf `usb://0x04f9:0x2015` (Seriennummer weg).

### USB-Kennung → Modell

`brother_ql` 0.9.4 kennt **keine** USB-Kennungen: `ModelSpec` hat kein
`usb_identifiers`, das pyusb-Backend filtert nur auf Hersteller `0x04f9` und
Interface-Klasse 7. Die Zuordnung pflegt deshalb `printer.USB_MODELS`; Quelle
ist die lokale `usb.ids`-Datenbank (`/usr/share/misc/usb.ids`, Paket
`usb.ids`). Nur Modelle der Bibliothek sind aufgefuehrt; der QL-580N fehlt,
weil `usb.ids` fuer ihn keine Kennung nennt, und die Massenspeicher-Modi
(z. B. QL-700 als `0x2049`) fehlen bewusst - dort wird nicht gedruckt.

| Kennung | Modell | Kennung | Modell |
| --- | --- | --- | --- |
| `04f9:2015` | QL-500 | `04f9:202a` | QL-1060N |
| `04f9:2016` | QL-550 | `04f9:2042` | QL-700 |
| `04f9:201b` | QL-650TD | `04f9:2043` | QL-710W |
| `04f9:2020` | QL-1050 | `04f9:2044` | QL-720NW |
| `04f9:2027` | QL-560 | `04f9:209b` | QL-800 |
| `04f9:2028` | QL-570 | `04f9:209c` | QL-810W |
| | | `04f9:209d` | QL-820NWB |

Auch beim Kernel-Geraet (`/dev/usb/lp1`) ist das Modell ableitbar, ohne dass
pyusb oeffnen muss: `usblp` legt `/sys/class/usbmisc/lpN` an, dessen
`device`-Verweis auf das USB-Interface zeigt; eine Ebene darueber liegt das
Geraet mit `idVendor`/`idProduct`. Am QL-700 geprueft:

```console
$ cat /sys/class/usbmisc/lp1/device/../idVendor   # 04f9
$ cat /sys/class/usbmisc/lp1/device/../idProduct  # 2042  -> QL-700
```

`printer.usb_id_for_path()` macht genau das (`sysfs_root` ist fuer Tests
injizierbar); `printer.model_for_address()` vereint beide Wege und liefert fuer
Netzwerkadressen bewusst `None` - welcher Drucker dort antwortet, verraet die
reine TCP-Druckschnittstelle nicht.

### Netzwerkadresse: nur die IP eintippen

`printer.parse_network_address()` macht aus der Nutzereingabe eine
vollstaendige Adresse und `printer.network_host()` die Anzeigeform zurueck:

| Eingabe | Adresse |
| --- | --- |
| `192.168.178.62` | `tcp://192.168.178.62:9100` |
| `192.168.178.62:9101` | `tcp://192.168.178.62:9101` (abweichender Port bleibt) |
| `ql820.local` | `tcp://ql820.local:9100` |
| `[::1]` | `tcp://[::1]:9100` (IPv6 wird nicht am Doppelpunkt zerschnitten) |
| `tcp://192.168.178.62:9100` | unveraendert (Praefixe werden toleriert) |
| leer | leer - der Druckdialog sagt dann, dass die Adresse fehlt |

`printer.NETWORK_PORT` ist der Standardport (9100, RAW/JetDirect) und damit
die einzige Stelle, an der er steht; die Anzeige laesst genau diesen Port weg,
einen abweichenden zeigt sie mit an.

### Netzwerksuche: was der QL-820NWB meldet (gemessen)

`brother_ql` 0.9.4 kann das nicht - `backends/network.py` hat dort nur ein
`raise NotImplementedError()` mit dem Kommentar *„We need some snmp request
sent to 255.255.255.255 here"*. `ql_editor.discovery` macht es selbst, ohne
Zusatzpaket, ueber zwei Wege gleichzeitig:

**1. mDNS** (`_pdl-datastream._tcp.local`, RFC 6763). Die Anfrage geht mit
gesetztem QU-Bit von einem freien Port aus, die Antwort kommt also per Unicast
zurueck - es wird kein Port 5353 belegt und der avahi-Daemon stoert nicht.
Antwort des QL-820NWB (511 Byte, `tests/data/mdns_ql820nwb.bin`):

```
= Brother QL-820NWB  PDL Printer
   hostname = [BRW....local]   address = [192.168.178.62]   port = [9100]
   txt = ["ty=Brother QL-820NWB" "usb_MFG=Brother" "usb_MDL=QL-820NWB"
          "product=(Brother QL-820NWB)" "pdl=application/octet-stream,image/urf"]
```

Das Modell steht in `usb_MDL`/`ty`; PTR (Dienst → Instanz), SRV (Zielhost +
Port), TXT (Modell) und A (Adresse) kommen im selben Paket. Antwortzeit ~1 s.

**2. SNMP-Broadcast** (UDP 161, Community `public`, ein Paket an die
Broadcast-Adresse je Schnittstelle). Der QL-820NWB antwortet (154 Byte,
`tests/data/snmp_ql820nwb.bin`):

| OID | Wert |
| --- | --- |
| `1.3.6.1.2.1.25.3.2.1.3.1` (hrDeviceDescr) | `Brother QL-820NWB` |
| `1.3.6.1.2.1.1.1.0` (sysDescr) | `Brother NC-38002w, Firmware Ver.1.00  ,MID 8V7110` |
| `1.3.6.1.2.1.1.5.0` (sysName) | `BRWBCF4D4334A01` |

Der *Druckername* steht nur in `hrDeviceDescr`; `sysDescr` beschreibt die
Netzwerkkarte. Antwortzeit < 0,1 s.

Beide Wege werden ueber die IP zusammengefuehrt (mDNS zuerst: dessen Name ist
der lesbare), Treffer nach IP sortiert. Aufgenommen wird nur, wer wie ein
Brother-Etikettendrucker aussieht (Hersteller + `QL-`): der EPSON WF-7720
meldet sich am selben Dienst und darf nicht in der Liste stehen
(`tests/data/mdns_epson_wf7720.bin`). Ein unbekanntes QL-Modell bleibt
sichtbar - das Modell waehlt man dann von Hand.

Die Suche endet, wenn nach der letzten Antwort `SEARCH_QUIET_TIME` (0,25 s)
Ruhe war - auf diesem Netz also nach ~0,35 s statt nach dem Zeitlimit (2 s).
`discover_network_printers(cancel=…)` laesst sich beim Schliessen des Fensters
abbrechen.

### Rechtelage am QL-700 (gemessen)

Beide USB-Wege scheitern ohne Systemrechte, und zwar unterschiedlich:

| Adresse | Backend | Fehler | Ursache |
| --- | --- | --- | --- |
| `/dev/usb/lp1` | `linux_kernel` | `[Errno 13] Permission denied` | `crw-rw---- root:lp`, Nutzer nicht in `lp` |
| `usb://0x04f9:0x2042` | `pyusb` | `Access denied (insufficient permissions)` | libusb braucht udev-Regel |

Die Geräteerkennung selbst funktioniert in beiden Faellen (sie oeffnet das
Geraet nicht).

**Beide Wege nach den Rechten am QL-700 nachgemessen** (29 mm endlos): die
Statusabfrage antwortet ueber `/dev/usb/lp1` **und** ueber
`usb://0x04f9:0x2042` (`media_width_mm=29`), und `print_image()` druckt ueber
beide Wege (`did_print: True`, `ready_for_next_job: True`). Der Kernel-Weg war
vorher nur an den fehlenden Rechten gescheitert, nicht am Weg selbst.

Ein Unterschied bleibt, und er entscheidet die Auswahl: `pyusb` haengt beim
Oeffnen den Kernel-Treiber ab, `usblp` bleibt zwar gebunden, aber der
Kernel-Knoten **antwortet fuer ~1-3 s nicht** (Geraet belegt) und danach
wieder:

```
libusb-Status: 29 mm
Kernel direkt danach: keine Antwort
Kernel 3s spaeter   : 29mm endless
```

Deshalb bietet `printer.usb_printers()` pro Drucker nur **einen** Weg an, den
Kernel-Anschluss: er gehoert dem Geraet eindeutig, waehrend `usb://…` immer das
erste Geraet dieser Kennung nimmt. Ohne Kernel-Knoten (`usblp` nicht geladen)
bleibt der libusb-Weg als einziger Eintrag stehen.

**Gewaehlte Abhilfe: eine udev-Regel mit `TAG+="uaccess"`**
(`scripts/install-udev-rule.sh`, Ziel `/etc/udev/rules.d/70-brother-ql.rules`):

```
SUBSYSTEM=="usbmisc", KERNEL=="lp*", ATTRS{idVendor}=="04f9", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="04f9", ENV{DEVTYPE}=="usb_device", TAG+="uaccess"
```

Gruende gegen die naheliegenden Alternativen:

* `usermod -aG lp "$USER"` wirkt erst nach einem **neuen Login** und deckt
  den libusb-Weg nicht ab.
* `MODE="0666"` gibt **allen** Benutzern Schreibzugriff auf das Geraet.
* `TAG+="uaccess"` setzt einen ACL-Eintrag fuer den Benutzer der aktiven
  Sitzung: sofort wirksam, nach dem Umstecken wieder da, kein Login noetig.
  Muster bestaetigt in `/usr/lib/udev/rules.d/60-steam-input.rules`.

**Am QL-700 nachgemessen (und dabei den Fehler gefunden):** mit dem Tag in
einer `99-`Datei steht in `/run/udev/data/c180:1` zwar `G:uaccess`, der
ACL-Eintrag fehlt aber - `getfacl /dev/usb/lp1` zeigt keinen Benutzer. Grund:
`73-seat-late.rules` prueft `TAG=="uaccess"` und laeuft **vor** einer
99-Datei; der `uaccess`-Builtin wird also nie aufgerufen. Mit `70-` (vor 73)
greift es: `getfacl` zeigt `user:andraeas:rw-` auf `/dev/usb/lp1` und
`/dev/bus/usb/001/00x`.

`udevadm info /dev/usb/lp1` zeigt `SUBSYSTEM=usbmisc` (nicht `usb`) - deshalb
braucht der Kernel-Weg eine eigene Zeile; `ATTRS{idVendor}` laeuft dafuer die
Elternkette hoch bis zum Geraet.

### `pkexec` ohne polkit-Agent (gemessen)

Auf diesem System laeuft `polkitd`, aber **kein** Authentifizierungs-Agent
(kein `lxpolkit`, `policykit-1-gnome`, `mate-polkit`; `gnome-shell` gibt es
hier nicht). Gemessen:

| Aufruf | Ergebnis |
| --- | --- |
| `pkexec /bin/true` (kein tty) | haengt, `timeout` greift nach 6 s (Exit 124) |
| `pkexec --disable-internal-agent /bin/true` | haengt ebenfalls (Exit 124) |
| `printf 'falsch\n' \| script -qec "pkexec /bin/true" /dev/null` | kein Prompt sichtbar, laeuft in den Timeout |

`pkexec` **wartet also endlos**, statt abzubrechen - auch mit
`--disable-internal-agent`. Ein haengender Dialog ist die schlechteste
Bedienung, deshalb startet QLInux `pkexec` nur, wenn ein Agent erkannt wird
(`access.auth_agent_running()`, Heuristik ueber die Prozessnamen in `/proc`)
und beendet ihn notfalls nach `PERMISSION_TIMEOUT_MS` (90 s) mit dem
Einzeiler-Dialog als Ausweg. Nebenbei: `QProcess` gibt dem Kind **kein**
kontrollierendes Terminal (`ps -o tty=` → `?`), der interne Text-Agent von
`pkexec` kann hier also ohnehin nicht fragen.

Empfehlung fuer die Paketierung (M4): die Regel im `postinst` einrichten -
dann ist ueberhaupt kein Passwort-Dialog noetig.

## Pillow-10-Patch

Von Haus aus nutzt `conversion.py` Zeile 112 `Image.ANTIALIAS` (in Pillow ≥ 10
entfernt). Der Patch setzt genau dieses eine Vorkommen auf `Image.LANCZOS`.

* `scripts/patch_brother_ql.py` ist **idempotent** und aendert sonst nichts.
* Das PyPI-Sdist 0.9.4 ist bis auf diese eine Zeile **byte-identisch** mit der
  installierten Referenzkopie (verifiziert) → der Patch reproduziert den
  Bestandszustand exakt.

Verifikation nach Installation:

```
Image.LANCZOS vorhanden:   True
Image.ANTIALIAS vorhanden: False
```
