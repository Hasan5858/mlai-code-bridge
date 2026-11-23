#!/usr/bin/env python3
"""Measure TTFT and output throughput through the bridge."""
import json, os, sys, time, urllib.request
from pathlib import Path

STATE = Path(os.environ.get("MLAI_SHIM_HOME", Path.home() / ".mlai-shim"))
KEY = (STATE / "key").read_text().strip()
URL = os.environ.get("MLAI_SHIM_URL", "http://127.0.0.1:8210/v1") + "/chat/completions"

CASES = [
    ("low / short answer", "Reply with exactly: PONG", 200, "low"),
    ("low / 200-word explain", "Explain what a database index does, in about 200 words.", 700, "low"),
    ("high / python function", "Write a Python function that merges two sorted lists in O(n), with a docstring and 3 unit tests.", 900, "high"),
    ("max / same (needs 2000+)", "Write a Python function that merges two sorted lists in O(n), with a docstring and 3 unit tests.", 2400, "max"),
]


def run(label, prompt, max_tokens, effort):
    body = json.dumps({
        "model": "mlai-code",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "reasoning_effort": effort,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + KEY,
        "Accept": "text/event-stream",
    })
    t0, ttft, usage, upstream = time.time(), None, {}, None
    with urllib.request.urlopen(req, timeout=300) as res:
        for raw in res:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                d = json.loads(payload)
            except Exception:
                continue
            upstream = d.get("model") or upstream
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices") or []:
                if (ch.get("delta") or {}).get("content") and ttft is None:
                    ttft = time.time() - t0
    total = time.time() - t0
    comp = usage.get("completion_tokens") or 0
    reasoning = ((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    visible = comp - reasoning
    print(f"{label:26s} upstream={upstream} ttft={(ttft or 0):.2f}s total={total:.2f}s "
          f"visible={visible} reasoning={reasoning} tok/s={(visible / total if total else 0):.1f}")


for case in CASES:
    try:
        run(*case)
    except Exception as exc:
        print(case[0], "FAILED", str(exc)[:200])
