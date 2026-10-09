#!/bin/sh
# One-time setup for the Blender asset pipeline (docs/assets-v2.md). Safe to
# re-run: every step skips what is already there.
#
#   bun run assets:setup          (BLENDER=/path/to/blender to override)
#
#   1. MPFB (MakeHuman for Blender) extension, installed and enabled
#   2. MakeHuman system assets (CC0: skins, hair, clothes, shoes, proxies),
#      downloaded to tools/cache/ and unpacked into MPFB's user data folder
#      (what MPFB's "Load pack from zip file" does)
#   3. CC0 texture sets -> assets/textures/ (scripts/fetch-textures.ts)
#   4. KTX-Software (the `ktx`/`toktx` binaries for KTX2 textures) ->
#      tools/ktx/, unpacked from the GitHub release without sudo
#   5. Basis transcoder for three's KTX2Loader -> public/libs/basis/
#
# tools/ and assets/textures/ are gitignored.
set -e
cd "$(dirname "$0")/.."
BLENDER=${BLENDER:-blender}
CACHE=tools/cache
mkdir -p "$CACHE"
say() { echo "setup: $*"; }

# ---------------------------------------------------------------- 1. MPFB
if "$BLENDER" -b --python-expr 'import sys, addon_utils; sys.exit(0 if addon_utils.check("bl_ext.blender_org.mpfb")[1] else 1)' >/dev/null 2>&1; then
  say "MPFB already installed and enabled"
else
  say "installing MPFB from extensions.blender.org"
  "$BLENDER" --online-mode -c extension install --sync --enable mpfb
fi

# ---------------------------------------------------------------- 2. MakeHuman system assets
ZIP="$CACHE/makehuman_system_assets_cc0.zip"
URL=https://files2.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip
if [ ! -s "$ZIP" ]; then
  say "downloading MakeHuman system assets (~270 MB)"
  curl -fL --retry 3 -o "$ZIP.part" "$URL"
  mv "$ZIP.part" "$ZIP"
fi
OUT=$(MPFB_ZIP="$(pwd)/$ZIP" "$BLENDER" -b --python-expr '
import os, sys, zipfile
from bl_ext.blender_org.mpfb.services import AssetService, LocationService
data = LocationService.get_user_data()
marker = os.path.join(data, "packs", "makehuman_system_assets.json")
if os.path.exists(marker):
    print("setup: MPFB system assets already in", data)
else:
    with zipfile.ZipFile(os.environ["MPFB_ZIP"]) as z:
        z.extractall(data)
    AssetService.update_all_asset_lists()
    print("setup: MPFB system assets unpacked into", data)
sys.exit(0 if os.path.exists(marker) else 1)
' 2>&1) || { echo "$OUT"; say "installing the MPFB asset pack failed"; exit 1; }
echo "$OUT" | grep '^setup:'

# ---------------------------------------------------------------- 3. textures
bun scripts/fetch-textures.ts

# ---------------------------------------------------------------- 4. KTX-Software
KTX_VERSION=4.4.2
if [ -x tools/ktx/ktx ] && tools/ktx/ktx --version >/dev/null 2>&1; then
  say "KTX-Software present ($(tools/ktx/ktx --version))"
else
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) PKG=KTX-Software-$KTX_VERSION-Darwin-arm64.pkg ;;
    Darwin-x86_64) PKG=KTX-Software-$KTX_VERSION-Darwin-x86_64.pkg ;;
    Linux-x86_64) PKG=KTX-Software-$KTX_VERSION-Linux-x86_64.tar.bz2 ;;
    Linux-aarch64) PKG=KTX-Software-$KTX_VERSION-Linux-arm64.tar.bz2 ;;
    *) PKG= ;;
  esac
  if [ -z "$PKG" ]; then
    say "no KTX-Software build for $(uname -s)-$(uname -m): textures will be WebP"
  else
    say "fetching $PKG"
    curl -fL --retry 3 -o "$CACHE/$PKG" "https://github.com/KhronosGroup/KTX-Software/releases/download/v$KTX_VERSION/$PKG"
    rm -rf "$CACHE/ktx-unpacked" tools/ktx
    mkdir -p tools/ktx
    case "$PKG" in
      *.pkg)
        pkgutil --expand-full "$CACHE/$PKG" "$CACHE/ktx-unpacked"
        cp -a "$CACHE"/ktx-unpacked/*-tools.pkg/Payload/usr/local/bin/ktx \
              "$CACHE"/ktx-unpacked/*-tools.pkg/Payload/usr/local/bin/toktx \
              "$CACHE"/ktx-unpacked/*-tools.pkg/Payload/usr/local/bin/ktxinfo tools/ktx/
        # The binaries look for libktx next to themselves (@rpath = @executable_path).
        cp -a "$CACHE"/ktx-unpacked/*-library.pkg/Payload/usr/local/lib/libktx* tools/ktx/
        ;;
      *.tar.bz2)
        mkdir -p "$CACHE/ktx-unpacked"
        tar -xjf "$CACHE/$PKG" -C "$CACHE/ktx-unpacked"
        cp -a "$CACHE"/ktx-unpacked/*/bin/ktx "$CACHE"/ktx-unpacked/*/bin/toktx tools/ktx/
        cp -a "$CACHE"/ktx-unpacked/*/lib/libktx* tools/ktx/
        ;;
    esac
    rm -rf "$CACHE/ktx-unpacked"
    if tools/ktx/ktx --version >/dev/null 2>&1; then
      say "KTX-Software installed in tools/ktx ($(tools/ktx/ktx --version))"
    else
      say "KTX-Software did not run here: textures will be WebP"
      rm -rf tools/ktx
    fi
  fi
fi

# ---------------------------------------------------------------- 5. decoders
bun scripts/copy-decoders.ts
say "done"
