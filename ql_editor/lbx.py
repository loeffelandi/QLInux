"""Brother-P-touch-Dateien (``.lbx``) lesen.

Eine ``.lbx`` ist ein ZIP: ``label.xml`` beschreibt das Layout (Maße in pt),
``prop.xml`` nur Metadaten, und Bilder liegen als BMP daneben (``Object0.bmp``
und folgende). Dieses Modul baut daraus ein QLInux-Dokument
(:func:`ql_editor.document.build`) - Band, Ausrichtung, Objekte. Speichern
bleibt ``.qlx``; zurück nach ``.lbx`` schreiben wir nicht.

Bewusst **ohne Qt**, damit der Import headless testbar ist. Was QLInux nicht
abbildet (Barcode, Tabelle, Datenbank, Kabelvorlage, Datum), landet in
``warnings`` und fehlt in der Objektliste - der Rest wird trotzdem geladen.
"""

from __future__ import annotations

import base64
import io
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from . import document, media
from .i18n import tr

#: Endung der P-touch-Dateien.
LBX_SUFFIX = ".lbx"

#: Dots je Punkt (300 dpi, 1 pt = 1/72 in).
DOTS_PER_PT = media.DPI / 72.0

#: Millimeter je Punkt.
MM_PER_PT = media.MM_PER_INCH / 72.0

#: Endlos-Vorlagen in P-touch sind 1000 mm "hoch" - das ist kein Etikett.
_ENDLESS_PAGE_MM = 1000.0

#: So weit darf ein Bandmaß danebenliegen (pt-Rundung, 29 vs. 28,96 mm).
_SIZE_TOLERANCE_MM = 1.5

_PT = "http://schemas.brother.info/ptouch/2007/lbx/main"
_STYLE = "http://schemas.brother.info/ptouch/2007/lbx/style"
_TEXT = "http://schemas.brother.info/ptouch/2007/lbx/text"
_DRAW = "http://schemas.brother.info/ptouch/2007/lbx/draw"
_IMAGE = "http://schemas.brother.info/ptouch/2007/lbx/image"

_ALIGN = {
    "LEFT": "left",
    "CENTER": "center",
    "RIGHT": "right",
    "JUSTIFY": "left",
}


class _Lbx:
    """Ein geöffnetes Archiv plus die abgeleitete Zeichenfläche."""

    def __init__(self, path: Path, archive: zipfile.ZipFile, root: ET.Element):
        self.path = path
        self.archive = archive
        self.root = root
        self.warnings: list[str] = []
        self._skipped: Counter[str] = Counter()
        paper = root.find(f".//{{{_STYLE}}}paper")
        if paper is None:
            raise document.DocumentError(
                tr("{path} enthält kein Etikett.").format(path=path)
            )
        self.paper = paper
        background = root.find(f".//{{{_STYLE}}}backGround")
        self.bg_x = _pt(background.get("x")) if background is not None else 0.0
        self.bg_y = _pt(background.get("y")) if background is not None else 0.0

    def finish_warnings(self) -> None:
        names = {
            "table": tr("Tabelle"),
            "database": tr("Datenbankfeld"),
            "cable": tr("Kabelvorlage"),
            "barcode": tr("Barcode"),
            "datetime": tr("Datum/Uhrzeit"),
            "dateAndTime": tr("Datum/Uhrzeit"),
            "dateTime": tr("Datum/Uhrzeit"),
            "poly": tr("Zeichnung"),
        }
        for local, count in self._skipped.items():
            kind = names.get(local, tr("Objekt"))
            if count > 1:
                self.warnings.append(
                    tr("Nicht übernommen: {kind} ({count}×)").format(
                        kind=kind, count=count
                    )
                )
            else:
                self.warnings.append(
                    tr("Nicht übernommen: {kind}").format(kind=kind)
                )


def load(path: str | Path) -> dict[str, Any]:
    """``.lbx`` lesen und als QLInux-Dokument zurückgeben.

    Zusätzlich zu :func:`ql_editor.document.build` steht in ``warnings``,
    was nicht übernommen wurde. Lesefehler kommen als
    :class:`ql_editor.document.DocumentError`.
    """
    path = Path(path)
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise document.DocumentError(
            tr("{path} ist keine Brother-P-touch-Datei: {error}").format(
                path=path, error=exc
            )
        ) from exc
    with archive:
        try:
            raw = archive.read("label.xml")
        except KeyError as exc:
            raise document.DocumentError(
                tr("{path} enthält kein label.xml.").format(path=path)
            ) from exc
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise document.DocumentError(
                tr("{path} ist keine Brother-P-touch-Datei: {error}").format(
                    path=path, error=exc
                )
            ) from exc
        lbx = _Lbx(path, archive, root)
        media_state = lbx_media(lbx)
        items = lbx_items(lbx)
        lbx.finish_warnings()
    data = document.build(media_state, items)
    data["warnings"] = lbx.warnings
    return data


