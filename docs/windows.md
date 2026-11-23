# Windows

The bridge is plain Python 3.9+ standard library — nothing in it is macOS-specific except the
secret-store lookup, which on Windows falls back to the token file the CLI writes.

## 1. Sign in

The Windows desktop app is a preview; the CLI is the supported path:

```powershell
npm install -g mlai-code
mlai login          # opens the browser, approves the device
mlai whoami
```

Windows has no Keychain, so `mlai login` writes the device credential to
`%USERPROFILE%\.mlai\.device-token` (0600 equivalent handled by the OS ACL).
The bridge reads that file automatically.

## 2. Install the bridge

```powershell
git clone https://github.com/Hasan5858/mlai-code-bridge.git
cd mlai-code-bridge
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` copies the script to `%USERPROFILE%\.mlai-shim\app`, registers the Scheduled Task
`mlai-code-bridge` (at logon, restart on failure, no time limit) and starts it.

Check:

```powershell
curl.exe -s http://127.0.0.1:8210/health
python .\bench.py
```

## 3. Point clients at it

```
base_url = http://127.0.0.1:8210/v1
api_key  = contents of %USERPROFILE%\.mlai-shim\key
model    = mlai-code
```

## Notes and caveats

* **Not verified by the maintainer.** The port was written for macOS; the Windows path is the same
  code with the file-based credential fallback and a Scheduled Task instead of launchd. If something
  breaks, open an issue with the `shim.log` tail.
* Antivirus / SmartScreen may flag a Python script that listens on a port — it binds `127.0.0.1`
  only and requires its own bearer key.
* Run the task as your user (not SYSTEM): the device token lives in your profile.
* Uninstall: `.\uninstall.ps1`, then delete `%USERPROFILE%\.mlai-shim` if you want the key gone too.
