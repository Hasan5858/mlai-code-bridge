#!/usr/bin/env python3
"""
mlai-code-bridge — serve an ML AI Code subscription as an OpenAI-compatible API.

Why this exists: code.ml.ai has no documented model API. Its model gateway only
accepts a short-lived *run token* minted per "laptop run", so a plain base_url +
API key never works. This bridge mints a run token with the device credential the
official CLI stores, keeps it warm, and re-serves it as a normal OpenAI /v1
endpoint on loopback.

Endpoints
    GET  /v1/models
    POST /v1/chat/completions     (stream: true and false)
    GET  /health

Auth
    Authorization: Bearer <key from ~/.mlai-shim/key>  (generated on first run)

Upstream
    POST {gateway}/chat/completions  with the run token

Unofficial. Not affiliated with ML.ai / Pixis. See README before using.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE = Path(os.environ.get("MLAI_SHIM_HOME", Path.home() / ".mlai-shim"))

# The device token is only ever sent to these hosts. code.ml.ai is the product origin;
# mlai-mini-code.vercel.app is the desktop CLI's own DEFAULT_URL (same deployment, 307s to
# code.ml.ai) and is kept only so older configs keep working.
DEFAULT_SERVER = "https://code.ml.ai"
ALLOWED_HOSTS = {"code.ml.ai", "mlai-mini-code.vercel.app", "127.0.0.1", "localhost"}


def _validate_server(raw: str) -> str:
    """An origin only: https (or http on loopback for tests), allowlisted host, no path/query."""
    u = urllib.parse.urlparse(str(raw).rstrip("/"))
    if u.path not in ("", "/") or u.query or u.fragment:
        raise SystemExit(f"MLAI_SERVER must be a bare origin, got {raw!r}")
    loopback = u.hostname in ("127.0.0.1", "localhost")
    if u.scheme != "https" and not (loopback and u.scheme == "http"):
        raise SystemExit("MLAI_SERVER must use https")
    if not loopback and u.hostname not in ALLOWED_HOSTS and os.environ.get("MLAI_ALLOW_CUSTOM_SERVER") != "1":
        raise SystemExit(
            f"refusing MLAI_SERVER host {u.hostname!r}: this device token is only meant for ml.ai hosts.\n"
            "Set MLAI_ALLOW_CUSTOM_SERVER=1 only if you are pointing at your own proxy."
        )
    return f"{u.scheme}://{u.netloc}"


SERVER = _validate_server(
    os.environ.get("MLAI_SERVER_OVERRIDE") or os.environ.get("MLAI_SERVER") or DEFAULT_SERVER
)


class _SameOriginRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only inside the same origin — never carry Authorization to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(newurl)
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            raise RuntimeError(f"refusing a cross-host redirect ({old.netloc} -> {new.netloc})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SameOriginRedirects)
PROTOCOL = 1
CLIENT_VERSION = os.environ.get("MLAI_CLIENT_VERSION", "0.3.2")
PORT = int(os.environ.get("MLAI_SHIM_PORT", "8210"))
MODEL_ID = os.environ.get("MLAI_MODEL_ID", "mlai-code")
CONTEXT_WINDOW = int(os.environ.get("MLAI_CONTEXT_WINDOW", "1048576"))
MAX_LOG_BYTES = 2 * 1024 * 1024
RUN_FILE = STATE / "run.json"
LOG_FILE = STATE / "shim.log"

_lock = threading.Lock()
_run: dict = {"token": None, "gateway": None, "expires": 0.0, "run_id": None, "budget": None}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.1"))
        with open(LOG_FILE, "a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line, file=sys.stderr, flush=True)


def project_id() -> str:
    STATE.mkdir(parents=True, exist_ok=True)
    f = STATE / "project.json"
    try:
        return json.loads(f.read_text())["id"]
    except Exception:
        pid = str(uuid.uuid4())
        f.write_text(json.dumps({"id": pid}))
        os.chmod(f, 0o600)
        return pid


def _secret_store_token() -> str:
    """The credential `mlai login` stores, from the OS secret store where there is one.

    macOS: login Keychain (the app and CLI write service "ML AI Code", account "device-token").
    Linux: libsecret via secret-tool. Windows: none — the CLI falls back to a file, see below.
    """
    try:
        if sys.platform == "darwin":
            cmd = ["security", "find-generic-password", "-s", "ML AI Code", "-a", "device-token", "-w"]
        elif sys.platform.startswith("linux"):
            cmd = ["secret-tool", "lookup", "service", "ML AI Code", "account", "device-token"]
        else:
            return ""
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception as exc:  # noqa: BLE001 - a missing helper is not fatal
        log(f"secret store read failed: {exc}")
        return ""


def device_token() -> str:
    """Device credential: MLAI_TOKEN, then the OS secret store, then the CLI's token file."""
    tok = os.environ.get("MLAI_TOKEN")
    if tok:
        return tok.strip()
    tok = _secret_store_token()
    if tok:
        return tok
    for candidate in (Path.home() / ".mlai" / ".device-token", STATE / "device-token"):
        try:
            if candidate.exists():
                value = candidate.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except OSError:
            continue
    raise RuntimeError(
        "Not signed in on this device. Run `mlai login` (npm install -g mlai-code, or the app's CLI), "
        "or set MLAI_TOKEN to the device token."
    )


