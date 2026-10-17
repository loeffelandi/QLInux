"""Tests fuer das Datenmodell (:mod:`ql_editor.media`).

Diese Tests laufen headless (keine Qt-, keine Druckerabhaengigkeit).
"""

from __future__ import annotations

import pytest

from ql_editor import media
from ql_editor.media import (
    Color,
    Kind,
    Margins,
    canvas_size_dots,
    get_label,
    get_model,
    labels_for_model,
    mm_to_dots,
)

MODEL = "QL-820NWB"

# Kontrollwerte aus der Aufgabenstellung (nur zur Verifikation - der Code
# liest die Werte dynamisch aus der Bibliothek, nicht aus dieser Tabelle).
EXPECTED_WIDTHS = {
    "12": 106,
    "29": 306,
    "38": 413,
    "50": 554,
    "54": 590,
    "62": 696,
    "102": 1164,
}


def test_mm_to_dots_conversion():
    assert media.DOTS_PER_MM == pytest.approx(11.811, abs=1e-3)
    assert mm_to_dots(40) == 472  # 40 mm * 300 / 25.4
    assert mm_to_dots(0) == 0


def test_negative_length_rejected():
    with pytest.raises(ValueError):
        mm_to_dots(-1)


def test_known_printable_widths():
    for identifier, expected_px in EXPECTED_WIDTHS.items():
        assert get_label(identifier).width_dots == expected_px, identifier


def test_model_lookup_and_device_width():
    model = get_model(MODEL)
    assert model.device_pixel_width == 720  # 90 bytes/row * 8
    assert model.two_color is True
    assert model.cutting is True


def test_unknown_lookups_raise():
    with pytest.raises(KeyError):
        get_label("does-not-exist")
    with pytest.raises(KeyError):
        get_model("QL-NOPE")


def test_restricted_label_filtered_for_model():
    ids_820 = {lbl.identifier for lbl in labels_for_model(MODEL)}
    assert "50" in ids_820
    # 102 mm ist auf QL-1050/QL-1060N beschraenkt.
    assert "102" not in ids_820
    assert get_label("102").usable_by("QL-1050")
    assert not get_label("102").usable_by(MODEL)


def test_unrestricted_label_usable_by_all():
    # Leere restrict-Liste bedeutet "fuer alle Modelle".
    assert get_label("50").restricted_to_models == ()
    assert get_label("50").usable_by("QL-500")
    assert get_label("50").usable_by(MODEL)


def test_two_color_label_flagged():
    red = get_label("62red")
    assert red.color is Color.BLACK_RED_WHITE
    assert red.color.supports_red
    assert not get_label("62").color.supports_red


def test_label_kinds():
    assert get_label("50").kind is Kind.ENDLESS
    assert get_label("62x100").kind is Kind.DIE_CUT
    assert get_label("d24").kind is Kind.ROUND_DIE_CUT
    assert get_label("50").is_endless is True
    assert get_label("62x100").kind.is_fixed_size is True


# --- Definition of Done #2: 50 mm endlos, feste Laenge 40 mm -> 554 x 472 px ---
def test_dod2_fixed_length_canvas_size():
    label = get_label("50")
    model = get_model(MODEL)
    size = canvas_size_dots(label, model, auto_length=False, fixed_length_mm=40)
    assert size == (554, 472)


def test_die_cut_canvas_size_is_band_size():
    label = get_label("62x100")
    model = get_model(MODEL)
    # auto_length/fixed werden bei Die-cut ignoriert.
    assert canvas_size_dots(label, model, auto_length=True) == (696, 1109)
    assert canvas_size_dots(label, model, auto_length=False, fixed_length_mm=5) == (696, 1109)


def test_auto_length_uses_minimum_when_empty():
    label = get_label("50")
    model = get_model(MODEL)
    lo, _hi = model.min_max_length_dots
    assert canvas_size_dots(label, model, auto_length=True, content_length_dots=0) == (554, lo)


def test_length_is_clamped_to_model_bounds():
    label = get_label("50")
    model = get_model(MODEL)
    lo, hi = model.min_max_length_dots
    assert canvas_size_dots(label, model, auto_length=True, content_length_dots=1)[1] == lo
    assert canvas_size_dots(label, model, auto_length=True, content_length_dots=10_000_000)[1] == hi