def lbx_media(lbx: _Lbx) -> dict[str, Any]:
    """Band, Ausrichtung und Länge aus ``style:paper``."""
    paper = lbx.paper
    width_mm = _pt(paper.get("width")) * MM_PER_PT
    height_mm = _pt(paper.get("height")) * MM_PER_PT
    auto = paper.get("autoLength") == "true" or abs(height_mm - _ENDLESS_PAGE_MM) < 5
    landscape = paper.get("orientation") == "landscape"
    orientation = (
        media.Orientation.ALONG.value
        if landscape
        else media.Orientation.ACROSS.value
    )
    state: dict[str, Any] = {
        "color": "black",
        "margins": {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0},
        "orientation": orientation,
        "length_mm": height_mm,
    }
    if auto:
        label, guessed = _endless_for_width(width_mm)
        state.update(label=label.identifier, auto_length=True, length_mode=media.LengthMode.CONTENT.value)
    else:
        label = _fixed_label(width_mm, height_mm)
        if label is not None:
            guessed = False
            state.update(
                label=label.identifier,
                auto_length=False,
                length_mode=media.LengthMode.CONTENT.value,
            )
        else:
            label, guessed = _endless_for_width(width_mm)
            state.update(
                label=label.identifier,
                auto_length=False,
                length_mode=media.LengthMode.FINISHED.value,
                length_mm=height_mm,
            )
    if guessed:
        lbx.warnings.append(
            tr(
                "Kein passendes Band für {size} mm – {name} wird verwendet."
            ).format(size=f"{width_mm:.0f} × {height_mm:.0f}", name=label.display_name)
        )
    return state


def lbx_items(lbx: _Lbx) -> list[dict[str, Any]]:
    """Objekte unter ``pt:objects`` in die Canvas-Serialisierung übersetzen."""
    objects = lbx.root.find(f".//{{{_PT}}}objects")
    if objects is None:
        return []
    items: list[dict[str, Any]] = []
    for element in list(objects):
        local = _local(element.tag)
        if local == "text":
            item = _text_item(lbx, element)
        elif local == "image":
            item = _image_item(lbx, element)
        elif local == "poly":
            item = _line_item(lbx, element)
        elif local == "frame":
            item = _rect_item(lbx, element)
        else:
            lbx._skipped[local] += 1
            continue
        if item is None:
            continue
        item["z"] = float(len(items))
        items.append(item)
    return items


def _endless_for_width(width_mm: float) -> tuple[media.LabelSpec, bool]:
    """Endlosband zur Papierbreite. ``guessed`` ist True, wenn keins passt."""
    endless = [label for label in media.all_labels() if label.is_endless]
    mono = [label for label in endless if not label.color.supports_red]
    match = [
        label
        for label in mono
        if abs(label.tape_width_mm - width_mm) <= _SIZE_TOLERANCE_MM
    ]
    if match:
        return match[0], False
    pool = mono or endless
    closest = min(pool, key=lambda label: abs(label.tape_width_mm - width_mm))
    return closest, True


def _fixed_label(width_mm: float, height_mm: float) -> media.LabelSpec | None:
    """Die-cut oder rund, dessen beide Maße zum Papier passen."""
    found: list[media.LabelSpec] = []
    for label in media.all_labels():
        if label.is_endless or label.color.supports_red:
            continue
        if (
            abs(label.tape_size[0] - width_mm) <= _SIZE_TOLERANCE_MM
            and abs(label.tape_size[1] - height_mm) <= _SIZE_TOLERANCE_MM
        ):
            found.append(label)
    if not found:
        return None
    return min(
        found,
        key=lambda label: abs(label.tape_size[0] - width_mm)
        + abs(label.tape_size[1] - height_mm),
    )


