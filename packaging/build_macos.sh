#!/usr/bin/env bash
#
# Baut QLInux.app und das .dmg fuer Apple Silicon.
#
#   packaging/build_macos.sh
#
# Ablauf: Symbole -> PyInstaller (QLInux.app, libusb im Bundle) -> Pruefung
# (libusb im Bundle, kein Homebrew-Pfad) -> dist/QLInux-<version>-arm64.dmg.
#
# Voraussetzungen: Apple Silicon, ``brew install libusb`` (nur zum Bauen; das
# .app bringt libusb selbst mit) und ``bash scripts/bootstrap_venv.sh``.
# Das .app ist nicht notarisiert; PyInstaller signiert es ad hoc, weil arm64
# ohne Signatur nicht startet. Beim ersten Start bestaetigt der Nutzer es in
# den Systemeinstellungen (siehe README).
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
    echo "Nur auf macOS mit Apple Silicon (arm64) moeglich, gefunden: $(uname -s) $(uname -m)" >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/packaging/out"
VERSION="$("$PY" -c 'import ql_editor; print(ql_editor.__version__)')"
APP="$OUT/QLInux.app"
DMG="$ROOT/dist/QLInux-${VERSION}-arm64.dmg"

LIBUSB="${LIBUSB_DYLIB:-}"
if [ -z "$LIBUSB" ]; then
    LIBUSB="$("$PY" -c 'import ctypes.util; print(ctypes.util.find_library("usb-1.0") or "")')"
fi
# Ein Python von python.org oder setup-python sucht nicht in Homebrew.
if [ -z "$LIBUSB" ] || [ ! -f "$LIBUSB" ]; then
    PREFIX="$(brew --prefix libusb 2>/dev/null || true)"
    LIBUSB=""
    for candidate in "$PREFIX/lib/libusb-1.0.dylib" /opt/homebrew/lib/libusb-1.0.dylib; do
        if [ -f "$candidate" ]; then
            LIBUSB="$candidate"
            break
        fi
    done
fi
if [ -z "$LIBUSB" ] || [ ! -f "$LIBUSB" ]; then
    echo "libusb fehlt. Installieren mit: brew install libusb" >&2
    exit 1
fi
export LIBUSB_DYLIB="$LIBUSB"

echo "==> Version $VERSION (arm64), libusb: $LIBUSB"

echo "==> Symbole"
"$PY" "$ROOT/packaging/make_icon.py"

echo "==> PyInstaller"
rm -rf "$OUT"
mkdir -p "$OUT"
cd "$ROOT"
"$ROOT/.venv/bin/pyinstaller" \
    --noconfirm --clean --log-level WARN \
    --distpath "$OUT" --workpath "$OUT/build" \
    "$ROOT/packaging/ql_editor.spec"

if [ ! -d "$APP" ]; then
    echo "QLInux.app wurde nicht erzeugt" >&2
    exit 1
fi

echo "==> Pruefung"
BIN="$APP/Contents/MacOS/ql-editor"
LIB_IN_APP="$(find "$APP" -name 'libusb-1.0*.dylib' | head -n 1)"
if [ -z "$LIB_IN_APP" ]; then
    echo "libusb steckt nicht im Bundle" >&2
    exit 1
fi
echo "libusb im Bundle: ${LIB_IN_APP#"$APP"/}"
if otool -L "$LIB_IN_APP" | tail -n +2 | grep -E '/(opt/homebrew|usr/local)/'; then
    echo "libusb verweist noch auf einen Homebrew-Pfad" >&2
    exit 1
fi
if ! lipo -archs "$BIN" | grep -qw arm64; then
    echo "Programm ist nicht arm64: $(lipo -archs "$BIN")" >&2
    exit 1
fi
codesign --verify --deep "$APP"
echo "Mindest-macOS: $(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$APP/Contents/Info.plist")"

echo "==> Selbsttest ohne Homebrew-Pfad"
# Die Probe laedt das gebuendelte libusb ueber pyusb, ohne dass die
# Umgebung auf Homebrew zeigt; fehlt sie, scheitert der Bau hier.
PROBE="$(env -i HOME="$HOME" PATH="/usr/bin:/bin" QT_QPA_PLATFORM=offscreen \
    QLINUX_SELFTEST=libusb "$BIN")"
echo "$PROBE"
case "$PROBE" in
    *"$APP/"*) ;;
    *)
        echo "pyusb laedt libusb nicht aus dem Bundle" >&2
        exit 1
        ;;
esac
# Die Update-Suche braucht die Zertifikatsliste im Bundle (docs/adr/0024).
PROBE="$(env -i HOME="$HOME" PATH="/usr/bin:/bin" QT_QPA_PLATFORM=offscreen \
    QLINUX_SELFTEST=certifi "$BIN")"
echo "$PROBE"
case "$PROBE" in
    *"$APP/"*) ;;
    *)
        echo "cacert.pem liegt nicht im Bundle" >&2
        exit 1
        ;;
esac

echo "==> .dmg"
mkdir -p "$ROOT/dist"
rm -f "$DMG"
STAGE="$OUT/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "QLInux $VERSION" -srcfolder "$STAGE" \
    -fs HFS+ -format UDZO -ov "$DMG" >/dev/null

# Die Ablage enthaelt einen Link auf /Programme: nicht liegen lassen.
rm -rf "$STAGE"

echo "==> fertig: $DMG"