def api_request(path: str, body=None, token: str | None = None, timeout: int = 60):
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-MLAI-Client": "laptop",
        "X-MLAI-Version": CLIENT_VERSION,
        "X-MLAI-Protocol": str(PROTOCOL),
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(SERVER + path, data=data, headers=headers, method="POST")
    try:
        with _opener.open(req, timeout=timeout) as res:
            return res.status, json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": raw[:500]}
        return exc.code, payload


def mint() -> dict:
    """Start a laptop run and adopt its token."""
    pid = project_id()
    status, data = api_request("/api/laptop", {
        "action": "start",
        "project": pid,
        "folder": "bridge",
        "folderProject": pid,
        "title": "Bridge",
    }, token=device_token())
    if status != 200 or not data.get("token"):
        raise RuntimeError(f"start failed ({status}): {json.dumps(data)[:400]}")
    _run.update({
        "token": data["token"],
        "gateway": data.get("gateway") or data.get("endpoint"),
        "expires": (data.get("expires") or 0) / 1000.0,
        "run_id": data.get("runId"),
        "budget": data.get("budget"),
    })
    try:
        RUN_FILE.write_text(json.dumps(_run))
        os.chmod(RUN_FILE, 0o600)
    except OSError:
        pass
    ttl = (_run["expires"] - time.time()) / 3600
    log(f"minted run {_run['run_id']} ttl={ttl:.1f}h budget={_run['budget']}")
    return _run


def load_cached() -> dict | None:
    try:
        data = json.loads(RUN_FILE.read_text())
    except Exception:
        return None
    if data.get("token") and data.get("gateway") and data.get("expires", 0) - time.time() > 300:
        _run.update(data)
        return _run
    return None


def finish_current(state: str = "completed") -> None:
    token = _run.get("token")
    if token:
        try:
            status, data = api_request("/api/laptop", {"action": "finish", "state": state}, token=token)
            log(f"finished run {_run.get('run_id')} -> {status} {json.dumps(data)[:200]}")
        except Exception as exc:
            log(f"finish failed: {exc}")
    try:
        RUN_FILE.unlink()
    except OSError:
        pass
    _run.update({"token": None, "gateway": None, "expires": 0.0, "run_id": None})


def current_run(force: bool = False) -> dict:
    with _lock:
        if not force and _run.get("token") and _run["expires"] - time.time() > 300:
            return _run
        if not force:
            cached = load_cached()
            if cached:
                return cached
        if _run.get("token"):
            finish_current("completed")
        return mint()


