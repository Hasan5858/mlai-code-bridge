# mlai-code-bridge

Use an **ML AI Code** subscription ([code.ml.ai](https://code.ml.ai)) from any OpenAI-compatible client — Hermes, Aider, Cline, Codex, your own scripts — by running a small loopback bridge on your Mac.

> **Unofficial.** Not affiliated with ML.ai / Pixis. See [Legal](#legal) before you use it.

## The problem

ML AI Code ships no model API. Its public API is routines only (`/api/routines/{id}/run`), and its model gateway at `https://code.ml.ai/api/model/v1` speaks OpenAI but refuses every normal credential:

```bash
curl -s https://code.ml.ai/api/model/v1/models        # 200 — public list: [{"id":"mlai-code"}]
curl -s -X POST https://code.ml.ai/api/laptop \
  -H "authorization: Bearer $MLAI_DEVICE_TOKEN" -d '{"action":"start", ...}'   # 200 — mints a run token
curl -s -X POST https://code.ml.ai/api/model/v1/chat/completions \
  -H "authorization: Bearer $MLAI_PERSONAL_TOKEN" ...    # 401 run_token_invalid
```

The gateway only accepts a **per-run token** that the desktop app/CLI mints when a "laptop run" starts, and those tokens live 12 hours. So `base_url` + API key never works out of the box.

## Which host receives your device token

Exactly one origin: **`https://code.ml.ai`**, the product domain. If you are reviewing the code and
expect something else: the ML AI Code desktop CLI's own `DEFAULT_URL` is
`https://mlai-mini-code.vercel.app` — the *same deployment*, which 307-redirects to `code.ml.ai`.
That hostname can therefore show up in an older copy of this bridge, in the app bundle
(`engine/src/home.mjs`) and in the bundled client SDK. It is not a third-party endpoint.

Hardening that ships here:

* `MLAI_SERVER` is validated — https, a bare origin, and it must be `code.ml.ai` or
  `mlai-mini-code.vercel.app` unless you opt out with `MLAI_ALLOW_CUSTOM_SERVER=1`
* redirects are followed only inside the same origin, so `Authorization` can never be forwarded
  to a host you did not configure
* the credential stays in Keychain / libsecret / the CLI's token file; nothing secret is written
  into the repo or into the client config

## What this bridge does

```
your client ──▶ http://127.0.0.1:8210/v1  (this bridge)
                    │  device credential (Keychain, from `mlai login`)
                    ▼
              POST /api/laptop {action:"start"}   → {token, gateway, expires, budget}
                    ▼
              POST {gateway}/chat/completions     → stream / JSON, tools, reasoning_effort
```

* mints a run token on boot, caches it, reuses it for the full 12-hour TTL
* re-mints automatically on `401 run_token_invalid` / `409 run_finished`
* finishes the old run before rotating, so usage settles server-side
* binds **loopback only** and requires its own generated bearer key

Verified against the live service: streaming SSE, non-stream JSON, `tools` / `tool_calls`, `reasoning_effort: low|high|max`, ~60–120 output tok/s, TTFT ~1–2 s.

## Requirements

* an ML AI Code account on a device with a signed-in CLI or app
  * **macOS:** the desktop app ships the CLI
    ```bash
    node "/Applications/ML AI Code.app/Contents/Resources/engine/bin/mlai.mjs" login
    ```
    the credential lands in the login Keychain (service `ML AI Code`, account `device-token`)
  * **Linux / Windows:** `npm install -g mlai-code && mlai login`
    (secret store on Linux, `%USERPROFILE%\.mlai\.device-token` on Windows)
* Python 3.9+ (standard library only — no pip installs)

## Platforms

| OS | Script | Autostart | Status |
|---|---|---|---|
| macOS | `mlai_bridge.py` | launchd (`install.sh`) | tested |
| Windows 10/11 | same script | Scheduled Task (`install.ps1`) | ported, **not verified by the maintainer** — see [docs/windows.md](docs/windows.md) |
| Linux | same script | systemd user unit — see [docs/linux.md](docs/linux.md) | ported, not verified |

The bridge is pure standard-library Python: the only OS-specific branch is reading the device
credential from Keychain / libsecret / the token file.

## Install

```bash
git clone https://github.com/Hasan5858/mlai-code-bridge.git
cd mlai-code-bridge
./install.sh                 # macOS: writes ~/Library/LaunchAgents/ai.mlai-bridge.plist and loads it
```

Windows: `powershell -ExecutionPolicy Bypass -File .\install.ps1` — see [docs/windows.md](docs/windows.md).

The daemon itself runs from `~/.mlai-shim/app/mlai_bridge.py` — a copy `install.sh` makes for you,
because macOS refuses to let a LaunchAgent read an external volume (`Operation not permitted`).
Keep the repo wherever you like; **re-run `./install.sh` after editing it**.

Check it:

```bash
curl -s http://127.0.0.1:8210/health
KEY=$(cat ~/.mlai-shim/key)
curl -s http://127.0.0.1:8210/v1/models -H "authorization: Bearer $KEY"
python3 mlai_bridge.py --selftest
```

Foreground run (no launchd): `python3 mlai_bridge.py --port 8210`

## Point a client at it

```
base_url = http://127.0.0.1:8210/v1
api_key  = contents of ~/.mlai-shim/key
model    = mlai-code
```

OpenAI SDK:

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8210/v1", api_key=open(os.path.expanduser("~/.mlai-shim/key")).read().strip())
print(client.chat.completions.create(model="mlai-code",
      messages=[{"role": "user", "content": "hello"}]).choices[0].message.content)
```

Hermes Agent, as an alias that leaves your default provider alone:

```bash
hermes --profile <name> config set model.aliases.mlai.model mlai-code
hermes --profile <name> config set model.aliases.mlai.provider custom
hermes --profile <name> config set model.aliases.mlai.base_url http://127.0.0.1:8210/v1
hermes --profile <name> config set model.aliases.mlai.key_env MLAI_SHIM_KEY
echo "MLAI_SHIM_KEY=$(cat ~/.mlai-shim/key)" >> ~/.hermes/profiles/<name>/.env
hermes --profile <name> chat -q "Reply with exactly: PONG" -m mlai
```

Or as a picker row (adds `mlai-code` under its own provider in the model picker):

```bash
hermes --profile <name> config set providers.mlai.base_url http://127.0.0.1:8210/v1
hermes --profile <name> config set providers.mlai.key_env MLAI_SHIM_KEY
hermes --profile <name> config set providers.mlai.api_mode chat_completions
hermes --profile <name> config set providers.mlai.models.mlai-code.context_length 1048576
```

Full notes: [docs/hermes.md](docs/hermes.md).

## API

| Route | Notes |
|---|---|
| `GET /v1/models` | always `mlai-code` (the gateway exposes nothing else) |
| `POST /v1/chat/completions` | `stream`, `tools`, `tool_choice`, `max_tokens`, `reasoning_effort` |
| `GET /health` | current run id, gateway, hours left on the token |

Environment: `MLAI_SHIM_PORT` (8210), `MLAI_SHIM_HOME` (~/.mlai-shim), `MLAI_SERVER`, `MLAI_TOKEN`, `MLAI_CLIENT_VERSION`, `MLAI_MODEL_ID`, `MLAI_CONTEXT_WINDOW`.

## Behaviour worth knowing

* **One model id.** `model: mlai-code` is the only addressable name; the vendor gateway routes internally per request (observed `glm-5.3-flash` for plain chat). Asking for another id changes nothing.
* **Effort is the real knob.** `reasoning_effort: low|high|max` is honoured. With `max`, reasoning can eat the whole `max_tokens` budget — use ≥ 2000 when you set it.
* **A chat appears in the dashboard per mint.** Each run token is one entry in the vendor dashboard. Reuse keeps it to ~2 per day, not one per request.
* **12-hour tokens.** No refresh tokens; the bridge re-mints. If the device sign-in is revoked (`mlai login` again), minting fails until you sign in.
* **Speed** on this machine: TTFT ~1.1–1.8 s, ~80–120 output tok/s at `effort: high`. Measure yours with `python3 bench.py`.

## Legal

This tool reuses your own subscription's model gateway outside the official client. The vendor's terms (code.ml.ai/terms) include *"Do not try to get around plan limits, security controls or other people's access."* Your plan pays for the tokens, so this is not limit-busting, but it **is** out-of-client use: your account can be flagged, and the endpoint or protocol can change without notice (the client sends `X-MLAI-Protocol: 1`). Use it on your own account, at your own risk. No warranty; MIT licensed.

## License

MIT © Hasan Sarker
