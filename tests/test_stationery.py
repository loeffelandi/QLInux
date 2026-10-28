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


def _picker_for(template):
    from ql_editor.sheet_picker import SheetStartPicker

    picker = SheetStartPicker()
    picker.set_template(template)
    # 1 px je Millimeter, damit die Feldmitte aus den Vorlagenmaßen kommt.
    picker.resize(round(template.page_width_mm), round(template.page_height_mm))
    return picker


def _field_center(template, number: int):
    from PySide6.QtCore import QPointF

    x_mm, y_mm = template.slot_origin(number - 1)
    return QPointF(
        x_mm + template.label_width_mm / 2,
        y_mm + template.label_height_mm / 2,
    )


def _press(picker, pos) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent

    picker.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            pos,
            picker.mapToGlobal(pos),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )


def test_picker_hits_the_center_of_field_five_on_3475(qapp):
    from ql_editor import sheet_picker

    source = sheet_picker.__loader__.get_source(sheet_picker.__name__)
    assert source is not None
    assert "import sheet_output" not in source
    assert "sheet_output import" not in source
    template = get_template("3475")
    picker = _picker_for(template)
    center = _field_center(template, 5)
    assert picker.index_at(center) == 5
    picked: list[int] = []
    picker.start_picked.connect(picked.append)
    _press(picker, center)
    assert picked == [5]
    picker.close()


def test_picker_click_in_a_cd_hole_selects_that_label(qapp):
    template = get_template("3654")
    assert template.hole_radius_mm > 0
    picker = _picker_for(template)
    center = _field_center(template, 1)
    assert picker.index_at(center) == 1
    picked: list[int] = []
    picker.start_picked.connect(picked.append)
    _press(picker, center)
    assert picked == [1]
    picker.close()


def test_selected_cd_number_stays_visible_in_the_hole(qapp):
    from PySide6.QtGui import QImage, QPalette

    template = get_template("3654")
    picker = _picker_for(template)
    picker.set_start(1)
    image = QImage(picker.size(), QImage.Format.Format_RGB32)
    picker.render(image)
    center = _field_center(template, 1)
    palette = picker.palette()
    paper = palette.color(QPalette.ColorRole.Base)
    accent = palette.color(QPalette.ColorRole.Highlight)
    white = palette.color(QPalette.ColorRole.HighlightedText)
    span = int(template.hole_radius_mm * 0.85)
    cx, cy = int(center.x()), int(center.y())
    best = paper
    best_gap = -1
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            if dx * dx + dy * dy > span * span:
                continue
            color = image.pixelColor(cx + dx, cy + dy)
            gap = (
                abs(color.red() - paper.red())
                + abs(color.green() - paper.green())
                + abs(color.blue() - paper.blue())
            )
            if gap > best_gap:
                best_gap = gap
                best = color

    def channel_gap(left, right) -> int:
        return (
            abs(left.red() - right.red())
            + abs(left.green() - right.green())
            + abs(left.blue() - right.blue())
        )

    assert best_gap > 40
    assert channel_gap(best, accent) < channel_gap(best, white)
    picker.close()


def test_picker_height_settles_when_the_scrollbar_would_toggle(qapp):
    from PySide6.QtWidgets import QScrollArea
    from ql_editor.sheet_picker import SheetStartPicker

    template = get_template("3475")
    picker = SheetStartPicker()
    picker.set_template(template)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(picker)
    # Volle Breite wäre höher als die Fläche, die schmalere bleibt es auch.
    area.resize(220, 180)
    area.show()
    for _ in range(3):
        qapp.processEvents()
    settled = picker.height()
    for _ in range(3):
        qapp.processEvents()
    assert settled > 100
    assert picker.height() == settled
    area.close()
    picker.close()


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
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("3481"))
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
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_BROTHER))
    assert not str(window._canvas._label.identifier).startswith("zweckform")
    assert window._quality_box.isVisibleTo(panel)
    assert not window._sheet_box.isVisibleTo(media)
    assert window._media_panel._printer_box.isVisibleTo(media)
    assert not window._sheet_hint.isVisibleTo(panel)
    assert window._left_panel.title == "Band & Drucker"
    assert "Band & Drucker" in window._left_panel._button.toolTip()
    window.close()
    qapp.processEvents()


def test_sheet_picker_sets_the_first_cell_and_hides_with_brother(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPalette
    from ql_editor.app import MainWindow
    from ql_editor.stationery import OUTPUT_BROTHER, OUTPUT_SHEET

    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    qapp.processEvents()
    media = window._media_panel
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_SHEET))
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("3475"))
    qapp.processEvents()
    picker = window._sheet_picker
    assert picker.isVisibleTo(media)
    assert picker.width() > 40

    template = get_template("3475")
    scale = picker.width() / template.page_width_mm

    def center(number: int) -> QPointF:
        x_mm, y_mm = template.slot_origin(number - 1)
        return QPointF(
            (x_mm + template.label_width_mm / 2) * scale,
            (y_mm + template.label_height_mm / 2) * scale,
        )

    _press(picker, center(5))
    assert window._sheet_start.value() == 5
    assert picker.start() == 5

    window._sheet_start.setValue(4)
    qapp.processEvents()
    assert picker.start() == 4
    image = QImage(picker.size(), QImage.Format.Format_RGB32)
    picker.render(image)

    def fill_at(number: int):
        x_mm, y_mm = template.slot_origin(number - 1)
        return image.pixelColor(int(x_mm * scale) + 6, int(y_mm * scale) + 6)

    palette = picker.palette()
    highlight = palette.color(QPalette.ColorRole.Highlight)
    used = palette.color(QPalette.ColorRole.Mid)
    chosen = fill_at(4)
    skipped = fill_at(1)
    assert abs(chosen.red() - highlight.red()) <= 12
    assert abs(chosen.blue() - highlight.blue()) <= 12
    assert abs(skipped.red() - used.red()) <= 12
    assert abs(skipped.blue() - used.blue()) <= 12

    window._sheet_start.setValue(20)
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("32015"))
    qapp.processEvents()
    assert window._sheet_start.value() == 8
    assert picker.start() == 8

    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_BROTHER))
    qapp.processEvents()
    assert not window._sheet_box.isVisibleTo(media)
    assert not picker.isVisibleTo(media)
    # Die Startzahl liegt in den Einstellungen und würde den nächsten Test schieben.
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("3475"))
    window._sheet_start.setValue(1)
    window.close()
    qapp.processEvents()


