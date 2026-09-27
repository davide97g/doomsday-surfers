#!/bin/sh
# Build the app and install it straight onto a paired iPhone (Wi-Fi or cable),
# then launch it. Development signing (automatic, team DA596D32QB), Release
# configuration so it runs like the real thing.
#   bun run ios:device                 build, install, launch
#   bun run ios:device --build-only    just build (checks signing)
#   bun run ios:device --perf          a perf build: the bot plays forever and
#                                      logs frame stats; this streams the log
#   DEVICE=<udid> bun run ios:device   another device (default: the iPhone 14)
# The phone must be unlocked and trust this Mac.
set -e
cd "$(dirname "$0")/.."

DEVICE=${DEVICE:-00008110-000479A11E83401E}
BUNDLE=com.davideghiotto.doomsdaysurfers
DERIVED=ios/build/dd
MODE=${1:-}

if [ "$MODE" = "--perf" ]; then
  VITE_PERF=1 bun run build
else
  bun run build
fi
bunx cap sync ios

LOG=ios/build/device-build.log
mkdir -p ios/build
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination "generic/platform=iOS" -derivedDataPath "$DERIVED" \
  -allowProvisioningUpdates build > "$LOG" 2>&1 || true
grep -E " error: |BUILD (SUCCEEDED|FAILED)" "$LOG" || true
grep -q "BUILD SUCCEEDED" "$LOG" || { echo "build failed (see $LOG)"; exit 1; }
APP="$DERIVED/Build/Products/Release-iphoneos/App.app"
echo "built $APP"

if [ "$MODE" = "--build-only" ]; then exit 0; fi

xcrun devicectl device install app --device "$DEVICE" "$APP"
if [ "$MODE" = "--perf" ]; then
  # Stream the app's console (the perf lines) until interrupted.
  xcrun devicectl device process launch --console --terminate-existing --device "$DEVICE" "$BUNDLE"
else
  xcrun devicectl device process launch --terminate-existing --device "$DEVICE" "$BUNDLE"
fi
