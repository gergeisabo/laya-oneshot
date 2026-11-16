"""Hermes plugin: typed decisions from an open Laya model that isn't running.

Thin wrapper over the bundled ``laya_oneshot`` package. The package owns the
model handling; this plugin only exposes one tool so an agent can ask a typed
question without a shell round trip.

The ssh host is read only from the user's own config
(``~/.config/laya-oneshot/config`` or ``LAYA_ONESHOT_HOST``), never from the
tool call. The checkpoint argument is limited to the known Laya repo ids.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_NAME = "laya-oneshot"

_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from laya_oneshot.questions import known_checkpoints  # noqa: E402


def _cli() -> list[str] | None:
    if not (_PLUGIN_DIR / "laya_oneshot" / "cli.py").is_file():
        return None
    return [sys.executable, "-m", "laya_oneshot.cli"]


def _decide(args=None, **kw):
    args = args or {}
    state = (args.get("state") or args.get("text") or "").strip()
    if not state:
        return json.dumps({"error": "state is required: the text to decide about"})

    cli = _cli()
    if not cli:
        return json.dumps({
            "error": "laya-oneshot is not installed",
            "install": "reinstall the plugin: hermes plugins install gergeisabo/laya-oneshot",
        })

    model = args.get("model")
    if model and str(model) not in known_checkpoints():
        return json.dumps({
            "error": f"unknown checkpoint {model!r}",
            "allowed": sorted(known_checkpoints()),
        })

    cmd = [*cli, "--json"]
    preset = args.get("preset")
    if preset:
        cmd += ["--preset", str(preset)]
    for question in args.get("ask") or []:
        cmd += ["--ask", str(question)]
    if model:
        cmd += ["--model", str(model)]
    cmd += ["--", state]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, cwd=_PLUGIN_DIR)
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
                "generate text and it keeps nothing running. The model host comes from the "
                "user's laya-oneshot config, not from this call."
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
                    "model": {
                        "type": "string",
                        "enum": sorted(known_checkpoints()),
                        "description": "Force one of the known Laya checkpoints. Default picks by script.",
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
