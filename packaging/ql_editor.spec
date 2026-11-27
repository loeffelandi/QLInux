# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller-Rezept fuer das AppImage (onedir) und, auf dem Mac, fuer
# QLInux.app. Aufruf ueber packaging/build_appimage.sh bzw.
# packaging/build_macos.sh - nicht direkt noetig.
import ctypes.util
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# Mitgelieferte Dateien: ql_editor.resources sucht sie im Bundle unter
# ``sys._MEIPASS/assets`` (App-Symbol im Fenster). Pfade relativ zur Spec.
datas = [
    ("../assets/ql-editor.png", "assets"),
    ("../ql_editor/data/zweckform-iso-templates.xml", "ql_editor/data"),
]

# Auf dem Mac gehoert libusb ins Bundle: Homebrew ist beim Nutzer nicht da.
# Die Datei kommt aus Homebrew (oder LIBUSB_DYLIB); ohne sie bricht der Bau ab.
binaries = []
if sys.platform == "darwin":
    # Symbole der Dateitypen (Info.plist verweist auf sie im Resources-Ordner).
    datas += [
        ("../assets/mimetypes/application-x-qlinux-label.icns", "."),
        ("../assets/mimetypes/application-x-brother-lbx.icns", "."),
    ]
    libusb = os.environ.get("LIBUSB_DYLIB") or ctypes.util.find_library("usb-1.0")
    if not libusb or not os.path.isfile(libusb):
        raise SystemExit("libusb fehlt: brew install libusb (oder LIBUSB_DYLIB setzen)")
    binaries.append((os.path.realpath(libusb), "."))

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
    "certifi",
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
    binaries=binaries,
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

if sys.platform == "darwin":
    import re

    # Der Wert steht in der Version von ql_editor/__init__.py.
    with open(os.path.join(SPECPATH, "..", "ql_editor", "__init__.py"), encoding="utf-8") as handle:
        version = re.search(r'__version__ = "([^"]+)"', handle.read()).group(1)

    import subprocess

    def _minimum_macos(entries):
        """Hoechstes ``minos`` aller Mach-O-Dateien im Bundle (``LC_BUILD_VERSION``).

        Das Bundle laeuft erst ab der neuesten Mindestversion seiner Teile;
        PySide6-Bindungen und ein lokal gebautes libusb liegen oft hoeher als
        die Qt-Bibliotheken.
        """
        newest = ()
        for entry in entries:
            source = entry[1]
            if not os.path.isfile(source):
                continue
            result = subprocess.run(
                ["otool", "-l", source], capture_output=True, text=True, check=False
            )
            seen = False
            for line in result.stdout.splitlines():
                if "LC_BUILD_VERSION" in line:
                    seen = True
                elif seen and line.split()[:1] == ["minos"]:
                    parts = tuple(int(x) for x in line.split()[1].split("."))
                    newest = max(newest, parts)
                    seen = False
        if not newest:
            raise SystemExit("Mindest-macOS des Bundles nicht lesbar (otool)")
        return ".".join(str(x) for x in newest)

    def _document_type(name, extension, icon, rank):
        return {
            "CFBundleTypeName": name,
            "CFBundleTypeExtensions": [extension],
            "CFBundleTypeIconFile": icon,
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": rank,
        }

    app = BUNDLE(
        coll,
        name="QLInux.app",
        icon="../assets/ql-editor.icns",
        bundle_identifier="io.github.loeffelandi.QLInux",
        version=version,
        info_plist={
            "CFBundleName": "QLInux",
            "CFBundleDisplayName": "QLInux",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": _minimum_macos(a.binaries),
            "LSApplicationCategoryType": "public.app-category.graphics-design",
            "NSLocalNetworkUsageDescription": (
                "QLInux sucht Brother-Drucker im lokalen Netz und sendet ihnen "
                "die Etiketten."
            ),
            "NSBonjourServices": ["_pdl-datastream._tcp"],
            "CFBundleDocumentTypes": [
                _document_type(
                    "QLInux-Etikett", "qlx", "application-x-qlinux-label.icns", "Owner"
                ),
                _document_type(
                    "Brother-P-touch-Etikett",
                    "lbx",
                    "application-x-brother-lbx.icns",
                    "Alternate",
                ),
            ],
        },
    )