def _text_item(lbx: _Lbx, element: ET.Element) -> dict[str, Any] | None:
    data = element.find(f"{{{_PT}}}data")
    text = data.text if data is not None and data.text else ""
    if not text.strip():
        return None
    style = _object_style(element)
    item, width, _height = _base(lbx, style, "text")
    font = element.find(f"{{{_TEXT}}}ptFontInfo")
    log_font = font.find(f"{{{_TEXT}}}logFont") if font is not None else None
    font_ext = font.find(f"{{{_TEXT}}}fontExt") if font is not None else None
    control = element.find(f"{{{_TEXT}}}textControl")
    align_el = element.find(f"{{{_TEXT}}}textAlign")
    size_pt = _pt(font_ext.get("size")) if font_ext is not None else 12.0
    weight = int(log_font.get("weight") or 400) if log_font is not None else 400
    align = _ALIGN.get(
        (align_el.get("horizontalAlignment") if align_el is not None else "LEFT")
        or "LEFT",
        "left",
    )
    wraps = False
    if control is not None:
        wraps = control.get("autoLF") == "true" or control.get("control") in {
            "FIXEDFRAME",
            "LONGTEXTFIXED",
        }
    # Zentriert/rechts braucht eine Feldbreite, sonst ist das Textfeld nur so
    # breit wie der Text und die Ausrichtung bleibt unsichtbar.
    text_width = width if wraps or align != "left" else -1.0
    item.update(
        text=text,
        font_family=(log_font.get("name") if log_font is not None else None) or "Sans",
        font_pixel_size=max(4, round(size_pt * DOTS_PER_PT)),
        bold=weight >= 700,
        italic=(log_font.get("italic") == "true") if log_font is not None else False,
        color=(font_ext.get("textColor") if font_ext is not None else None) or "#000000",
        align=align,
        text_width=text_width,
    )
    return item


