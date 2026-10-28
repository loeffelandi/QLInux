"""Tests fuer Binding-Felder an Text/Barcode/QR (M1, D4)."""

from __future__ import annotations

import pytest
from ql_editor.items import (
    BarcodeItem,
    QRItem,
    TextItem,
    item_from_dict,
    normalize_binding,
)

pytestmark = pytest.mark.usefixtures("qapp")


def test_normalize_binding_database_and_serial():
    assert normalize_binding({"source": "database", "field": "Circuit"}) == {
        "source": "database",
        "field": "Circuit",
    }
    assert normalize_binding({"source": "serial"}) == {"source": "serial"}
    assert normalize_binding(None) is None
    assert normalize_binding({"source": "none"}) is None


def test_normalize_binding_rejects_invalid():
    with pytest.raises(ValueError):
        normalize_binding({"source": "database"})
    with pytest.raises(ValueError):
        normalize_binding({"source": "other"})


def test_text_binding_round_trip():
    item = TextItem("Snapshot")
    item.set_binding({"source": "database", "field": "Fixture"})

    restored = item_from_dict(item.to_dict())

    assert restored.toPlainText() == "Snapshot"
    assert restored.binding == {"source": "database", "field": "Fixture"}


def test_text_without_binding_omits_key():
    data = TextItem("Hallo").to_dict()

    assert "binding" not in data
    assert item_from_dict(data).binding is None


def test_barcode_and_qr_binding_round_trip():
    barcode = BarcodeItem("123456789")
    barcode.set_binding({"source": "serial"})
    qr = QRItem("https://example.org")
    qr.set_binding({"source": "database", "field": "Patch"})

    assert item_from_dict(barcode.to_dict()).binding == {"source": "serial"}
    assert item_from_dict(qr.to_dict()).binding == {
        "source": "database",
        "field": "Patch",
    }


def test_clear_binding():
    item = TextItem("x")
    item.set_binding({"source": "database", "field": "A"})
    item.clear_binding()

    assert item.binding is None
    assert "binding" not in item.to_dict()