def normalize_body(body: dict) -> dict:
    out = dict(body)
    out["model"] = MODEL_ID
    if "max_completion_tokens" in out and "max_tokens" not in out:
        out["max_tokens"] = out.pop("max_completion_tokens")
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mlai-code-bridge/1.0"

    def log_message(self, fmt, *args):
        return

    def _auth_ok(self) -> bool:
        try:
            key = (STATE / "key").read_text().strip()
        except OSError:
            return False
        got = (self.headers.get("authorization") or "").replace("Bearer ", "").strip()
        return bool(key) and secrets.compare_digest(got, key)

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/v1/models", "/models"):
            if not self._auth_ok():
                return self._json(401, {"error": {"message": "bad bridge key", "type": "invalid_api_key"}})
            return self._json(200, {"object": "list", "data": [{
                "id": MODEL_ID, "object": "model", "owned_by": "mlai", "created": 0,
                "context_length": CONTEXT_WINDOW,
            }]})
        if path in ("/health", "/v1/health"):
            return self._json(200, {
                "ok": True,
                "run": _run.get("run_id"),
                "gateway": _run.get("gateway"),
                "ttl_h": round((_run.get("expires", 0) - time.time()) / 3600, 2),
            })
        self._json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            return self._json(404, {"error": {"message": "not found", "type": "invalid_request_error"}})
        if not self._auth_ok():
            return self._json(401, {"error": {"message": "bad bridge key", "type": "invalid_api_key"}})
        try:
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            return self._json(400, {"error": {"message": "invalid JSON body", "type": "invalid_request_error"}})
        if not isinstance(body.get("messages"), list):
            return self._json(400, {"error": {"message": "messages[] required", "type": "invalid_request_error"}})

        payload = normalize_body(body)
        stream = bool(payload.get("stream"))
        for attempt in (0, 1):
            run = current_run(force=attempt == 1)
            url = run["gateway"].rstrip("/") + "/chat/completions"
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
                "Authorization": "Bearer " + run["token"],
            }, method="POST")
            try:
                res = _opener.open(req, timeout=300)
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                if exc.code in (401, 403, 409) and attempt == 0:
                    log("run token rejected, re-minting")
                    continue
                log(f"upstream {exc.code}: {raw[:300]}")
                return self._json(exc.code, {"error": {"message": raw[:800], "type": "upstream_error"}})
            except Exception as exc:
                log(f"upstream error: {exc}")
                return self._json(502, {"error": {"message": str(exc)[:300], "type": "upstream_error"}})

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                chunks = 0
                try:
                    while True:
                        line = res.readline()
                        if not line:
                            break
                        self.wfile.write(line)
                        self.wfile.flush()
                        chunks += 1
                except (BrokenPipeError, ConnectionResetError):
                    log("client disconnected mid-stream")
                finally:
                    try:
                        res.close()
                    except Exception:
                        pass
                log(f"stream ok chunks={chunks} run={run['run_id']}")
                return

            raw = res.read()
            try:
                data = json.loads(raw)
                usage = data.get("usage") or {}
                log(f"json ok tokens={usage.get('total_tokens')} run={run['run_id']}")
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return


def selftest() -> int:
    run = current_run()
    print("server:", SERVER, "| run:", run["run_id"], "| gateway:", run["gateway"],
          "| ttl_h:", round((run["expires"] - time.time()) / 3600, 2))
    body = json.dumps({"model": MODEL_ID, "messages": [{"role": "user", "content": "Reply with exactly: PONG"}],
                       "max_tokens": 300}).encode()
    req = urllib.request.Request(run["gateway"].rstrip("/") + "/chat/completions", data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + run["token"]})
    with urllib.request.urlopen(req, timeout=120) as res:
        data = json.loads(res.read())
    msg = data["choices"][0]["message"]
    print("status:", res.status, "content:", repr(msg.get("content")), "usage:", (data.get("usage") or {}).get("total_tokens"))
    finish_current("completed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve an ML AI Code subscription as an OpenAI-compatible API.")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--selftest", action="store_true", help="mint a token, run one completion, then exit")
    args = ap.parse_args()

    STATE.mkdir(parents=True, exist_ok=True)
    keyfile = STATE / "key"
    if not keyfile.exists():
        keyfile.write_text("mlai-" + secrets.token_urlsafe(24))
        os.chmod(keyfile, 0o600)

    if args.selftest:
        return selftest()

    try:
        current_run()
    except Exception as exc:
        log(f"warm-up failed: {exc}")

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)

    def shutdown(signum, frame):
        log(f"signal {signum}, closing")
        threading.Thread(target=srv.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, shutdown)

    log(f"upstream {SERVER} | listening on http://127.0.0.1:{args.port}/v1 (key {keyfile})")
    try:
        srv.serve_forever()
    finally:
        finish_current("completed")
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