def _image_item(lbx: _Lbx, element: ET.Element) -> dict[str, Any] | None:
    style = _object_style(element)
    item, local_w, local_h = _base(lbx, style, "image")
    image_style = element.find(f"{{{_IMAGE}}}imageStyle")
    filename = image_style.get("fileName") if image_style is not None else None
    if not filename:
        lbx.warnings.append(tr("Bild ohne Datei – nicht übernommen."))
        return None
    try:
        raw = lbx.archive.read(filename)
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (KeyError, OSError) as exc:
        lbx.warnings.append(
            tr("Bild {name} konnte nicht gelesen werden: {error}").format(
                name=filename, error=exc
            )
        )
        return None
    image = image.convert("RGBA")
    image = _apply_trim(image, image_style)
    image = _apply_transparency(image, image_style)
    target_w = max(1, round(local_w))
    target_h = max(1, round(local_h))
    # Das BMP ist oft die Originaldatei (mehrere tausend Pixel). Auf die
    # Etikettengröße verkleinern, sonst landet das im .qlx als Base64.
    if image.width > target_w or image.height > target_h:
        image = image.resize(
            (min(image.width, target_w), min(image.height, target_h)),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    item.update(
        data_b64=base64.b64encode(buffer.getvalue()).decode("ascii"),
        source_path=image_style.get("originalName") if image_style is not None else None,
        scale_x=target_w / image.width,
        scale_y=target_h / image.height,
    )
    return item


def _apply_trim(image: Image.Image, image_style: ET.Element | None) -> Image.Image:
    if image_style is None:
        return image
    trimming = image_style.find(f"{{{_IMAGE}}}trimming")
    origin = image_style.find(f"{{{_IMAGE}}}orgPos")
    if trimming is None or trimming.get("flag") != "true" or origin is None:
        return image
    org_w = _pt(origin.get("width"))
    org_h = _pt(origin.get("height"))
    if org_w <= 0 or org_h <= 0:
        return image

    def _px(value: str | None, org: float, span: float, pixels: int) -> int:
        return int(round((_pt(value) - org) / span * pixels))

    left = _px(trimming.get("trimOrgX"), _pt(origin.get("x")), org_w, image.width)
    top = _px(trimming.get("trimOrgY"), _pt(origin.get("y")), org_h, image.height)
    # trimOrgWidth/Height sind Breiten, keine Koordinaten.
    right = left + max(1, int(round(_pt(trimming.get("trimOrgWidth")) / org_w * image.width)))
    bottom = top + max(1, int(round(_pt(trimming.get("trimOrgHeight")) / org_h * image.height)))
    left = min(max(0, left), image.width - 1)
    top = min(max(0, top), image.height - 1)
    right = min(max(left + 1, right), image.width)
    bottom = min(max(top + 1, bottom), image.height)
    return image.crop((left, top, right, bottom))


def _apply_transparency(image: Image.Image, image_style: ET.Element | None) -> Image.Image:
    if image_style is None:
        return image
    transparent = image_style.find(f"{{{_IMAGE}}}transparent")
    if transparent is None or transparent.get("flag") != "true":
        return image
    color = _hex_rgb(transparent.get("color") or "#FFFFFF")
    pixels = image.getdata()
    image.putdata(
        [
            (red, green, blue, 0) if (red, green, blue) == color else (red, green, blue, alpha)
            for red, green, blue, alpha in pixels
        ]
    )
    return image


def _line_item(lbx: _Lbx, element: ET.Element) -> dict[str, Any] | None:
    poly = element.find(f"{{{_DRAW}}}polyStyle")
    if poly is None or poly.get("shape") != "LINE":
        lbx._skipped["poly"] += 1
        return None
    points = element.find(f".//{{{_DRAW}}}polyLinePoints")
    parsed = _points(points.get("points") if points is not None else None)
    if len(parsed) < 2:
        lbx._skipped["poly"] += 1
        return None
    style = _object_style(element)
    origin_x = _pt(style.get("x"))
    origin_y = _pt(style.get("y"))
    (x1, y1), (x2, y2) = parsed[0], parsed[-1]
    # Die Punkte sind die fertige Linie. Eine zusätzliche Drehung würde sie
    # ein zweites Mal drehen; der Winkel steckt damit schon in den Endpunkten.
    item = {
        "type": "line",
        "x": (_pt(style.get("x")) - lbx.bg_x) * DOTS_PER_PT,
        "y": (_pt(style.get("y")) - lbx.bg_y) * DOTS_PER_PT,
        "rotation": 0.0,
        "z": 0.0,
    }
    item.update(
        x1=(x1 - origin_x) * DOTS_PER_PT,
        y1=(y1 - origin_y) * DOTS_PER_PT,
        x2=(x2 - origin_x) * DOTS_PER_PT,
        y2=(y2 - origin_y) * DOTS_PER_PT,
        width_px=max(0.5, _pen_width(style) * DOTS_PER_PT),
    )
    return item


def _rect_item(lbx: _Lbx, element: ET.Element) -> dict[str, Any]:
    style = _object_style(element)
    item, width, height = _base(lbx, style, "rect")
    item.update(
        w=max(1.0, width),
        h=max(1.0, height),
        width_px=max(0.5, _pen_width(style) * DOTS_PER_PT),
        filled=False,
    )
    return item


def _base(lbx: _Lbx, style: ET.Element, kind: str) -> tuple[dict[str, Any], float, float]:
    """Position, Drehung und **lokale** Breite/Höhe.

    ``x``/``y``/``width``/``height`` in der Datei sind der achsenparallele
    Kasten auf dem Etikett. ``angle`` dreht den Inhalt darin (P-touch, im
    Uhrzeigersinn wie Qt). Die linke obere Ecke des Objekts wandert dabei,
    sonst landet ein hochkant gestelltes Logo neben dem Band.
    """
    x = (_pt(style.get("x")) - lbx.bg_x) * DOTS_PER_PT
    y = (_pt(style.get("y")) - lbx.bg_y) * DOTS_PER_PT
    width = _pt(style.get("width")) * DOTS_PER_PT
    height = _pt(style.get("height")) * DOTS_PER_PT
    x, y, width, height, rotation = _place(x, y, width, height, float(style.get("angle") or 0.0))
    return (
        {"type": kind, "x": x, "y": y, "rotation": rotation, "z": 0.0},
        width,
        height,
    )


def _place(
    x: float, y: float, width: float, height: float, angle: float
) -> tuple[float, float, float, float, float]:
    """Kasten (x, y, Breite, Höhe) plus Drehung in Qt-Lage (Ursprung oben links)."""
    quarter = round(angle / 90.0)
    if abs(angle - quarter * 90.0) > 0.1:
        return x, y, width, height, angle
    quarter %= 4
    if quarter == 1:  # 90° im Uhrzeigersinn
        return x + width, y, height, width, 90.0
    if quarter == 2:
        return x + width, y + height, width, height, 180.0
    if quarter == 3:  # 270°
        return x, y + height, height, width, 270.0
    return x, y, width, height, 0.0


def _object_style(element: ET.Element) -> ET.Element:
    style = element.find(f"{{{_PT}}}objectStyle")
    return style if style is not None else ET.Element("objectStyle")


def _pen_width(style: ET.Element) -> float:
    pen = style.find(f"{{{_PT}}}pen")
    if pen is None:
        return 0.5
    return _pt(pen.get("widthX")) or 0.5


def _points(raw: str | None) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for pair in (raw or "").split():
        parts = pair.split(",")
        if len(parts) != 2:
            continue
        points.append((_pt(parts[0]), _pt(parts[1])))
    return points


def _pt(value: str | None) -> float:
    if not value:
        return 0.0
    text = value.strip().lower().removesuffix("pt").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _hex_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return (255, 255, 255)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (255, 255, 255)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