def test_default_margins_are_zero():
    """Ränder stehen standardmaessig auf 0 - Vorschub und Seitenrand sind
    schon automatisch drin (Bandbreite und Bandlaenge), nicht als Rand."""
    label = get_label("50")
    assert label.feed_margin == 35  # der Vorschub ist vorhanden ...
    margins = label.default_margins()
    assert isinstance(margins, Margins)
    assert margins == Margins(left=0.0, right=0.0, top=0.0, bottom=0.0)  # ... aber kein Rand


# --- Laengen-Kompensation (Gesamtlaenge statt Inhalt) ---
def test_printer_extra_dots_for_endless():
    # 2 * feed_margin(35) + CUT_OFFSET_DOTS(13) = 83 Dots ~ 7,0 mm
    assert media.printer_extra_dots(get_label("50")) == 83
    assert media.dots_to_mm(83) == pytest.approx(7.03, abs=0.05)


def test_printer_extra_dots_zero_for_die_cut():
    assert media.printer_extra_dots(get_label("62x100")) == 0
    assert media.printer_extra_dots(get_label("d24")) == 0


def test_finished_length_mode_reduces_content():
    label = get_label("50")
    model = get_model(MODEL)
    # 40 mm Gesamtlaenge -> 472 - 83 = 389 Dots Inhalt, Breite bleibt 554.
    size = media.canvas_size_dots(
        label, model, auto_length=False, fixed_length_mm=40,
        length_mode=media.LengthMode.FINISHED,
    )
    assert size == (554, 389)


def test_content_mode_is_unchanged_dod2():
    label = get_label("50")
    model = get_model(MODEL)
    size = media.canvas_size_dots(
        label, model, auto_length=False, fixed_length_mm=40,
        length_mode=media.LengthMode.CONTENT,
    )
    assert size == (554, 472)


def test_finished_length_roundtrip():
    label = get_label("50")
    model = get_model(MODEL)
    content = media.content_dots_for_finished_length(label, model, 40)
    assert content == 389
    assert media.finished_length_mm(label, content) == pytest.approx(40.0, abs=0.1)


def test_finished_length_mode_ignored_for_die_cut():
    label = get_label("62x100")
    model = get_model(MODEL)
    size = media.canvas_size_dots(
        label, model, auto_length=False, fixed_length_mm=40,
        length_mode=media.LengthMode.FINISHED,
    )
    assert size == (696, 1109)


# --- Ausrichtung (quer / laengs des Bandes) ---
def test_orientation_flags():
    assert media.Orientation.ACROSS.rotates_for_print is False
    assert media.Orientation.ALONG.rotates_for_print is True
    assert media.Orientation.ACROSS.label_de == "quer zum Band"
    assert media.Orientation.ALONG.label_de == "längs des Bandes"


def test_canvas_size_for_orientation_swaps_axes():
    label = get_label("50")
    assert media.canvas_size_for_orientation(label, 472) == (554, 472)
    assert media.canvas_size_for_orientation(
        label, 472, media.Orientation.ALONG
    ) == (472, 554)


def test_canvas_size_along_puts_length_on_width():
    label = get_label("50")
    model = get_model(MODEL)
    size = media.canvas_size_dots(
        label,
        model,
        auto_length=False,
        fixed_length_mm=40,
        orientation=media.Orientation.ALONG,
    )
    # Gleiche Laenge (472) wie DoD #2 - nur auf der anderen Achse.
    assert size == (472, 554)


def test_canvas_size_along_contains_printable_width():
    label = get_label("50")
    model = get_model(MODEL)
    width, height = media.canvas_size_dots(
        label, model, auto_length=True, content_length_dots=300,
        orientation=media.Orientation.ALONG,
    )
    assert width == 300
    assert height == label.width_dots


def test_label_length_dots_is_orientation_independent():
    label = get_label("50")
    model = get_model(MODEL)
    assert media.label_length_dots(
        label, model, auto_length=True, content_length_dots=300
    ) == 300
    assert media.label_length_dots(
        label, model, auto_length=False, fixed_length_mm=40
    ) == 472


def test_die_cut_orientation_swaps_axes():
    label = get_label("62x100")
    model = get_model(MODEL)
    assert media.canvas_size_dots(
        label, model, orientation=media.Orientation.ALONG
    ) == (1109, 696)
