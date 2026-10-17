"""Import von Brother-P-touch-Dateien (``.lbx``, :mod:`ql_editor.lbx`).

Die Dateien hier sind synthetisch: ein ZIP mit ``label.xml`` und, wo nötig,
einem kleinen BMP. Keine echten Etiketten im Repository.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from ql_editor import document, lbx

NS = """xmlns:pt="http://schemas.brother.info/ptouch/2007/lbx/main" xmlns:style="http://schemas.brother.info/ptouch/2007/lbx/style" xmlns:text="http://schemas.brother.info/ptouch/2007/lbx/text" xmlns:draw="http://schemas.brother.info/ptouch/2007/lbx/draw" xmlns:image="http://schemas.brother.info/ptouch/2007/lbx/image" """


def _pt(mm: float) -> str:
    return f"{mm / 25.4 * 72:.4f}pt"


def write_lbx(
    path: Path,
    *,
    width_mm: float,
    height_mm: float,
    orientation: str = "landscape",
    auto_length: bool = True,
    objects: str = "",
    background: str | None = None,
    images: dict[str, Image.Image] | None = None,
) -> Path:
    """Minimale ``.lbx`` schreiben."""
    if background is None:
        background = (
            f'<style:backGround x="{_pt(1.5)}" y="{_pt(1.5)}" '
            f'width="{_pt(width_mm)}" height="{_pt(10)}"/>'
        )
    xml = f"""<?xml version="1.0"?>
<pt:document {NS} version="1.7">
  <pt:body currentSheet="Sheet 1">
    <style:sheet name="Sheet 1">
      <style:paper width="{_pt(width_mm)}" height="{_pt(height_mm)}"
        orientation="{orientation}" autoLength="{"true" if auto_length else "false"}"/>
      {background}
      <pt:objects>
        {objects}
      </pt:objects>
    </style:sheet>
  </pt:body>
</pt:document>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("label.xml", xml)
        for name, image in (images or {}).items():
            buffer = io.BytesIO()
            image.save(buffer, format="BMP")
            archive.writestr(name, buffer.getvalue())
    return path


def _text(
    *,
    x: float = 2,
    y: float = 2,
    width: float = 40,
    height: float = 10,
    size: str = "15.3pt",
    weight: int = 700,
    align: str = "CENTER",
    control: str = "AUTOLEN",
    auto_lf: str = "false",
    body: str = "Hallo",
    font: str = "DIN",
) -> str:
    return f"""
    <text:text>
      <pt:objectStyle x="{_pt(x)}" y="{_pt(y)}" width="{_pt(width)}" height="{_pt(height)}" angle="0">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <text:ptFontInfo>
        <text:logFont name="{font}" italic="false" weight="{weight}"/>
        <text:fontExt size="{size}" textColor="#000000"/>
      </text:ptFontInfo>
      <text:textControl control="{control}" autoLF="{auto_lf}"/>
      <text:textAlign horizontalAlignment="{align}"/>
      <pt:data>{body}</pt:data>
    </text:text>
    """


