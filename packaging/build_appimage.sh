#!/usr/bin/env bash
#
# Baut das AppImage (M4.3).
#
#   packaging/build_appimage.sh
#
# Ablauf: PyInstaller-Bundle -> AppDir (Programm + Desktop-Datei + Symbol)
# -> appimagetool -> dist/QLInux-<version>-x86_64.AppImage.
#
# appimagetool wird einmalig nach packaging/.cache/ geladen (nicht im Repo).
# Es braucht FUSE nur zum *Start*: hier laeuft es mit
# --appimage-extract-and-run, damit auch Rechner ohne FUSE bauen koennen.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/packaging/out"
CACHE="$ROOT/packaging/.cache"
APPDIR="$OUT/AppDir"
VERSION="$("$PY" -c 'import ql_editor; print(ql_editor.__version__)')"
APPIMAGE="$ROOT/dist/QLInux-${VERSION}-x86_64.AppImage"

echo "==> Version $VERSION"

echo "==> App-Symbol"
"$PY" "$ROOT/packaging/make_icon.py"

echo "==> PyInstaller"
rm -rf "$OUT"
mkdir -p "$OUT"
cd "$ROOT"
"$ROOT/.venv/bin/pyinstaller" \
    --noconfirm --clean --log-level WARN \
    --distpath "$OUT" --workpath "$OUT/build" \
    "$ROOT/packaging/ql_editor.spec"
# PyInstaller legt das Verzeichnis nach seinem Namen ab.
mv "$OUT/ql-editor" "$OUT/bundle"

echo "==> AppDir"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"
mv "$OUT/bundle" "$APPDIR/usr/lib/ql-editor"
install -m 0755 "$ROOT/packaging/AppRun" "$APPDIR/AppRun"
install -m 0755 "$ROOT/packaging/ql-editor" "$APPDIR/usr/bin/ql-editor"
install -m 0644 "$ROOT/packaging/ql-editor.desktop" "$APPDIR/ql-editor.desktop"
install -m 0644 "$ROOT/packaging/ql-editor.desktop" \
    "$APPDIR/usr/share/applications/ql-editor.desktop"
install -m 0644 "$ROOT/assets/ql-editor.png" "$APPDIR/ql-editor.png"
install -m 0644 "$ROOT/assets/ql-editor.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/ql-editor.png"

echo "==> appimagetool"
mkdir -p "$CACHE"
TOOL="$CACHE/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

echo "==> AppImage"
mkdir -p "$ROOT/dist"
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE"

echo
echo "fertig: $APPIMAGE ($(du -h "$APPIMAGE" | cut -f1))"
echo "starten:  $APPIMAGE"
