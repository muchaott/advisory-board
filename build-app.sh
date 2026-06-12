#!/bin/bash
# Build a real, double-clickable Yoda.app bundle that launches the menubar app
# from this project's venv. Installs to /Applications (falls back to ~/Applications).
# Re-run after changing the icon or moving the project.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/.venv/bin/python"
ICON="$ROOT/assets/logo.icns"

DEST="/Applications"
[ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST"
APP="$DEST/Yoda.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cp "$ICON" "$APP/Contents/Resources/logo.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Yoda</string>
  <key>CFBundleDisplayName</key><string>Yoda</string>
  <key>CFBundleExecutable</key><string>Yoda</string>
  <key>CFBundleIdentifier</key><string>com.muchao.yoda</string>
  <key>CFBundleIconFile</key><string>logo</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/Yoda" <<LAUNCH
#!/bin/bash
cd "$ROOT" || exit 1
exec "$PY" menubar.py
LAUNCH
chmod +x "$APP/Contents/MacOS/Yoda"

# refresh LaunchServices + Dock icon cache
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true

echo "Built $APP"
