"""Hermes plugin: typed decisions from an open Laya model that isn't running.

Thin wrapper over the `laya-oneshot` CLI. The CLI owns the model handling; this
plugin only exposes one tool so an agent can ask a typed question without a
shell round trip.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PLUGIN_NAME = "laya-oneshot"

_CANDIDATES = (
    Path.home() / ".local/bin/laya-oneshot",
    Path.home() / ".local/share/uv/tools/laya-oneshot/bin/laya-oneshot",
    Path("/opt/homebrew/bin/laya-oneshot"),
)


def _cli() -> str | None:
    found = shutil.which("laya-oneshot")
    if found:
        return found
    for candidate in _CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def _decide(args=None, **kw):
    args = args or {}
    state = (args.get("state") or args.get("text") or "").strip()
    if not state:
        return json.dumps({"error": "state is required: the text to decide about"})

    cli = _cli()
    if not cli:
        return json.dumps({
            "error": "laya-oneshot is not installed",
            "install": "uv tool install git+https://github.com/gergeisabo/laya-oneshot",
        })

    cmd = [cli, "--json"]
    preset = args.get("preset")
    if preset:
        cmd += ["--preset", str(preset)]
    for question in args.get("ask") or []:
        cmd += ["--ask", str(question)]
    if args.get("host"):
        cmd += ["--host", str(args["host"])]
    if args.get("model"):
        cmd += ["--model", str(args["model"])]
    cmd += ["--", state]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "the decision model did not answer in 180s"})
    if proc.returncode != 0:
        return json.dumps({"error": (proc.stderr or proc.stdout).strip()[:400]})
    try:
        return proc.stdout
    except Exception as exc:  # pragma: no cover - defensive
        return json.dumps({"error": str(exc)})


def register(ctx):
    ctx.register_tool(
        name="laya_decide",
        toolset="laya-oneshot",
        schema={
            "name": "laya_decide",
            "description": (
                "Answer typed questions about a piece of text with probabilities, in about a "
                "second: yes/no, pick one of N, or a score on a scale. Returns the Jev-shaped "
                "JSON (answers, probabilities, usage). Use it as a cheap filter in front of an "
                "expensive model call — triage, routing, guardrails, yes/no gates. It does not "
                "generate text and it keeps nothing running."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "description": "The text to decide about: a message, an email, a ticket, a request.",
                    },
                    "preset": {
                        "type": "string",
                        "enum": ["triage", "email", "guard", "router"],
                        "description": "Built-in question set. triage = intent/urgency/frustration/refund/churn; "
                                       "email = category/spam/phishing/urgency/needs_reply; guard = jailbreak/injection/"
                                       "sensitive/harm; router = difficulty/needs_code/needs_fresh_data.",
                    },
                    "ask": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Your own yes/no questions instead of a preset. Repeatable.",
                    },
                    "host": {
                        "type": "string",
                        "description": "Run the model on this ssh host instead of locally, e.g. me@10.0.0.5.",
                    },
                    "model": {
                        "type": "string",
                        "description": "Force a checkpoint; default picks by script (English vs multilingual).",
                    },
                },
                "required": ["state"],
            },
        },
        handler=_decide,
        check_fn=lambda: _cli() is not None,
        requires_env=[],
        description="Typed decision (yes/no, choice, score) in about a second",
        emoji="⚖️",
    )
