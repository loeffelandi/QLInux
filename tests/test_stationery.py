"""Avery-Zweckform-Bögen: gLabels-Maße, Belegung, PDF."""

from __future__ import annotations

import re

import pytest
from PIL import Image
from PySide6.QtCore import QSettings

from ql_editor.media import Kind, mm_to_dots
from ql_editor.settings import AppSettings
from ql_editor.stationery import (
    SHEET_LABELS_MAX,
    SheetError,
    as_label_spec,
    fill_caption,
    filled_per_page,
    get_template,
    page_count,
    plan_sheet,
    templates,
)

pytestmark = pytest.mark.usefixtures("qapp")


def test_catalog_contains_the_common_address_sheets():
    parts = {template.part for template in templates()}
    assert {"3474", "3475", "3481", "3651", "4780"} <= parts


def test_3475_is_the_24_up_address_sheet():
    template = get_template("3475")
    assert (template.nx, template.ny) == (3, 8)
    assert template.per_sheet == 24
    assert template.page_width_mm == 210
    assert template.page_height_mm == 297
    assert template.label_width_mm == pytest.approx(198.570 * 25.4 / 72)
    assert template.label_height_mm == pytest.approx(102.121 * 25.4 / 72)


def test_3481_grid_is_in_millimetres():
    template = get_template("3481")
    assert template.label_width_mm == 70
    assert template.label_height_mm == 41
    assert template.slot_origin(0) == (0, 5)
    assert template.slot_origin(1) == (70, 5)
    assert template.slot_origin(3) == (0, 46)


def test_equivalent_part_inherits_the_grid():
    original = get_template("J8435A")
    alias = get_template("32250A")
    assert alias.part == "32250A"
    assert alias.label_width_mm == original.label_width_mm
    assert alias.nx == original.nx
    assert alias.ny == original.ny


def test_cd_label_is_a_disc_with_a_hole():
    template = get_template("3654")
    assert template.hole_radius_mm > 0
    assert template.label_width_mm == pytest.approx(template.label_height_mm)
    assert template.ny == 2


def test_unknown_part_is_an_error():
    with pytest.raises(SheetError):
        get_template("kein-bogen")


def test_copies_repeat_before_the_next_record_and_the_next_sheet_starts_at_one():
    template = get_template("3475")
    placements = plan_sheet(template, 3, start=23, copies=2)
    assert [(item.page, item.slot, item.image_index) for item in placements] == [
        (0, 22, 0),
        (0, 23, 0),
        (1, 0, 1),
        (1, 1, 1),
        (1, 2, 2),
        (1, 3, 2),
    ]
    assert page_count(placements) == 2
    assert filled_per_page(placements) == [2, 4]


def test_fill_caption_states_how_full_each_sheet_is():
    template = get_template("3475")
    one = plan_sheet(template, 10, start=1, copies=1)
    assert filled_per_page(one) == [10]
    assert fill_caption(filled_per_page(one), template.per_sheet) == (
        "10 von 24 Etiketten belegt"
    )
    many = plan_sheet(template, 30, start=1, copies=1)
    assert filled_per_page(many) == [24, 6]
    assert fill_caption(filled_per_page(many), template.per_sheet) == (
        "Bogen 1: 24 von 24\nBogen 2: 6 von 24"
    )
    full = plan_sheet(template, 48, start=1, copies=1)
    assert fill_caption(filled_per_page(full), template.per_sheet) == (
        "Bogen 1–2: 24 von 24"
    )


def test_plan_rejects_empty_jobs_and_the_cell_cap():
    template = get_template("3475")
    with pytest.raises(SheetError):
        plan_sheet(template, 0, start=1, copies=1)
    with pytest.raises(SheetError):
        plan_sheet(template, 1, start=0, copies=1)
    with pytest.raises(SheetError):
        plan_sheet(template, 1, start=25, copies=1)
    with pytest.raises(SheetError):
        plan_sheet(template, SHEET_LABELS_MAX, copies=2)


def test_label_spec_uses_the_die_cut_size():
    template = get_template("3481")
    spec = as_label_spec(template)
    assert spec.identifier == "zweckform-3481"
    assert spec.form_factor is Kind.DIE_CUT
    assert spec.width_dots == mm_to_dots(70)
    assert spec.height_dots == mm_to_dots(41)
    assert spec.feed_margin == 0


