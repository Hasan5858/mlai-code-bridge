# Linux

Same script, systemd user unit instead of launchd.

## 1. Sign in

```bash
npm install -g mlai-code
mlai login
mlai whoami
```

On Linux the credential lives in the Secret Service (`secret-tool lookup service "ML AI Code" account device-token`).
The bridge reads it from there; if no keyring is available, run `mlai login` with `MLAI_KEYCHAIN=file`
so the CLI writes `~/.mlai/.device-token`, which the bridge also reads.

## 2. Install

```bash
git clone https://github.com/Hasan5858/mlai-code-bridge.git
cd mlai-code-bridge
mkdir -p ~/.mlai-shim/app
cp mlai_bridge.py bench.py ~/.mlai-shim/app/
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/mlai-bridge.service <<'EOF'
[Unit]
Description=ML AI Code subscription bridge (OpenAI-compatible)
After=network-online.target

[Service]
ExecStart=/usr/bin/env python3 %h/.mlai-shim/app/mlai_bridge.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now mlai-bridge.service
systemctl --user status mlai-bridge.service --no-pager
```

Check: `curl -s http://127.0.0.1:8210/health`

## Notes

* Not verified by the maintainer (written on macOS). The Python is identical; the only Linux-specific
  piece is the Secret Service lookup.
* The key file is `~/.mlai-shim/key`; use it as your `api_key`.
* Uninstall: `systemctl --user disable --now mlai-bridge.service` and remove the unit.
