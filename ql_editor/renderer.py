"""Rendering: Qt-Szene -> ``PIL.Image`` in exakter Zielbreite.

Kernprinzip (siehe docs/API_NOTES.md): Das gerenderte Bild ist **immer exakt
``dots_printable[0]`` Pixel breit**. Nur dann ueberspringt
:func:`brother_ql.conversion.convert` den Resize-Pfad (kein Qualitaetsverlust,
keine Warnung) und die Pixel werden 1:1 auf den Druckkopf abgebildet.

Dieses Modul ist bewusst *duenn*: es kennt weder Items noch Drucker. Es
rendert eine beliebige ``QGraphicsScene`` verlustfrei in ein ``PIL.Image``.

Fuer Tests laeuft es headless mit ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

from typing import Protocol

from PIL import Image
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from .i18n import tr
from .media import DPI, LabelSpec

# QImage/QPainter erwarten Dots-per-Meter; 300 dpi = 300 / 0.0254 * 1000.
_DOTS_PER_METER = round(DPI * 1000.0 / 25.4)


class RenderError(RuntimeError):
    """Fehler beim Rendern (falsche Groesse, ungueltige Szene)."""


class RenderableScene(Protocol):
    """Minimal-Interface einer Szene (erfuellt von ``QGraphicsScene``)."""

    def sceneRect(self) -> QRectF:  # noqa: N802  # pragma: no cover - structural typing
        ...

    def render(
        self, painter: QPainter, target: QRectF, source: QRectF
    ) -> None:  # pragma: no cover
        ...


def qimage_to_pil(qimage: QImage) -> Image.Image:
    """Konvertiere ein ``QImage`` verlustfrei in ein ``PIL.Image`` (RGB).

    Beruecksichtigt die Zeilen-Ausrichtung (``bytesPerLine``) korrekt.
    """
    if qimage.isNull():
        raise RenderError(tr("QImage ist leer (isNull)."))
    rgb = qimage.convertToFormat(QImage.Format.Format_RGB888)
    width, height = rgb.width(), rgb.height()
    stride = rgb.bytesPerLine()
    # constBits() liefert einen Puffer der Groesse stride*height; wir kopieren
    # ihn, da die QImage danach zerstoert werden kann.
    buffer = bytes(rgb.constBits())
    expected = stride * height
    if len(buffer) < expected:
        raise RenderError(f"QImage-Puffer zu klein: {len(buffer)} < {expected} Bytes.")
    return Image.frombytes("RGB", (width, height), buffer, "raw", "RGB", stride, 1)


def render_scene_to_image(
    scene: RenderableScene,
    width_dots: int,
    height_dots: int,
    *,
    background: Qt.GlobalColor = Qt.GlobalColor.white,
    antialias: bool = True,
    rotate: bool = False,
    clip_dots: QRectF | None = None,
) -> Image.Image:
    """Rendere ``scene`` in ein ``PIL.Image`` der Groesse ``width_dots`` x ``height_dots``.

    ``clip_dots`` (Bildkoordinaten) schneidet alles ab, was ausserhalb liegt -
    so bleibt hinter dem Rand nichts stehen, auch nicht im Druck.

    Die Szene wird 1:1 abgebildet (``source = sceneRect``, ``target = Bild``).

    ``rotate`` dreht das Ergebnis um 90 Grad **gegen** den Uhrzeigersinn
    (Ausrichtung ``ALONG``: die Designflaeche ist ``Laenge x Bandbreite``, das
    Druckbild muss aber ``Bandbreite x Laenge`` sein). Da die Drehung eine reine
    Pixel-Permutation ist, bleibt jede punktweise Weiterverarbeitung (Threshold,
    Dither) unveraendert - die Druckvorschau zeigt dieselben Pixel, nur in der
    Canvas-Orientierung.
    """
    if width_dots <= 0 or height_dots <= 0:
        raise RenderError(
            tr("Ungueltige Canvas-Groesse: {width} x {height} Dots.").format(
                width=width_dots, height=height_dots
            )
        )

    image = QImage(width_dots, height_dots, QImage.Format.Format_RGB32)
    image.setDotsPerMeterX(_DOTS_PER_METER)
    image.setDotsPerMeterY(_DOTS_PER_METER)
    image.fill(background)

    painter = QPainter(image)
    try:
        if antialias:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        source = scene.sceneRect()
        if source.isNull() or source.width() <= 0 or source.height() <= 0:
            raise RenderError(tr("sceneRect der Szene ist leer oder ungueltig."))
        target = QRectF(0, 0, width_dots, height_dots)
        if clip_dots is not None:
            painter.setClipRect(clip_dots)
        scene.render(painter, target, source)
    finally:
        painter.end()

    result = qimage_to_pil(image)
    if rotate:
        result = result.transpose(Image.Transpose.ROTATE_90)
    return result


def assert_exact_label_width(
    image: Image.Image, label: LabelSpec, *, scale: int = 1
) -> None:
    """Stelle sicher, dass ``image`` exakt ``scale * label.dots_printable[0]`` breit ist.

    ``scale`` ist der Renderfaktor: im 600-dpi-Modus (``scale=2``) erwartet
    ``convert()`` genau die doppelte Breite (``dots_expected``), sonst schaltet
    es seinen eigenen Resize-Pfad ein.

    :raises RenderError: bei Abweichung - die Fehlermeldung nennt Soll und Ist.
    """
    expected = label.width_dots * scale
    if image.width != expected:
        raise RenderError(
            tr(
                "Bildbreite {width} px entspricht nicht der Bandbreite "
                "{expected} px (Band {label!r}, Faktor {scale}). Das "
                "wuerde brother_ql zum Resize zwingen."
            ).format(
                width=image.width,
                expected=expected,
                label=label.identifier,
                scale=scale,
            )
        )


def render_for_label(
    scene: RenderableScene,
    label: LabelSpec,
    canvas_size_dots: tuple[int, int],
    *,
    rotate: bool = False,
    scale: int = 1,
) -> Image.Image:
    """Rendere ``scene`` exakt in der Breite von ``label`` und pruefe das Ergebnis.

    ``canvas_size_dots`` ist die Groesse der **Designflaeche** (Canvas). Mit
    ``rotate=True`` (Ausrichtung ``ALONG``) wird das Ergebnis um 90 Grad gedreht
    und ist danach ``label.width_dots`` breit.

    ``scale`` rendert die Designflaeche in beiden Achsen feiner (600-dpi-Modus:
    ``scale=2``). Da die Szene als Vektor gerendert wird, entsteht dabei echte
    zusaetzliche Aufloesung - nicht ein hochskaliertes Bild.

    Die Breite wird *nicht* angepasst, sondern verifiziert - eine fehlerhafte
    Szene soll auffallen.
    """
    width, height = int(canvas_size_dots[0]), int(canvas_size_dots[1])
    image = render_scene_to_image(scene, width * scale, height * scale, rotate=rotate)
    assert_exact_label_width(image, label, scale=scale)
    return image


__all__ = [
    "RenderError",
    "RenderableScene",
    "assert_exact_label_width",
    "qimage_to_pil",
    "render_for_label",
    "render_scene_to_image",
]
