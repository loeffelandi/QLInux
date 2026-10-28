# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller-Rezept fuer das AppImage (onedir). Aufruf ueber
# packaging/build_appimage.sh - nicht direkt noetig.
import os

from PyInstaller.utils.hooks import collect_submodules

# Mitgelieferte Dateien: ql_editor.resources sucht sie im Bundle unter
# ``sys._MEIPASS/assets`` (App-Symbol im Fenster). Pfade relativ zur Spec.
datas = [
    ("../assets/ql-editor.png", "assets"),
    ("../ql_editor/data/zweckform-iso-templates.xml", "ql_editor/data"),
]

hidden = [
    "brother_ql",
    "brother_ql.backends",
    "brother_ql.backends.helpers",
    "brother_ql.backends.pyusb",
    "brother_ql.backends.network",
    "brother_ql.backends.linux_kernel",
    "brother_ql.conversion",
    "brother_ql.raster",
    "brother_ql.labels",
    "brother_ql.models",
    "brother_ql.reader",
    "PySide6.QtPrintSupport",
    "PIL",
    "PIL.Image",
    "qrcode",
    "barcode",
    "usb",
    "usb.core",
    "usb.util",
]
hidden += collect_submodules("ql_editor")

# Qt-Module, die die App nie nutzt - ohne sie waere das AppImage deutlich groesser.
excludes = [
    "PySide6.QtWebEngine",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSql",
    "PySide6.QtCharts",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    "tkinter",
    "matplotlib",
]

a = Analysis(
    ["entrypoint.py"],
    pathex=[os.path.abspath(os.path.join(SPECPATH, ".."))],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ql-editor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ql-editor",
)
