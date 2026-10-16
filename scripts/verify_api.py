#!/usr/bin/env python3
"""Dokumentiert die real vorhandenen API-Signaturen der installierten brother_ql.

Ersetzt die manuellen ``help()``-Aufrufe aus der Aufgabe durch eine
reproduzierbare, maschinenlesbare Ausgabe. Aufruf:

    source .venv/bin/activate
    python scripts/verify_api.py
"""
from __future__ import annotations

import inspect
import json
from enum import Enum

import brother_ql


def _jsonable(value):
    if isinstance(value, Enum):
        return f"{value.__class__.__name__}.{value.name}"
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> int:
    section("brother_ql Version / Pfad")
    print("file:      ", brother_ql.__file__)
    print("__version__:", getattr(brother_ql, "__version__", "(kein __version__-Attribut)"))
    try:
        from importlib.metadata import version
        print("dist-info: ", version("brother_ql"))
    except Exception as exc:  # pragma: no cover
        print("dist-info: ", exc)

    section("Module: labels / models (moderne Quelle)")
    from brother_ql.labels import LabelsManager, FormFactor, Color
    from brother_ql.models import ModelsManager
    label_ids = list(LabelsManager().iter_identifiers())
    model_ids = list(ModelsManager().iter_identifiers())
    print("labels: ", label_ids)
    print("models: ", model_ids)
    print("FormFactor:", [m.name for m in FormFactor])
    print("Color:     ", [m.name for m in Color])

    section("label_type_specs['50'] (via devicedependent-Shim)")
    from brother_ql.devicedependent import label_type_specs
    print(json.dumps(_jsonable(label_type_specs["50"]), indent=2, ensure_ascii=False))

    section("API-Signaturen")
    from brother_ql.raster import BrotherQLRaster
    from brother_ql.conversion import convert
    from brother_ql.backends.helpers import send
    print("BrotherQLRaster.__init__", inspect.signature(BrotherQLRaster.__init__))
    print("convert", inspect.signature(convert))
    print("send   ", inspect.signature(send))

    section("Laufzeit-Check (Kernprinzip)")
    model = "QL-820NWB"
    qlr = BrotherQLRaster(model=model)
    print("model:              ", model)
    print("two_color_support:  ", qlr.two_color_support)
    print("get_pixel_width():  ", qlr.get_pixel_width())
    print("dots_printable '50':", label_type_specs["50"]["dots_printable"])

    section("backend 'network'")
    from brother_ql.backends import backend_factory
    be = backend_factory("network")
    print("network backend class:", be["backend_class"].__name__)

    section("LANCZOS-Patch aktiv?")
    import brother_ql.conversion as conv
    src = inspect.getsource(conv.convert)
    print("Image.LANCZOS vorhanden:  ", "Image.LANCZOS" in src)
    print("Image.ANTIALIAS vorhanden:", "Image.ANTIALIAS" in src)

    print("\nOK - API-Verifikation abgeschlossen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
