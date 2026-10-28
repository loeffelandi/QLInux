"""Import von Brother-P-touch-Dateien (``.lbx``, :mod:`ql_editor.lbx`).

Die Dateien hier sind synthetisch: ein ZIP mit ``label.xml`` und, wo nötig,
einem kleinen BMP. Keine echten Etiketten im Repository.
"""

from __future__ import annotations

import base64
import io
import zipfile

import pytest
from PIL import Image
from ql_editor import document, lbx
from tests.lbx_samples import pt, text_object, write_lbx


def test_endless_62_landscape_is_along_the_tape(tmp_path):
    path = write_lbx(
        tmp_path / "logo.lbx", width_mm=62, height_mm=1000, orientation="landscape"
    )

    data = lbx.load(path)

    assert data["format"] == document.DOCUMENT_FORMAT
    assert data["media"]["label"] == "62"
    assert data["media"]["orientation"] == "along"
    assert data["media"]["auto_length"] is True
    assert data["media"]["margins"] == {
        "left": 0.0,
        "right": 0.0,
        "top": 0.0,
        "bottom": 0.0,
    }
    assert "length_mm" not in data["media"]
    assert data["warnings"] == []


def test_portrait_text_keeps_font_weight_and_alignment(tmp_path):
    path = write_lbx(
        tmp_path / "adresse.lbx",
        width_mm=50,
        height_mm=1000,
        orientation="portrait",
        objects=text_object(),
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
      <pt:objectStyle x="{pt(11.5)}" y="{pt(6.5)}" width="{pt(10)}" height="{pt(5)}" angle="0">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <image:imageStyle fileName="Object0.bmp" originalName="logo.png">
        <image:trimming flag="false"/>
        <image:transparent flag="false"/>
        <image:orgPos x="{pt(11.5)}" y="{pt(6.5)}" width="{pt(10)}" height="{pt(5)}"/>
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
    raw = base64.b64decode(item["data_b64"])
    loaded = Image.open(io.BytesIO(raw))

    assert item["x"] == pytest.approx(10 / 25.4 * lbx.media.DPI, abs=0.05)
    assert item["y"] == pytest.approx(5 / 25.4 * lbx.media.DPI, abs=0.05)
    # 10 mm x 5 mm sind ~118 x 59 Dots - das 200x100-BMP wird darauf verkleinert.
    assert loaded.size == (118, 59)
    assert item["scale_x"] * loaded.size[0] == pytest.approx(
        10 / 25.4 * lbx.media.DPI, abs=1
    )
    assert item["scale_y"] * loaded.size[1] == pytest.approx(
        5 / 25.4 * lbx.media.DPI, abs=1
    )


def test_line_and_frame(tmp_path):
    objects = f"""
    <draw:poly>
      <pt:objectStyle x="{pt(3.5)}" y="{pt(4.5)}" width="{pt(20)}" height="{pt(1)}" angle="0">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <draw:polyStyle shape="LINE">
        <draw:polyLinePoints points="{pt(3.5)},{pt(4.5)} {pt(23.5)},{pt(4.5)}"/>
      </draw:polyStyle>
    </draw:poly>
    <draw:frame>
      <pt:objectStyle x="{pt(3.5)}" y="{pt(8)}" width="{pt(12)}" height="{pt(6)}" angle="90">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <draw:frameStyle category="SIMPLE"/>
    </draw:frame>
    """
    path = write_lbx(
        tmp_path / "linien.lbx", width_mm=62, height_mm=1000, objects=objects
    )

    line, frame = lbx.load(path)["items"]

    assert line["type"] == "line"
    assert line["x1"] == pytest.approx(0, abs=0.01)
    assert line["x2"] == pytest.approx(20 / 25.4 * lbx.media.DPI)
    assert line["width_px"] == pytest.approx(0.5 * lbx.DOTS_PER_PT)
    assert frame["type"] == "rect"
    # Datei-Winkel 90° ist gegen den Uhrzeigersinn: Qt-Drehung 270°, der Anker
    # wandert um die Höhe nach unten, lokal sind die Seiten vertauscht.
    assert frame["rotation"] == 270
    assert frame["x"] == pytest.approx(2 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["y"] == pytest.approx(12.5 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["w"] == pytest.approx(6 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["h"] == pytest.approx(12 / 25.4 * lbx.media.DPI, abs=0.05)
    assert frame["filled"] is False


def test_unknown_objects_are_warnings_not_fatal(tmp_path):
    objects = """
    <table:table xmlns:table="http://schemas.brother.info/ptouch/2007/lbx/table"/>
    """ + text_object(body="bleibt")
    path = write_lbx(
        tmp_path / "tabelle.lbx", width_mm=62, height_mm=1000, objects=objects
    )

    data = lbx.load(path)

    assert [item["text"] for item in data["items"]] == ["bleibt"]
    assert any("Tabelle" in warning for warning in data["warnings"])


def test_not_a_zip(tmp_path):
    path = tmp_path / "kaputt.lbx"
    path.write_text("kein zip", encoding="utf-8")

    with pytest.raises(document.DocumentError):
        lbx.load(path)


def test_place_turns_file_angles_counterclockwise():
    """180° bleibt, 270° in der Datei ist 90° im Uhrzeigersinn für Qt."""
    assert lbx._place(10, 20, 30, 40, 180) == (40, 60, 30, 40, 180.0)
    assert lbx._place(10, 20, 30, 40, 270) == (40, 20, 40, 30, 90.0)
    assert lbx._place(10, 20, 30, 40, 90) == (10, 60, 40, 30, 270.0)


def test_trim_flag_warns_and_keeps_the_whole_image(tmp_path):
    image = Image.new("RGB", (8, 4), "red")
    objects = f"""
    <image:image>
      <pt:objectStyle x="{pt(2)}" y="{pt(2)}" width="{pt(20)}" height="{pt(10)}" angle="0"/>
      <image:imageStyle fileName="Object0.bmp" originalName="logo.png">
        <image:trimming flag="true" trimOrgX="0pt" trimOrgY="0pt" trimOrgWidth="1pt" trimOrgHeight="1pt"/>
      </image:imageStyle>
    </image:image>
    """
    path = write_lbx(
        tmp_path / "schnitt.lbx",
        width_mm=62,
        height_mm=1000,
        objects=objects,
        images={"Object0.bmp": image},
    )

    data = lbx.load(path)
    loaded = Image.open(io.BytesIO(base64.b64decode(data["items"][0]["data_b64"])))

    assert loaded.size == (8, 4)
    assert any("logo.png" in warning for warning in data["warnings"])


def test_transparent_color_becomes_alpha(tmp_path):
    image = Image.new("RGB", (2, 1))
    image.putpixel((0, 0), (255, 255, 255))
    image.putpixel((1, 0), (0, 0, 0))
    objects = f"""
    <image:image>
      <pt:objectStyle x="{pt(2)}" y="{pt(2)}" width="{pt(20)}" height="{pt(10)}" angle="0"/>
      <image:imageStyle fileName="Object0.bmp">
        <image:transparent flag="true" color="#FFFFFF"/>
      </image:imageStyle>
    </image:image>
    """
    path = write_lbx(
        tmp_path / "transparent.lbx",
        width_mm=62,
        height_mm=1000,
        objects=objects,
        images={"Object0.bmp": image},
    )

    loaded = Image.open(
        io.BytesIO(base64.b64decode(lbx.load(path)["items"][0]["data_b64"]))
    ).convert("RGBA")

    assert loaded.getpixel((0, 0))[3] == 0
    assert loaded.getpixel((1, 0))[3] == 255


def test_fixed_length_endless_when_no_die_cut_matches(tmp_path):
    path = write_lbx(
        tmp_path / "fest.lbx",
        width_mm=62,
        height_mm=26,
        auto_length=False,
    )

    media = lbx.load(path)["media"]

    assert media["label"] == "62"
    assert media["auto_length"] is False
    assert media["length_mode"] == "finished"
    assert media["length_mm"] == pytest.approx(26, abs=0.05)


def test_unknown_width_warns_and_picks_the_closest_tape(tmp_path):
    path = write_lbx(tmp_path / "schmal.lbx", width_mm=36, height_mm=1000)

    data = lbx.load(path)

    assert data["media"]["label"] == "38"
    assert any("Kein passendes Band" in warning for warning in data["warnings"])


def test_cable_template_keeps_its_text(tmp_path):
    objects = (
        """
    <cable:cable xmlns:cable="http://schemas.brother.info/ptouch/2007/lbx/cable">
    """
        + text_object(body="eins")
        + text_object(body="zwei")
        + """
    </cable:cable>
    """
    )
    path = write_lbx(
        tmp_path / "kabel.lbx", width_mm=62, height_mm=1000, objects=objects
    )

    data = lbx.load(path)

    assert [item["text"] for item in data["items"]] == ["eins", "zwei"]
    assert any("Kabelvorlage" in warning for warning in data["warnings"])


def test_broken_numbers_do_not_abort(tmp_path):
    path = write_lbx(
        tmp_path / "zahl.lbx",
        width_mm=62,
        height_mm=1000,
        objects=text_object(weight="fett", angle="schief"),
    )

    item = lbx.load(path)["items"][0]

    assert item["bold"] is False
    assert item["rotation"] == 0


def test_a_broken_bitmap_is_a_warning(tmp_path):
    objects = """
    <image:image>
      <pt:objectStyle x="2pt" y="2pt" width="10pt" height="10pt" angle="0"/>
      <image:imageStyle fileName="Object0.bmp" originalName="kaputt.bmp"/>
    </image:image>
    """
    path = write_lbx(
        tmp_path / "kaputtbild.lbx",
        width_mm=62,
        height_mm=1000,
        objects=objects,
        raw_files={"Object0.bmp": b"das ist kein bild"},
    )

    data = lbx.load(path)

    assert data["items"] == []
    assert any("Object0.bmp" in warning for warning in data["warnings"])


def test_zip_without_label_xml(tmp_path):
    path = tmp_path / "leer.lbx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("prop.xml", "<meta/>")

    with pytest.raises(document.DocumentError):
        lbx.load(path)
