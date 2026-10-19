#!/usr/bin/env bash
#
# Baut das AppImage (M4.3).
#
#   packaging/build_appimage.sh
#
# Ablauf: PyInstaller-Bundle -> AppDir (Programm + Desktop-Datei + Symbol)
# -> appimagetool -> dist/QLInux-<version>-<arch>.AppImage.
#
# Die Architektur kommt von uname -m (x86_64 oder aarch64). appimagetool
# wird einmalig nach packaging/.cache/ geladen (nicht im Repo). Es braucht
# FUSE nur zum *Start*: hier laeuft es mit --appimage-extract-and-run,
# damit auch Rechner ohne FUSE bauen koennen.
#
# Build-Host braucht die Qt/XCB-Systemlibs (u. a. libxcb-cursor0,
# libxkbcommon-x11-0, libxcb-icccm4, …). PyInstaller packt nur, was es
# finden kann - fehlen sie, startet das AppImage ohne xcb-Plugin.
set -euo pipefail

_missing=()
for _lib in libxcb-cursor.so.0 libxkbcommon-x11.so.0 libxcb-icccm.so.4; do
    if ! ldconfig -p 2>/dev/null | grep -q "$_lib"; then
        _missing+=("$_lib")
    fi
done
if [ "${#_missing[@]}" -gt 0 ]; then
    echo "Fehlende Build-Libs (werden sonst nicht ins AppImage gepackt): ${_missing[*]}" >&2
    echo "Debian/Ubuntu: sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1" >&2
    exit 1
fi
unset _missing _lib

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
OUT="$ROOT/packaging/out"
CACHE="$ROOT/packaging/.cache"
APPDIR="$OUT/AppDir"
VERSION="$("$PY" -c 'import ql_editor; print(ql_editor.__version__)')"

case "$(uname -m)" in
    x86_64) ARCH=x86_64 ;;
    aarch64|arm64) ARCH=aarch64 ;;
    *)
        echo "Nicht unterstuetzte Architektur: $(uname -m) (erwartet: x86_64 oder aarch64)" >&2
        exit 1
        ;;
esac

APPIMAGE="$ROOT/dist/QLInux-${VERSION}-${ARCH}.AppImage"

echo "==> Version $VERSION ($ARCH)"

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
mkdir -p "$APPDIR/usr/share/metainfo"
install -m 0644 "$ROOT/packaging/ql-editor.metainfo.xml" \
    "$APPDIR/usr/share/metainfo/ql-editor.metainfo.xml"
install -m 0644 "$ROOT/assets/ql-editor.png" "$APPDIR/ql-editor.png"
install -m 0644 "$ROOT/assets/ql-editor.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/ql-editor.png"
# Dateitypen: .qlx und .lbx (MIME-Definition + Symbole fuer beide Typen).
mkdir -p "$APPDIR/usr/share/mime/packages" \
    "$APPDIR/usr/share/icons/hicolor/256x256/mimetypes" \
    "$APPDIR/usr/share/icons/hicolor/128x128/mimetypes"
install -m 0644 "$ROOT/packaging/ql-editor-mime.xml" \
    "$APPDIR/usr/share/mime/packages/ql-editor-mime.xml"
for icon in "$ROOT"/assets/mimetypes/*.png; do
    install -m 0644 "$icon" "$APPDIR/usr/share/icons/hicolor/256x256/mimetypes/"
done
for icon in "$ROOT"/assets/mimetypes/128/*.png; do
    install -m 0644 "$icon" "$APPDIR/usr/share/icons/hicolor/128x128/mimetypes/"
done

echo "==> appimagetool"
mkdir -p "$CACHE"
TOOL="$CACHE/appimagetool-${ARCH}.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
    chmod +x "$TOOL"
fi

echo "==> AppImage"
mkdir -p "$ROOT/dist"
# Update-Info fuer GearLever: neueste GitHub-Release, .zsync-Datei daneben.
UPDATE_INFO="gh-releases-zsync|loeffelandi|QLInux|latest|QLInux-*-${ARCH}.AppImage.zsync"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run -u "$UPDATE_INFO" "$APPDIR" "$APPIMAGE"
# appimagetool schreibt die .zsync je nach Version ins Home, ins CWD oder
# neben das AppImage - danach soll sie neben der Datei in dist/ liegen.
ZSYNC_NAME="$(basename "$APPIMAGE").zsync"
for candidate in "$HOME/$ZSYNC_NAME" "$ROOT/$ZSYNC_NAME" "$ROOT/dist/$ZSYNC_NAME"; do
    if [ -f "$candidate" ] && [ "$candidate" != "$ROOT/dist/$ZSYNC_NAME" ]; then
        mv -f "$candidate" "$ROOT/dist/$ZSYNC_NAME"
        break
    fi
done
if [ ! -f "$ROOT/dist/$ZSYNC_NAME" ]; then
    echo "Warnung: $ZSYNC_NAME nicht gefunden" >&2
fi

echo
echo "fertig: $APPIMAGE ($(du -h "$APPIMAGE" | cut -f1))"
echo "starten:  $APPIMAGE"