def test_sheet_preview_paints_each_record(qapp, monkeypatch):
    from PIL import Image
    from ql_editor.app import MainWindow
    from ql_editor.stationery import OUTPUT_SHEET

    red = Image.new("RGB", (8, 8), "red")
    blue = Image.new("RGB", (8, 8), "blue")

    class _Variant:
        def __init__(self, index: int) -> None:
            self.record = {"n": index}
            self.index = index

    class _Planned:
        def __init__(self, index: int) -> None:
            self.serial_index = 0
            self.variant = _Variant(index)

    window = MainWindow()
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_SHEET))
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("3481"))
    window._copies_spin.setValue(1)
    labels = [_Planned(0), _Planned(1)]

    def planned():
        return labels

    def render(*, for_sheet: bool = False, only_indexes=None):
        assert for_sheet
        assert list(only_indexes) == [0, 1]
        return [red, blue]

    monkeypatch.setattr(window, "_planned_labels", planned)
    monkeypatch.setattr(window, "_render_print_images", render)
    monkeypatch.setattr(window, "_print_sheet_open", lambda: True)
    window._refresh_sheet_preview()
    preview = window._print_preview._image
    # 3481: Feld 1 bei x=0, Feld 2 bei x=70 mm. 5 mm unter dem Rand.
    assert preview.pixelColor(4, 20).red() > 200
    assert preview.pixelColor(4, 20).blue() < 40
    assert preview.pixelColor(202, 20).blue() > 200
    assert preview.pixelColor(202, 20).red() < 40
    window.close()
    qapp.processEvents()


def test_sheet_preview_names_the_first_page_when_another_follows(qapp, monkeypatch):
    from PIL import Image
    from ql_editor.app import MainWindow
    from ql_editor.stationery import OUTPUT_SHEET

    class _Planned:
        serial_index = 0

        class variant:
            record = None
            index = 0

    window = MainWindow()
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_SHEET))
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("3481"))

    def planned():
        return [_Planned()] * 25

    def render(*, for_sheet: bool = False, only_indexes=None):
        count = 1 if only_indexes is None else len(list(only_indexes))
        return [Image.new("RGB", (4, 4), "white")] * count

    monkeypatch.setattr(window, "_planned_labels", planned)
    monkeypatch.setattr(window, "_render_print_images", render)
    monkeypatch.setattr(window, "_print_sheet_open", lambda: True)
    window._refresh_sheet_preview()
    assert window._sheet_preview_page.text() == "Vorschau: Bogen 1 von 2"
    assert not window._sheet_preview_page.isHidden()
    window.close()
    qapp.processEvents()


def test_sheet_target_belongs_to_the_tab(qapp):
    from ql_editor.app import MainWindow
    from ql_editor.stationery import OUTPUT_BROTHER, OUTPUT_SHEET

    window = MainWindow()
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_SHEET))
    window._sheet_part_combo.setCurrentIndex(window._sheet_part_combo.findData("3481"))
    window._create_tab()
    assert window._sheet_output()
    assert window._sheet_part_combo.currentData() == "3481"
    window._output_combo.setCurrentIndex(window._output_combo.findData(OUTPUT_BROTHER))
    window._tab_bar.setCurrentIndex(0)
    assert window._sheet_output()
    assert window._sheet_part_combo.currentData() == "3481"
    assert window._canvas._label.width_dots == mm_to_dots(70)
    window._tab_bar.setCurrentIndex(1)
    assert not window._sheet_output()
    assert not str(window._canvas._label.identifier).startswith("zweckform")
    window.close()
    qapp.processEvents()


def test_sheet_history_stores_copies_and_the_cell_count(qapp):
    from ql_editor.app import MainWindow

    window = MainWindow()
    window._remember_sheet_job("Office", 24, "sent", copies=3, part="3475")
    job = window._print_jobs[-1]
    assert job.copies == 3
    assert job.label == "Zweckform 3475 · 24 Etiketten"
    assert job.outcome == "sent"
    window.close()
    qapp.processEvents()


def test_sheet_worker_prints_off_the_gui_thread(qapp, monkeypatch):
    import threading

    from ql_editor.app import SheetOutputWorker

    seen: dict[str, object] = {}

    def fake(name, template, images, placements, **kwargs):
        seen["name"] = name
        seen["thread"] = threading.current_thread()
        seen["cells"] = len(placements)

    monkeypatch.setattr("ql_editor.app.print_sheets", fake)
    template = get_template("3481")
    worker = SheetOutputWorker(
        kind="print",
        template=template,
        images=[Image.new("RGB", (2, 2), "red")],
        placements=plan_sheet(template, 1),
        offset_x=1.0,
        offset_y=0.0,
        printer_name="Office",
    )
    worker.start()
    assert worker.wait(5000)
    assert seen["name"] == "Office"
    assert seen["cells"] == 1
    assert seen["thread"] is not threading.main_thread()
