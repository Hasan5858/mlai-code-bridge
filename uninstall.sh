#!/bin/sh
# Stops and removes the LaunchAgent. ~/.mlai-shim keeps the key and logs.
set -eu
PLIST="$HOME/Library/LaunchAgents/ai.mlai-bridge.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "removed $PLIST"
