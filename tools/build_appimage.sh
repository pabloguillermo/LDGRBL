#!/usr/bin/env bash
# Builds LDGRBL.appimage (x86_64) from the current source tree.
#
# Bundles: the system Python 3 + its stdlib, the system wxPython (and libwx_*),
# the project sources, and the pip dependencies from requirements.txt.
# GTK3 and the base system libraries are taken from the host at run time, so the
# AppImage targets Debian/Ubuntu-like systems with GTK3 installed (same or newer
# glibc than the build machine).
#
# Requirements on the build machine: python3, python3-wxgtk4.0 (wx), pip, curl.
# Usage: tools/build_appimage.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${BUILD_DIR:-/tmp/ldgrbl-build}"
APPDIR="$BUILD/LDGRBL.AppDir"
OUT="$ROOT/LDGRBL.appimage"
PYBIN="$(command -v python3)"
PYVER="$("$PYBIN" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYREAL="$(readlink -f "$PYBIN")"
STDLIB="$("$PYBIN" -c 'import sysconfig;print(sysconfig.get_path("stdlib"))')"
WXDIR="$("$PYBIN" -c 'import wx,os;print(os.path.dirname(wx.__file__))')"
LIBDIR=/usr/lib/x86_64-linux-gnu

rm -rf "$APPDIR"
mkdir -p "$BUILD" "$APPDIR/usr/bin" "$APPDIR/usr/lib/python3/dist-packages" \
         "$APPDIR/usr/lib/ldgrbl" "$APPDIR/usr/lib/wx"

echo "==> Python $PYVER"
cp "$PYREAL" "$APPDIR/usr/bin/python$PYVER"
rsync -a --exclude='__pycache__' --exclude='test' --exclude='tests' \
      --exclude='idlelib' --exclude='tkinter' --exclude='turtledemo' \
      --exclude='ensurepip' --exclude='site-packages' --exclude='dist-packages' \
      "$STDLIB/" "$APPDIR/usr/lib/python$PYVER/"

echo "==> pip dependencies"
PIPTMP="$BUILD/pip-target"
rm -rf "$PIPTMP"
# wxPython comes from the system (no manylinux wheel); everything else from pip.
grep -v -i '^wxpython' "$ROOT/requirements.txt" | sed 's/^numpy.*/numpy/' > "$BUILD/req.txt"
"$PYBIN" -m pip install --quiet --target "$PIPTMP" --only-binary=:all: -r "$BUILD/req.txt"
cp -a "$PIPTMP"/. "$APPDIR/usr/lib/python3/dist-packages/"

echo "==> wxPython"
cp -a "$WXDIR" "$APPDIR/usr/lib/python3/dist-packages/wx"
for d in /usr/lib/python3/dist-packages/wxPython*; do
    [ -e "$d" ] && cp -a "$d" "$APPDIR/usr/lib/python3/dist-packages/" || true
done
# wxPython needs the matching libwx_* shared libraries (not the webview one).
for f in "$LIBDIR"/libwx_*.so.*; do
    case "$f" in *webview*) continue;; esac
    cp -a "$f" "$APPDIR/usr/lib/wx/"
done

echo "==> Application sources"
rsync -a --exclude='__pycache__' --exclude='*.pyc' "$ROOT/meerk40t" "$APPDIR/usr/lib/ldgrbl/"
cp "$ROOT/meerk40t.py" "$APPDIR/usr/lib/ldgrbl/"
[ -d "$ROOT/locale" ] && rsync -a "$ROOT/locale" "$APPDIR/usr/lib/ldgrbl/"

echo "==> Launcher, desktop entry, icon"
cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"
export APPDIR="\$HERE"
export PYTHONHOME="\$HERE/usr"
export PYTHONPATH="\$HERE/usr/lib/ldgrbl:\$HERE/usr/lib/python3/dist-packages"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export LD_LIBRARY_PATH="\$HERE/usr/lib/wx\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
exec "\$HERE/usr/bin/python$PYVER" "\$HERE/usr/lib/ldgrbl/meerk40t.py" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/ldgrbl.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=LDGRBL
Comment=Laser GRBL control software (MeerK40t based)
Exec=AppRun
Icon=ldgrbl
Categories=Graphics;Engineering;
Terminal=false
EOF
ICON="$ROOT/images/Ícone de Gravador a Laser com Dragão.png"
[ -f "$ICON" ] || ICON="$ROOT/images/meerk40t.png"
cp "$ICON" "$APPDIR/ldgrbl.png"

echo "==> appimagetool"
TOOL="$BUILD/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fL -o "$TOOL" \
      https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi
rm -f "$OUT"
# --appimage-extract-and-run: works without FUSE on the build machine.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$OUT"
chmod +x "$OUT"
echo "Done: $OUT ($(du -h "$OUT" | cut -f1))"
