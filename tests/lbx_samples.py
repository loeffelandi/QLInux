"""Synthetische ``.lbx``-Dateien für die Import-Tests.

Keine echten Etiketten. ``tests`` liegt über das Repo-Root im ``sys.path``
(siehe ``tests/conftest.py``), deshalb ``from tests.lbx_samples import ...``.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from PIL import Image

NS = """xmlns:pt="http://schemas.brother.info/ptouch/2007/lbx/main" xmlns:style="http://schemas.brother.info/ptouch/2007/lbx/style" xmlns:text="http://schemas.brother.info/ptouch/2007/lbx/text" xmlns:draw="http://schemas.brother.info/ptouch/2007/lbx/draw" xmlns:image="http://schemas.brother.info/ptouch/2007/lbx/image" """


def pt(mm: float) -> str:
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
    raw_files: dict[str, bytes] | None = None,
    paper_extra: str = "",
    extra_ns: str = "",
    before_objects: str = "",
) -> Path:
    """Minimale ``.lbx`` schreiben."""
    if background is None:
        background = (
            f'<style:backGround x="{pt(1.5)}" y="{pt(1.5)}" '
            f'width="{pt(width_mm)}" height="{pt(10)}"/>'
        )
    xml = f"""<?xml version="1.0"?>
<pt:document {NS}{extra_ns} version="1.7">
  <pt:body currentSheet="Sheet 1">
    <style:sheet name="Sheet 1">
      <style:paper width="{pt(width_mm)}" height="{pt(height_mm)}"
        orientation="{orientation}" autoLength="{"true" if auto_length else "false"}" {paper_extra}/>
      {background}
      {before_objects}
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
        for name, raw in (raw_files or {}).items():
            archive.writestr(name, raw)
    return path


def text_object(
    *,
    x: float = 2,
    y: float = 2,
    width: float = 40,
    height: float = 10,
    size: str = "15.3pt",
    weight: object = 700,
    align: str = "CENTER",
    control: str = "AUTOLEN",
    auto_lf: str = "false",
    body: str = "Hallo",
    font: str = "DIN",
    angle: str = "0",
    expanded: str | None = None,
) -> str:
    expanded_xml = ""
    if expanded:
        expanded_xml = (
            f'<pt:expanded dbMergeFieldStyleName="{expanded}" dbRecordOffset="0"/>'
        )
    return f"""
    <text:text>
      <pt:objectStyle x="{pt(x)}" y="{pt(y)}" width="{pt(width)}" height="{pt(height)}" angle="{angle}">
        <pt:pen widthX="0.5pt"/>
      </pt:objectStyle>
      <text:ptFontInfo>
        <text:logFont name="{font}" italic="false" weight="{weight}"/>
        <text:fontExt size="{size}" textColor="#000000"/>
      </text:ptFontInfo>
      <text:textControl control="{control}" autoLF="{auto_lf}"/>
      <text:textAlign horizontalAlignment="{align}"/>
      {expanded_xml}
      <pt:data>{body}</pt:data>
    </text:text>
    """
