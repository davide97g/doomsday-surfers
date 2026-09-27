#!/bin/sh
# Build the app and install it straight onto a paired iPhone (Wi-Fi or cable)
# or an iOS Simulator, then launch it. Release configuration so it runs like
# the real thing; development signing (automatic, team DA596D32QB) on device.
#   bun run ios:device                   build, install, launch on the iPhone
#   bun run ios:device --sim             same on the iPhone 17 simulator
#   bun run ios:device --build-only      just build (checks signing)
#   bun run ios:device --perf            a perf build: the bot plays forever
#                                        and logs frame stats; streams the log
#   DEVICE=<udid> / SIM=<udid>           another device / simulator
# Flags combine (e.g. --sim --perf). A phone must be unlocked and trust this Mac.
set -e
cd "$(dirname "$0")/.."

DEVICE=${DEVICE:-00008110-000479A11E83401E}
SIM=${SIM:-DF6BBFEF-6BF6-4EA1-897D-1211CECBAF1C}
BUNDLE=com.davideghiotto.doomsdaysurfers
DERIVED=ios/build/dd
USE_SIM=0
PERF=0
BUILD_ONLY=0
for a in "$@"; do
  case "$a" in
    --sim) USE_SIM=1 ;;
    --perf) PERF=1 ;;
    --build-only) BUILD_ONLY=1 ;;
    *) echo "unknown flag $a"; exit 1 ;;
  esac
done

if [ "$PERF" = 1 ]; then
  VITE_PERF=1 bun run build
else
  bun run build
fi
bunx cap sync ios

if [ "$USE_SIM" = 1 ]; then
  SDK=iphonesimulator
  DEST="platform=iOS Simulator,id=$SIM"
else
  SDK=iphoneos
  DEST="generic/platform=iOS"
fi
LOG=ios/build/device-build.log
mkdir -p ios/build
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release -sdk "$SDK" \
  -destination "$DEST" -derivedDataPath "$DERIVED" \
  -allowProvisioningUpdates build > "$LOG" 2>&1 || true
grep -E " error: |BUILD (SUCCEEDED|FAILED)" "$LOG" || true
grep -q "BUILD SUCCEEDED" "$LOG" || { echo "build failed (see $LOG)"; exit 1; }
APP="$DERIVED/Build/Products/Release-$SDK/App.app"
echo "built $APP"

if [ "$BUILD_ONLY" = 1 ]; then exit 0; fi

if [ "$USE_SIM" = 1 ]; then
  xcrun simctl boot "$SIM" 2>/dev/null || true
  open "$(xcode-select -p)/Applications/Simulator.app" || true
  xcrun simctl bootstatus "$SIM" -b > /dev/null
  xcrun simctl install "$SIM" "$APP"
  if [ "$PERF" = 1 ]; then
    xcrun simctl launch --console-pty --terminate-running-process "$SIM" "$BUNDLE"
  else
    xcrun simctl launch --terminate-running-process "$SIM" "$BUNDLE"
  fi
else
  xcrun devicectl device install app --device "$DEVICE" "$APP"
  if [ "$PERF" = 1 ]; then
    # Stream the app's console (the perf lines) until interrupted.
    xcrun devicectl device process launch --console --terminate-existing --device "$DEVICE" "$BUNDLE"
  else
    xcrun devicectl device process launch --terminate-existing --device "$DEVICE" "$BUNDLE"
  fi
fi
