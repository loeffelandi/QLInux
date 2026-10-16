#!/usr/bin/env python3
"""Kommandozeilen-Test des Druckpfads (headless, ohne GUI).

Erzeugt ein einfaches Etikett (Text + optional QR-Code), rendert es in exakter
Bandbreite, zeigt die monochrome Vorschau und druckt es optional.

Beispiele:

    # Nur rechnen + Vorschau speichern (kein Drucker noetig):
    python scripts/print_test.py --label 50 --length-mm 40 --text "Hallo QL" \
        --dry-run --save /tmp/opencode/ql_dryrun.png

    # Wirklich drucken:
    python scripts/print_test.py --address tcp://192.168.178.62:9100 \
        --label 50 --length-mm 40 --text "Hallo QL" --qr "https://example.org"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Headless-Rendering: kein echtes Display noetig.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsPixmapItem, QGraphicsScene, QGraphicsTextItem

from ql_editor import media, preview
from ql_editor.printer import PrinterConfig, PrinterError, build_raster, print_image
from ql_editor.renderer import render_for_label


def build_scene(label, height_dots: int, text: str, qr_data: str | None,
                font_size: int, margins_mm: float):
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, label.width_dots, height_dots))

    bg = QGraphicsPixmapItem()
    pm = QPixmap(label.width_dots, height_dots)
    pm.fill(QColor("white"))
    bg.setPixmap(pm)
    scene.addItem(bg)

    margin = media.mm_to_dots(margins_mm)

    qr_width = 0
    if qr_data:
        import qrcode

        qr = qrcode.QRCode(border=1, box_size=10)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_path = Path("/tmp/opencode/_ql_qr.png")
        qr_path.parent.mkdir(parents=True, exist_ok=True)
        qr_img.save(qr_path)
        item = QGraphicsPixmapItem(QPixmap(str(qr_path)))
        # QR nicht groesser als die Etikettenhoehe und hoechstens ~45 % der Breite,
        # damit links noch Platz fuer Text bleibt.
        size = min(height_dots - 2 * margin, int(label.width_dots * 0.45))
        if size > 0:
            item.setPixmap(item.pixmap().scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        qr_width = item.pixmap().width()
        item.setPos(label.width_dots - margin - qr_width, margin)
        scene.addItem(item)

    text_item = QGraphicsTextItem(text)
    font = QFont("Sans")
    font.setPixelSize(font_size)
    text_item.setFont(font)
    text_item.setDefaultTextColor(QColor("black"))
    text_width = max(1, label.width_dots - 2 * margin - qr_width - (margin if qr_data else 0))
    text_item.setTextWidth(text_width)
    text_item.setPos(margin, margin)
    scene.addItem(text_item)
    return scene


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="QLInux Druckpfad-Test")
    parser.add_argument("--model", default=media.DEFAULT_MODEL)
    parser.add_argument("--address", default="tcp://192.168.178.62:9100")
    parser.add_argument("--backend", default="network")
    parser.add_argument("--label", default="50")
    parser.add_argument("--length-mm", type=float, default=40.0)
    parser.add_argument(
        "--length-mode", choices=[m.value for m in media.LengthMode],
        default=media.LengthMode.FINISHED.value,
        help="finished = Gesamtlaenge inkl. Druckerrand (Default), content = nur Inhalt",
    )
    parser.add_argument("--auto", action="store_true", help="Auto-Laenge (Ignore --length-mm)")
    parser.add_argument("--text", default="QLInux")
    parser.add_argument("--qr", default=None, help="QR-Code-Inhalt")
    parser.add_argument("--font-size", type=int, default=48)
    parser.add_argument("--margin-mm", type=float, default=1.0)
    parser.add_argument("--threshold", type=int, default=70)
    parser.add_argument("--dither", action="store_true")
    parser.add_argument("--red", action="store_true")
    parser.add_argument("--no-cut", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="nicht drucken")
    parser.add_argument("--save", type=str, default=None, help="Vorschau-PNG speichern")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])

    label = media.get_label(args.label)
    model = media.get_model(args.model)
    length_mode = media.LengthMode(args.length_mode)
    width, height = media.canvas_size_dots(
        label, model, auto_length=args.auto, fixed_length_mm=args.length_mm,
        length_mode=length_mode,
    )
    print(f"Band:   {label.identifier}  ({label.display_name})")
    print(f"Modus:  Laenge = {'Gesamt (inkl. Druckerrand)' if length_mode is media.LengthMode.FINISHED else 'Inhalt'}")
    print(f"Canvas: {width} x {height} px  ({media.dots_to_mm(width):.1f} x {media.dots_to_mm(height):.1f} mm Inhalt)")
    total_mm = media.finished_length_mm(label, height) if label.is_endless else media.dots_to_mm(height)
    print(f"Gesamt: ~{total_mm:.1f} mm fertiges Etikett")

    scene = build_scene(label, height, args.text, args.qr, args.font_size, args.margin_mm)
    image = render_for_label(scene, label, height)
    print(f"Render: {image.size[0]} x {image.size[1]} px (erwartet {label.width_dots} breit)")

    options = preview.PreviewOptions(threshold=args.threshold, dither=args.dither)
    visual = preview.binarize(image, options)
    print(f"Tinte:  {preview.ink_ratio(image, options) * 100:.1f} %")

    if args.save:
        visual.convert("L").save(args.save)
        print(f"Vorschau gespeichert: {args.save}")

    config = PrinterConfig(model=args.model, address=args.address, backend=args.backend)
    try:
        data = build_raster(
            image, label, config,
            threshold=args.threshold, dither=args.dither,
            red=args.red, cut=not args.no_cut,
        )
        print(f"Raster: {len(data)} Bytes")
        if args.dry_run:
            print("Dry-run: es wurde NICHT gedruckt.")
            return 0
        status = print_image(
            image, label, config,
            threshold=args.threshold, dither=args.dither,
            red=args.red, cut=not args.no_cut,
        )
        print(f"Status: {status}")
        return 0
    except PrinterError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
