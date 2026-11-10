#!/bin/bash
set -euo pipefail

case "${1:?native phase required}" in
  import-certificate)
    KEYCHAIN_PATH="$RUNNER_TEMP/build.keychain-db"
    CERT_PATH="$RUNNER_TEMP/certificate.p12"
    printf '%s' "$CERT_BASE64" | base64 --decode -o "$CERT_PATH"
    security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
    security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    security import "$CERT_PATH" -P "$CERT_PASSWORD" -A -t cert -f pkcs12 -k "$KEYCHAIN_PATH"
    security list-keychain -d user -s "$KEYCHAIN_PATH" login.keychain
    security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
    echo "KEYCHAIN_PATH=$KEYCHAIN_PATH" >> "$GITHUB_ENV"
    ;;
  store-credentials)
    xcrun notarytool store-credentials "notarytool-profile" \
      --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APP_PASSWORD" \
      --keychain "$KEYCHAIN_PATH"
    ;;
  build)
    python3 .github/scripts/native.py clean-macos
    cmake -S HTML2PDF -B HTML2PDF/cmake-build \
      -DCMAKE_BUILD_TYPE=Release \
      '-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64' \
      "-DCMAKE_OSX_DEPLOYMENT_TARGET=${MACOS_DEPLOYMENT_TARGET:?}"
    cmake --build HTML2PDF/cmake-build
    python3 .github/scripts/native.py architectures
    ;;
  merge)
    python3 .github/scripts/native.py merge-windows
    echo "BUNDLE_PATH=HTML2PDF/HTML2PDF-test/Plugins/HTML2PDF.bundle" >> "$GITHUB_ENV"
    ;;
  sign)
    IDENTITY=$(security find-identity -v -p codesigning "$KEYCHAIN_PATH" \
      | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)".*/\1/')
    test -n "$IDENTITY"
    codesign --verbose --deep --timestamp --force --options=runtime \
      --sign "$IDENTITY" "$BUNDLE_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    ;;
  package)
    VERSION=$(python3 .github/scripts/source_version.py)
    ZIP_PATH="HTML2PDF-${VERSION}.zip"
    DMG_PATH="HTML2PDF-${VERSION}.dmg"
    python3 - "$ZIP_PATH" "$DMG_PATH" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, ".github/scripts")
import native
native.validate_paths(tuple(map(Path, sys.argv[1:])))
PY
    test ! -e "$ZIP_PATH"
    test ! -e "$DMG_PATH"
    ditto -c -k --keepParent "$BUNDLE_PATH" "$ZIP_PATH"
    hdiutil create -format UDBZ -volname HTML2PDF -srcfolder "$BUNDLE_PATH" "$DMG_PATH"
    for artifact in "$ZIP_PATH" "$DMG_PATH"; do
      response=$(xcrun notarytool submit "$artifact" \
        --keychain-profile "notarytool-profile" --keychain "$KEYCHAIN_PATH" \
        --wait --output-format json)
      printf '%s' "$response" | python3 -c \
        'import json,sys
sys.path.insert(0, ".github/scripts")
from release import finite_float, invalid_constant, json_object
result = json.load(sys.stdin, object_pairs_hook=json_object,
                   parse_constant=invalid_constant, parse_float=finite_float)
sys.exit(0 if isinstance(result,dict) and result.get("status") == "Accepted" else "Notarization was not Accepted")'
    done
    xcrun stapler staple "$DMG_PATH"
    codesign --verify --deep --strict --verbose=2 "$BUNDLE_PATH"
    python3 .github/scripts/native.py validate
    echo "ZIP_PATH=$ZIP_PATH" >> "$GITHUB_ENV"
    echo "DMG_PATH=$DMG_PATH" >> "$GITHUB_ENV"
    ;;
  *)
    echo "Unknown native phase: $1" >&2
    exit 1
    ;;
esac