def test_endless_62_landscape_is_along_the_tape(tmp_path):
    path = write_lbx(tmp_path / "logo.lbx", width_mm=62, height_mm=1000, orientation="landscape")

    data = lbx.load(path)

    assert data["format"] == document.DOCUMENT_FORMAT
    assert data["media"]["label"] == "62"
    assert data["media"]["orientation"] == "along"
    assert data["media"]["auto_length"] is True
    assert data["media"]["margins"] == {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
    assert data["warnings"] == []


def test_portrait_text_keeps_font_weight_and_alignment(tmp_path):
    path = write_lbx(
        tmp_path / "adresse.lbx",
        width_mm=50,
        height_mm=1000,
        orientation="portrait",
        objects=_text(),
    )

    data = lbx.load(path)
    item = data["items"][0]

    assert data["media"]["label"] == "50"
    assert data["media"]["orientation"] == "across"
    assert item["text"] == "Hallo"
    assert item["font_family"] == "DIN"
    assert item["bold"] is True
    assert item["font_pixel_size"] == 64
    assert item["align"] == "center"
    # Zentriert: Feldbreite gesetzt, sonst sähe man die Ausrichtung nicht.
    assert item["text_width"] == pytest.approx(40 / 25.4 * lbx.media.DPI)


def test_die_cut_29x90(tmp_path):
    path = write_lbx(
        tmp_path / "name.lbx",
        width_mm=29,
        height_mm=90,
        orientation="landscape",
        auto_length=False,
    )

    data = lbx.load(path)

    assert data["media"]["label"] == "29x90"
    assert data["media"]["orientation"] == "along"
    assert data["media"]["auto_length"] is False


def test_image_is_placed_against_the_background_and_shrunk(tmp_path):
    image = Image.new("RGB", (200, 100), "black")
    objects = f"""
    <image:image>
      <pt:objectStyle x="{_pt(11.5)}" y="{_pt(6.5)}" width="{_pt(10)}" height="{_pt(5)}" angle="0">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <image:imageStyle fileName="Object0.bmp" originalName="logo.png">
        <image:trimming flag="false"/>
        <image:transparent flag="false"/>
        <image:orgPos x="{_pt(11.5)}" y="{_pt(6.5)}" width="{_pt(10)}" height="{_pt(5)}"/>
      </image:imageStyle>
    </image:image>
    """
    path = write_lbx(
        tmp_path / "bild.lbx",
        width_mm=62,
        height_mm=1000,
        objects=objects,
        images={"Object0.bmp": image},
    )

    data = lbx.load(path)
    item = data["items"][0]
    raw = __import__("base64").b64decode(item["data_b64"])
    loaded = Image.open(io.BytesIO(raw))

    assert item["x"] == pytest.approx(10 / 25.4 * lbx.media.DPI, abs=0.05)
    assert item["y"] == pytest.approx(5 / 25.4 * lbx.media.DPI, abs=0.05)
    # 10 mm x 5 mm sind ~118 x 59 Dots - das 200x100-BMP wird darauf verkleinert.
    assert loaded.size == (118, 59)
    assert item["scale_x"] * loaded.size[0] == pytest.approx(10 / 25.4 * lbx.media.DPI, abs=1)
    assert item["scale_y"] * loaded.size[1] == pytest.approx(5 / 25.4 * lbx.media.DPI, abs=1)


def test_line_and_frame(tmp_path):
    objects = f"""
    <draw:poly>
      <pt:objectStyle x="{_pt(3.5)}" y="{_pt(4.5)}" width="{_pt(20)}" height="{_pt(1)}" angle="0">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <draw:polyStyle shape="LINE">
        <draw:polyLinePoints points="{_pt(3.5)},{_pt(4.5)} {_pt(23.5)},{_pt(4.5)}"/>
      </draw:polyStyle>
    </draw:poly>
    <draw:frame>
      <pt:objectStyle x="{_pt(3.5)}" y="{_pt(8)}" width="{_pt(12)}" height="{_pt(6)}" angle="90">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <draw:frameStyle category="SIMPLE"/>
    </draw:frame>
    """
    path = write_lbx(tmp_path / "linien.lbx", width_mm=62, height_mm=1000, objects=objects)

    line, frame = lbx.load(path)["items"]

    assert line["type"] == "line"
    assert line["x1"] == pytest.approx(0, abs=0.01)
    assert line["x2"] == pytest.approx(20 / 25.4 * lbx.media.DPI)
    assert line["width_px"] == pytest.approx(0.5 * lbx.DOTS_PER_PT)
    assert frame["type"] == "rect"
    # 90° im Uhrzeigersinn: der Kasten bleibt 12 x 6 mm, der Anker wandert
    # um die Breite nach rechts, lokal sind die Seiten vertauscht.
    assert frame["rotation"] == 90
    assert frame["x"] == pytest.approx(14 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["y"] == pytest.approx(6.5 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["w"] == pytest.approx(6 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["h"] == pytest.approx(12 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["filled"] is False


def test_unknown_objects_are_warnings_not_fatal(tmp_path):
    objects = """
    <table:table xmlns:table="http://schemas.brother.info/ptouch/2007/lbx/table"/>
    """ + _text(body="bleibt")
    path = write_lbx(tmp_path / "tabelle.lbx", width_mm=62, height_mm=1000, objects=objects)

    data = lbx.load(path)

    assert [item["text"] for item in data["items"]] == ["bleibt"]
    assert any("Tabelle" in warning for warning in data["warnings"])


def test_not_a_zip(tmp_path):
    path = tmp_path / "kaputt.lbx"
    path.write_text("kein zip", encoding="utf-8")

    with pytest.raises(document.DocumentError):
        lbx.load(path)


def test_zip_without_label_xml(tmp_path):
    path = tmp_path / "leer.lbx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("prop.xml", "<meta/>")

    with pytest.raises(document.DocumentError):
        lbx.load(path)