def test_pdf_keeps_one_a4_page_for_a_partial_sheet(qapp, tmp_path):
    from ql_editor.sheet_output import write_pdf

    template = get_template("3481")
    image = Image.new("RGB", (12, 8), "black")
    placements = plan_sheet(template, 2, start=1, copies=1)
    path = tmp_path / "bogen.pdf"
    write_pdf(path, template, [image, image], placements)
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    text = data.decode("latin-1", errors="ignore")
    assert len(re.findall(r"/Type\s*/Page(?!s)", text)) == 1


def test_pdf_adds_a_page_when_the_grid_overflows(qapp, tmp_path):
    from ql_editor.sheet_output import write_pdf

    template = get_template("3475")
    image = Image.new("RGB", (4, 4), "white")
    placements = plan_sheet(template, 25, start=1, copies=1)
    path = tmp_path / "bogen.pdf"
    write_pdf(path, template, [image] * 25, placements)
    text = path.read_bytes().decode("latin-1", errors="ignore")
    assert len(re.findall(r"/Type\s*/Page(?!s)", text)) == 2


def test_preview_page_is_a4_at_72_dpi(qapp):
    from ql_editor.sheet_output import render_page_image

    template = get_template("3481")
    image = Image.new("RGB", (6, 6), "red")
    placements = plan_sheet(template, 1, start=1, copies=1)
    preview = render_page_image(template, [image], placements, dpi=72)
    assert preview.width() == pytest.approx(210 / 25.4 * 72, abs=1)
    assert preview.height() == pytest.approx(297 / 25.4 * 72, abs=1)
    # 3481 beginnt 5 mm unter dem Papierrand. Darüber bleibt das Blatt weiß,
    # im Feld liegt das Etikett.
    assert preview.pixelColor(2, 2).red() > 250
    assert preview.pixelColor(2, 2).blue() > 250
    assert preview.pixelColor(4, 20).red() > 200
    assert preview.pixelColor(4, 20).blue() < 40


def test_sheet_settings_roundtrip(qapp, tmp_path):
    path = tmp_path / "qlinux.ini"
    settings = AppSettings(QSettings(str(path), QSettings.Format.IniFormat))
    settings.sheet_output = True
    settings.sheet_part = "3481"
    settings.sheet_start = 4
    settings.sheet_offset_x = 1.5
    settings.sheet_offset_y = -0.5
    settings.sheet_printer = "Office"
    settings.sync()
    again = AppSettings(QSettings(str(path), QSettings.Format.IniFormat))
    assert again.sheet_output is True
    assert again.sheet_part == "3481"
    assert again.sheet_start == 4
    assert again.sheet_offset_x == pytest.approx(1.5)
    assert again.sheet_offset_y == pytest.approx(-0.5)
    assert again.sheet_printer == "Office"


def test_offset_is_clamped(qapp, tmp_path):
    settings = AppSettings(
        QSettings(str(tmp_path / "qlinux.ini"), QSettings.Format.IniFormat)
    )
    settings.sheet_offset_x = 80
    assert settings.sheet_offset_x == 20


def test_sheet_target_sizes_the_canvas_to_the_label(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.stationery import OUTPUT_BROTHER, OUTPUT_SHEET

    window = MainWindow()
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_SHEET))
    window._sheet_part_combo.setCurrentIndex(
        window._sheet_part_combo.findData("3481")
    )
    assert window._canvas._label.width_dots == mm_to_dots(70)
    assert window._canvas.height_dots == mm_to_dots(41)
    assert window._sheet_hint.text() == "1 von 21 Etiketten belegt"
    # Sichtbar heißt: eingeblendet gegenüber dem eigenen Vorfahren. Das
    # Druck-Panel ist zu, bis das Sheet aufgeht.
    media = window._media_panel
    panel = window._print_panel
    assert window._sheet_box.isVisibleTo(media)
    assert not window._media_panel._printer_box.isVisibleTo(media)
    assert window._sheet_hint.isVisibleTo(panel)
    assert window._sheet_pdf_button.isVisibleTo(panel)
    assert not window._quality_box.isVisibleTo(panel)
    assert window._left_panel.title == "Etikettenbogen"
    window._output_combo.setCurrentIndex(
        window._output_combo.findData(OUTPUT_BROTHER)
    )
    assert not str(window._canvas._label.identifier).startswith("zweckform")
    assert window._quality_box.isVisibleTo(panel)
    assert not window._sheet_box.isVisibleTo(media)
    assert window._media_panel._printer_box.isVisibleTo(media)
    assert not window._sheet_hint.isVisibleTo(panel)
    assert window._left_panel.title == "Band & Drucker"
    window.close()
    qapp.processEvents()
