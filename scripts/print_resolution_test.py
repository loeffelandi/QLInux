#!/usr/bin/env python
"""Zwei Testetiketten drucken: 300 x 300 dpi und 300 x 600 dpi.

Beide Etiketten tragen **dasselbe Design** und **dieselbe Laenge**, damit man
sie vergleichen und mit dem Lineal nachmessen kann. Das Design ist bewusst
vektorig (Linien, kleine Schrift, QR) - so zeigt sich der Unterschied dort, wo
der High-Resolution-Modus wirkt: feinere Abtastung in Bandlaufrichtung.

Gedruckt wird ueber genau den Pfad der App
(``canvas.render_printable`` -> ``printer.build_raster`` -> ``send``); das
Skript oeffnet kein Fenster.

Aufruf::

    python scripts/print_resolution_test.py --dry-run   # nur rechnen + Bilder
    python scripts/print_resolution_test.py             # beide drucken
    python scripts/print_resolution_test.py --only 600  # nur die feine
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ohne Anzeige (z. B. ueber SSH) rendert Qt offscreen - es geht trotzdem.
if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication
from ql_editor import media
from ql_editor.canvas import LabelCanvas
from ql_editor.items import LineItem, QRItem, RectItem, TextItem
from ql_editor.media import LengthMode, Orientation, dots_to_mm
from ql_editor.preview import DEFAULT_THRESHOLD
from ql_editor.printer import (
    DEFAULT_ADDRESS,
    PrinterConfig,
    PrinterError,
    build_raster,
    print_image,
    resolution_options,
)

#: Abstand der Lineal-Striche (1 mm) in Dots.
MM = media.DOTS_PER_MM


def build_design(canvas: LabelCanvas, title_text: str) -> None:
    """Testdesign auf die Designflaeche setzen (Masse kommen vom Canvas)."""
    rect = canvas.printable_rect()
    width, height = int(rect.width()), int(rect.height())

    # Lineal am linken Rand: 1-mm-Striche, jeder fuenfte laenger, alle 10 mm
    # eine Zahl - damit laesst sich die Etikettenlaenge nachmessen.
    canvas.add_item(LineItem(1.5, 0, 1.5, height, width_px=1.5))
    index = 0
    while index * MM <= height:
        y = index * MM
        long_tick = index % 5 == 0
        canvas.add_item(
            LineItem(1.5, y, 1.5 + (13 if long_tick else 6), y, width_px=1.2)
        )
        if index and index % 10 == 0:
            number = TextItem(str(index), font_pixel_size=11)
            number.setPos(17, max(0.0, y - 6))
            canvas.add_item(number)
        index += 1

    left = 36
    title_size = max(20, int(height * 0.13))
    title = TextItem(f"TEST {title_text}", font_pixel_size=title_size)
    title.setPos(left, 4)
    canvas.add_item(title)

    # Textleiter: dieselbe Zeile in vier Groessen - die kleinste ist der
    # eigentliche Test (bei 600 dpi feiner abgetastet).
    y = 8 + title_size * 1.35
    for size in (22, 17, 13, 10):
        line = TextItem("Auflösungstest 0123456789", font_pixel_size=size)
        line.setPos(left, y)
        canvas.add_item(line)
        y += size * 1.45 + 3

    # Feiner QR-Code mit duennem Rahmen: Module und Linien in einem Bild.
    qr_size = min(76, int(height * 0.34))
    frame = RectItem(QRectF(0, 0, qr_size + 6, qr_size + 6), width_px=1.2)
    frame.setPos(width - qr_size - 12, height - qr_size - 12)
    canvas.add_item(frame)
    qr = QRItem("https://example.org/aufloesung", size_dots=qr_size)
    qr.setPos(width - qr_size - 9, height - qr_size - 9)
    canvas.add_item(qr)

    # Flache Diagonale: die Treppe wird bei 600 dpi halb so grob.
    canvas.add_item(LineItem(left, height - 8, 260, height - 62, width_px=1.5))
    canvas.scene().clearSelection()


def make_canvas(
    label_id: str, model_id: str, length_mm: float
) -> tuple[LabelCanvas, media.LabelSpec, int]:
    """Canvas mit festem Band und fester Gesamtlaenge aufbauen."""
    label = media.get_label(label_id)
    model = media.get_model(model_id)
    length_dots = media.label_length_dots(
        label,
        model,
        auto_length=False,
        fixed_length_mm=length_mm,
        length_mode=LengthMode.FINISHED,
    )
    canvas = LabelCanvas()
    canvas.set_label(label, length_dots, orientation=Orientation.ACROSS)
    return canvas, label, length_dots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--address", default=DEFAULT_ADDRESS, help="Druckeradresse")
    parser.add_argument("--model", default=media.DEFAULT_MODEL, help="Druckermodell")
    parser.add_argument("--label", default="50", help="Band-Kennung (z. B. 50, 62)")
    parser.add_argument(
        "--length-mm", type=float, default=30.0, help="Fertige Etikettenlaenge in mm"
    )
    parser.add_argument(
        "--only",
        choices=("both", "300", "600"),
        default="both",
        help="nur eine Aufloesung drucken",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="nur rechnen, nichts senden"
    )
    parser.add_argument(
        "--preview-dir", default="/tmp/opencode", help="hier die Renderings ablegen"
    )
    parser.add_argument(
        "--pause", type=float, default=6.0, help="Sekunden zwischen den Auftraegen"
    )
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication([])  # noqa: F841 (Rendering braucht sie)

    config = PrinterConfig(model=args.model, address=args.address)
    options = list(resolution_options(config.model))
    if args.only == "300":
        options = [o for o in options if not o.dpi_600]
    elif args.only == "600":
        options = [o for o in options if o.dpi_600]
    if not options:
        print(f"{config.model} kann die gewaehlte Aufloesung nicht.")
        return 2

    probe, label, length_dots = make_canvas(args.label, config.model, args.length_mm)
    print(
        f"Band: {label.display_name} ({label.identifier})  "
        f"Breite {label.width_dots} Dots  "
        f"Inhalt {length_dots} Dots, fertig "
        f"{media.finished_length_mm(label, length_dots):.1f} mm"
    )
    print(
        f"Designflaeche: {int(probe.printable_rect().width())} x "
        f"{int(probe.printable_rect().height())} Dots"
    )
    print(f"Adresse: {config.address}  (Backend {config.backend})")
    print()

    preview_dir = Path(args.preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)

    jobs = []
    for resolution in options:
        # Frischer Canvas je Aufloesung: das Design darf sich nicht stapeln.
        canvas, _, _ = make_canvas(args.label, config.model, args.length_mm)
        build_design(canvas, resolution.label)
        image = canvas.render_printable(scale=resolution.scale)
        rows = image.height
        dpi = 300 * resolution.scale
        length = rows / dpi * 25.4 + dots_to_mm(media.printer_extra_dots(label))
        data = build_raster(
            image,
            label,
            config,
            threshold=DEFAULT_THRESHOLD,
            dither=False,
            hq=True,
            dpi_600=resolution.dpi_600,
        )
        preview = preview_dir / f"test_{dpi}dpi.png"
        image.save(preview)
        print(
            f"{resolution.label:12s} scale={resolution.scale}  "
            f"Bild {image.width}x{image.height}  "
            f"{rows} Rasterzeilen bei {dpi} dpi -> fertig {length:.2f} mm  "
            f"({len(data)} Bytes)  Vorschau: {preview}"
        )
        jobs.append((resolution, image, data))

    print()
    if args.dry_run:
        print("--dry-run: nichts gesendet.")
        return 0

    for index, (resolution, image, data) in enumerate(jobs):
        if index:
            time.sleep(args.pause)
        print(f"Drucke {resolution.label} ...", flush=True)
        try:
            status = print_image(
                image,
                label,
                config,
                threshold=DEFAULT_THRESHOLD,
                dither=False,
                hq=True,
                dpi_600=resolution.dpi_600,
            )
        except PrinterError as exc:
            print(f"  fehlgeschlagen: {exc}")
            return 1
        print(f"  gesendet: outcome={status.get('outcome')}")

    print()
    print("Fertig. Bitte beide Etiketten vergleichen:")
    print("  1. Laenge mit dem Lineal nachmessen - muss bei beiden gleich sein.")
    print("  2. Kleine Schrift und die Diagonale ansehen: die 600-dpi-Variante")
    print("     sollte in Bandlaufrichtung feiner sein.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
