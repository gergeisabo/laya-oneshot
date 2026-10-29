"""Where a decision gets computed.

Two transports, same request shape:

  local   run ``laya-mlx predict`` on this machine
  remote  run it on another machine over ssh, once, and exit

Neither keeps a process alive. There is no server, no port, no API key.
"""
from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import tempfile
from dataclasses import dataclass

DEFAULT_PREDICT = "laya-mlx"

# Runs on the remote side: split the payload into the two files the CLI wants.
_SPLIT = (
    "import json,sys;b=sys.argv[1];d=json.load(open(b+'/p.json'));"
    "open(b+'/s.txt','w').write(json.dumps(d['state']));"
    "json.dump(d['questions'],open(b+'/q.json','w'))"
)


class TransportError(RuntimeError):
    """The model could not be reached or refused the request."""


@dataclass
class Result:
    body: dict
    route: str | None
    transport: str


def _parse(stdout: str, transport: str, route: str | None) -> Result:
    start, end = stdout.find("{"), stdout.rfind("}")
    if start < 0 or end < 0:
        raise TransportError(f"unreadable answer from {transport}: {stdout[:300]!r}")
    try:
        body = json.loads(stdout[start:end + 1])
    except json.JSONDecodeError as exc:
        raise TransportError(f"invalid JSON from {transport}: {exc}") from exc
    return Result(body=body, route=route, transport=transport)


def run_local(payload: dict, predict: str = DEFAULT_PREDICT, timeout: int = 180) -> Result:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    try:
        json.dump(payload["questions"], handle)
        handle.close()
        cmd = [os.path.expanduser(predict), "predict",
               "--state", payload["state"], "--questions", handle.name]
        if payload.get("model"):
            cmd += ["--model", payload["model"]]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise TransportError(f"{predict} not found — install it with `pip install laya-mlx`") from exc
        except subprocess.TimeoutExpired as exc:
            raise TransportError(f"local prediction timed out after {timeout}s") from exc
    finally:
        os.unlink(handle.name)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        raise TransportError(f"laya-mlx failed: {tail[-1] if tail else 'no output'}")
    return _parse(proc.stdout, "local", None)


def remote_command(payload: dict, predict: str = DEFAULT_PREDICT) -> str:
    """The exact shell command sent to the remote host — one shot, then cleanup."""
    blob = base64.b64encode(json.dumps(payload).encode()).decode()
    model = f" --model {shlex.quote(payload['model'])}" if payload.get("model") else ""
    return (
        'D=$(mktemp -d) || exit 1; '
        f'printf %s {blob} | base64 -d > "$D/p.json" || exit 1; '
        f'python3 -c {shlex.quote(_SPLIT)} "$D" || exit 1; '
        f'{predict} predict --state-file "$D/s.txt" --questions "$D/q.json"{model}; '
        # `status` is read-only in zsh, which is the default login shell on macOS.
        'rc=$?; rm -rf "$D"; exit $rc'
    )


def run_remote(payload: dict, host: str, predict: str = DEFAULT_PREDICT,
               timeout: int = 180, ssh_options: list[str] | None = None) -> Result:
    if not host or host.startswith("-"):
        raise TransportError(f"invalid ssh host {host!r}")
    opts = ssh_options or ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]
    # `--` ends ssh's option parsing, so the host is always read as a destination.
    cmd = ["ssh", *opts, "--", host, remote_command(payload, predict)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise TransportError(f"no answer from {host} in {timeout}s — is it asleep?") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        hint = tail[-1] if tail else "no output"
        if any(k in hint for k in ("Connection refused", "timed out", "No route to host", "Permission denied")):
            hint += f" — cannot reach {host}"
        raise TransportError(f"remote prediction failed: {hint}")
    return _parse(proc.stdout, "remote", None)
