"""Datum/Uhrzeit: Formate, Versatz, aktuelle Zeit, Inspector."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QCheckBox, QComboBox

from ql_editor import i18n
from ql_editor.canvas import LabelCanvas
from ql_editor.datetime_text import (
    DATE_FORMATS,
    format_date,
    format_stamp,
    format_time,
    shift,
)
from ql_editor.items import DateTimeItem, item_from_dict
from ql_editor.media import get_label

WHEN = datetime(2026, 10, 18, 16, 47, 3)


def test_formats_follow_the_ui_language():
    assert format_date(WHEN, "dmy_dot") == "18.10.2026"
    assert format_date(WHEN, "ymd_slash") == "2026/10/18"
    assert format_date(WHEN, "long") == "18. Oktober 2026"
    assert format_date(WHEN, "weekday") == "Sonntag, 18. Oktober 2026"
    assert format_time(WHEN, "hm") == "16:47"
    assert format_time(WHEN, "hms") == "16:47:03"
    assert format_time(WHEN, "hm12") == "4:47 PM"
    assert format_time(WHEN.replace(hour=0, minute=5), "hm12") == "12:05 AM"
    assert format_stamp(WHEN, "both", "dmy_dot", "hm") == "18.10.2026 16:47"
    assert format_stamp(WHEN, "time", "dmy_dot", "hm") == "16:47"

    i18n.set_language("en")
    try:
        assert format_date(WHEN, "long") == "18. October 2026"
        assert format_date(WHEN, "weekday") == "Sunday, 18. October 2026"
    finally:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_shift_keeps_a_real_day_of_the_month():
    assert shift(WHEN, 2, "hours") == WHEN.replace(hour=18)
    assert shift(WHEN, -1, "days") == datetime(2026, 10, 17, 16, 47, 3)
    assert shift(datetime(2026, 1, 31), 1, "months") == datetime(2026, 2, 28)
    assert shift(datetime(2024, 1, 31), 1, "months") == datetime(2024, 2, 29)
    assert shift(datetime(2026, 3, 31), -1, "months") == datetime(2026, 2, 28)
    assert shift(datetime(2026, 1, 15), -1, "months") == datetime(2025, 12, 15)
    assert shift(WHEN, 1, "years").year == 2027
    assert shift(WHEN, 0, "days") == WHEN


def test_underline_roundtrip_matches_bold_and_italic(qapp):
    item = DateTimeItem()
    assert item.underline is False
    item.set_bold(True)
    item.set_italic(True)
    item.set_underline(True)
    assert item.font().bold() and item.font().italic() and item.font().underline()
    restored = item_from_dict(item.to_dict())
    assert restored.bold and restored.italic and restored.underline
    assert restored.font().underline()


def test_live_clock_is_not_stored_but_a_fixed_date_is(qapp):
    item = DateTimeItem()
    item.set_mode("date")
    item.set_date_format("iso")
    item.set_offset(0, "days")
    item.refresh(now=WHEN)
    assert item.toPlainText() == "2026-10-18"
    stored = item.to_dict()
    item.refresh(now=datetime(2030, 1, 1, 8, 0))
    assert item.toPlainText() == "2030-01-01"
    assert item.to_dict() == stored

    item.set_live(False)
    item.set_fixed(datetime(2020, 5, 6, 7, 8, 9))
    item.refresh(now=datetime(2030, 1, 1))
    assert item.toPlainText() == "2020-05-06"
    assert "2020-05-06T07:08:09" in item.to_dict()["fixed"]


def test_offset_roundtrip_and_unknown_values(qapp):
    item = DateTimeItem()
    item.set_live(False)
    item.set_fixed(WHEN)
    item.set_mode("both")
    item.set_date_format("ymd_slash")
    item.set_time_format("hm")
    item.set_offset(-13, "days")
    assert item.toPlainText() == "2026/10/05 16:47"

    restored = item_from_dict(item.to_dict())
    assert isinstance(restored, DateTimeItem)
    assert restored.toPlainText() == "2026/10/05 16:47"
    assert restored.offset == -13
    assert restored.offset_unit == "days"
    assert restored.live is False

    item.set_date_format("nope")
    item.set_mode("nope")
    item.set_offset(2, "fortnights")
    assert item.date_format == "dmy_dot"
    assert item.mode == "both"
    assert item.offset_unit == "days"
    assert item.offset == 2


def test_render_has_ink_and_no_selection_chrome(qapp):
    canvas = LabelCanvas()
    canvas.resize(400, 300)
    canvas.show()
    qapp.processEvents()
    canvas.set_label(get_label("50"), 400)
    item = DateTimeItem(font_pixel_size=64)
    item.set_live(False)
    item.set_fixed(WHEN)
    item.set_mode("date")
    item.set_date_format("dmy_dot")
    canvas.add_item(item)
    item.setPos(8, 8)
    item.setSelected(True)
    image = canvas.render_printable()
    dark = blue = 0
    for pixel in image.getdata():
        red, green, blue_channel = pixel[:3]
        if red < 40 and green < 40 and blue_channel < 40:
            dark += 1
        if blue_channel > 150 and red < 80 and green < 160:
            blue += 1
    assert dark > 20
    assert blue == 0
    assert item.toPlainText() == "18.10.2026"


def test_main_window_inserts_a_current_stamp_and_undoes_the_format(qapp):
    from ql_editor.app import MainWindow

    win = MainWindow()
    # Schmaler als AUTO_COLLAPSE_RIGHT_PX klappt der Inspector zu. 1100 px
    # liegt darunter; sichtbar ist der Inhalt dann nur mitten in der Animation.
    win.resize(1400, 860)
    win.show()
    qapp.processEvents()
    win._act_add_datetime.trigger()
    qapp.processEvents()
    stamps = [it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "datetime"]
    assert len(stamps) == 1
    assert stamps[0].live
    assert stamps[0].mode == "both"
    assert win._inspector._title.text() == "Datum/Uhrzeit"
    checks = [
        box
        for box in win._inspector.findChildren(QCheckBox)
        if box.text() == "Aktuell" and box.isVisible()
    ]
    assert len(checks) == 1 and checks[0].isChecked()

    combo = next(
        box
        for box in win._inspector.findChildren(QComboBox)
        if box.isVisible() and box.count() == len(DATE_FORMATS)
    )
    combo.setCurrentIndex(1)
    qapp.processEvents()
    stamp = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "datetime")
    assert stamp.date_format == "ymd_slash"
    assert "/" in stamp.toPlainText()
    assert stamp.align == "left"
    # Inspector bietet Textausrichtung wie bei Text (wirkt mit text_width).
    from PySide6.QtWidgets import QToolButton

    align_buttons = [
        button
        for button in win._inspector.findChildren(QToolButton)
        if button.toolTip() in ("Links", "Mitte", "Rechts") and button.isCheckable()
    ]
    assert len(align_buttons) >= 3
    center = next(button for button in align_buttons if button.toolTip() == "Mitte")
    center.click()
    qapp.processEvents()
    stamp = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "datetime")
    assert stamp.align == "center"

    win._act_undo.trigger()
    qapp.processEvents()
    stamp = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "datetime")
    assert stamp.align == "left"
    win._act_undo.trigger()
    qapp.processEvents()
    stamp = next(it for it in win._canvas.scene().items() if getattr(it, "kind", None) == "datetime")
    assert stamp.date_format == "dmy_dot"
