#!/bin/sh
# Installs mlai-code-bridge as a per-user LaunchAgent (macOS).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
PY=$(command -v python3 || true)
[ -n "$PY" ] || { echo "python3 not found (install the Xcode command line tools)"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "python3 is $("$PY" -V 2>&1) — 3.9+ required"; exit 1; }
PLIST="$HOME/Library/LaunchAgents/ai.mlai-bridge.plist"
mkdir -p "$HOME/.mlai-shim/app" "$HOME/Library/LaunchAgents"
# macOS blocks a LaunchAgent from reading external volumes (TCC: "Operation not permitted"),
# so the daemon runs a copy under ~/.mlai-shim/app. Edit the repo, re-run this script.
cp "$HERE/mlai_bridge.py" "$HOME/.mlai-shim/app/mlai_bridge.py"
cp "$HERE/bench.py" "$HOME/.mlai-shim/app/bench.py"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.mlai-bridge</string>
  <key>ProgramArguments</key>
  <array>
    <string>PYTHON_PATH</string>
    <string>SCRIPT_PATH</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>HOME_PATH/.mlai-shim/launchd.out</string>
  <key>StandardErrorPath</key><string>HOME_PATH/.mlai-shim/launchd.err</string>
</dict>
</plist>
PLISTEOF
sed -i '' "s|PYTHON_PATH|$PY|; s|SCRIPT_PATH|$HOME/.mlai-shim/app/mlai_bridge.py|; s|HOME_PATH|$HOME|" "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
sleep 2
echo "LaunchAgent loaded: $PLIST"
echo
echo "base_url : http://127.0.0.1:8210/v1"
echo "api_key  : $(cat "$HOME/.mlai-shim/key")"
echo "model    : mlai-code"
echo
echo "health   : curl -s http://127.0.0.1:8210/health"
echo "uninstall: launchctl unload \"$PLIST\" && rm \"$PLIST\""
