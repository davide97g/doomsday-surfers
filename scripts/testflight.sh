#!/bin/sh
# Archive the iOS app and upload it to TestFlight (internal testing only).
# Needs: the app record in App Store Connect for com.davideghiotto.doomsdaysurfers,
# and your Apple ID signed in under Xcode > Settings > Accounts.
#   bun run ios:testflight            archive + upload
#   bun run ios:testflight --dry      archive only (no upload)
set -e
cd "$(dirname "$0")/.."

BUILD=$(date +%Y%m%d%H%M)   # every upload needs a higher build number
ARCHIVE="ios/build/DoomsdaySurfers-$BUILD.xcarchive"

bun run build
bunx cap sync ios

xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$ARCHIVE" \
  -allowProvisioningUpdates CURRENT_PROJECT_VERSION="$BUILD" \
  archive | grep -E " error: |ARCHIVE (SUCCEEDED|FAILED)" || true
[ -d "$ARCHIVE" ] || { echo "archive failed"; exit 1; }
echo "archived build $BUILD -> $ARCHIVE"

if [ "$1" = "--dry" ]; then exit 0; fi

xcodebuild -exportArchive -archivePath "$ARCHIVE" \
  -exportOptionsPlist ios/App/ExportOptions.plist -exportPath ios/build/export \
  -allowProvisioningUpdates
echo "uploaded build $BUILD to App Store Connect; it shows in TestFlight after processing (~10-30 min)"
