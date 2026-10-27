"""laya-oneshot — a typed decision from a model that is not running.

    laya-oneshot "Third time you double-charged me. Refund today or I cancel."

Loads the checkpoint, reads the answer out of one forward pass, exits. Nothing
stays resident, nothing listens on a port.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__
from .questions import from_args, load_preset, pick_checkpoint
from .transport import DEFAULT_PREDICT, TransportError, run_local, run_remote

CONFIG_PATH = os.path.expanduser("~/.config/laya-oneshot/config")
PRESETS = ("triage", "email", "guard", "router")


def read_config() -> dict:
    config = {}
    if os.path.exists(CONFIG_PATH):
        for line in open(CONFIG_PATH, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()
    for key in ("HOST", "PREDICT", "MODEL", "THRESHOLD"):
        env = os.environ.get(f"LAYA_ONESHOT_{key}")
        if env:
            config[key.lower()] = env
    return config


def render(body: dict, questions: dict, elapsed_ms: float, transport: str, route: str | None) -> str:
    lines = []
    for name, answer in (body.get("answers") or {}).items():
        kind = answer.get("type")
        if kind == "choice":
            probs = answer.get("probabilities") or {}
            top = max(probs, key=probs.get) if probs else answer.get("choice")
            value = probs.get(top, 0.0)
            runners = ", ".join(f"{k} {v:.2f}" for k, v in
                                sorted(probs.items(), key=lambda kv: -kv[1])[1:3])
            lines.append(f"{name:<17}{top:<24}{bar(value)} {value:.2f}   ({runners})")
        elif kind == "noul":
            p = float(answer.get("noul", 0.0))
            label = "yes" if p > 0.5 else "no"
            lines.append(f"{name:<17}{label:<24}{bar(max(p, 1 - p))} {max(p, 1 - p):.2f}")
        elif kind == "score":
            value = answer.get("score")
            levels = (questions.get(name) or {}).get("criteria") or []
            index = round(value) if value is not None else 0
            legend = levels[index] if levels and 0 <= index < len(levels) else ""
            filled = max(1, round(6 * (value or 0)))
            lines.append(f"{name:<17}{value if value is None else f'{value:.2f}':<24}"
                         f"{'█' * filled}{'░' * (12 - filled)} {legend}")
    usage = body.get("usage") or {}
    lines.append("")
    lines.append(f"{route or '?'} · {usage.get('input_tokens', '?')} tokens · "
                 f"{elapsed_ms:.0f} ms · {transport}")
    if route and route.endswith("multilingual"):
        lines.append("note: the multilingual checkpoint ships uncalibrated — read probabilities as rough ranks.")
    return "\n".join(lines)


def bar(value: float, width: int = 24) -> str:
    filled = round(width * max(0.0, min(1.0, value)))
    return "█" * filled + "░" * (width - filled)


def top_probability(body: dict) -> float | None:
    for answer in (body.get("answers") or {}).values():
        if answer.get("type") == "choice":
            probs = answer.get("probabilities") or {}
            return max(probs.values()) if probs else None
        if answer.get("type") == "noul":
            p = float(answer.get("noul", 0.0))
            return max(p, 1 - p)
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="laya-oneshot",
        description="One typed decision from an open Laya model. Loads, answers, exits.")
    parser.add_argument("state", nargs="?", help="text to decide about (default: stdin)")
    parser.add_argument("--file", help="read the state from a file")
    parser.add_argument("--preset", default="triage",
                        help=f"built-in question set: {', '.join(PRESETS)} (default: triage), or a JSON file")
    parser.add_argument("--ask", action="append", metavar="QUESTION",
                        help="ask your own question: yes/no by default; repeatable")
    parser.add_argument("--choice", action="append", metavar="LABEL[=DESC]",
                        help="an option for the previous --ask")
    parser.add_argument("--level", action="append", metavar="TEXT",
                        help="a level for the previous --ask, lowest first (makes it a score)")
    parser.add_argument("--model", help="force a checkpoint (repo id or laya/multilingual); default: by script")
    parser.add_argument("--host", help="run on this ssh host instead of locally, e.g. my-mac")
    parser.add_argument("--predict", help=f"path to the laya-mlx CLI (default: {DEFAULT_PREDICT})")
    parser.add_argument("--timeout", type=int, default=180, help="seconds before giving up (default: 180)")
    parser.add_argument("--threshold", type=float,
                        help="exit 1 when the first answer is less confident than this (0-1)")
    parser.add_argument("--json", action="store_true", help="print the raw response")
    parser.add_argument("--dry-run", action="store_true", help="print the payload and the remote command, run nothing")
    parser.add_argument("--version", action="version", version=f"laya-oneshot {__version__}")
    args = parser.parse_args(raw)

    config = read_config()

    if args.file:
        state = open(args.file, encoding="utf-8", errors="replace").read()
    elif args.state:
        state = args.state
    elif not sys.stdin.isatty():
        state = sys.stdin.read()
    else:
        parser.error("no text to decide about — pass it as an argument, with --file, or on stdin")
    if not state.strip():
        parser.error("empty text")

    try:
        questions = from_args(raw) if args.ask else load_preset(args.preset)
    except (ValueError, IndexError) as exc:
        parser.error(str(exc))

    model = pick_checkpoint(state, args.model or config.get("model"))
    payload = {"state": state, "questions": questions, "model": model}

    host = args.host or config.get("host")
    predict = args.predict or config.get("predict") or DEFAULT_PREDICT

    if args.dry_run:
        print(json.dumps({"payload": payload, "host": host, "predict": predict}, indent=2, ensure_ascii=False))
        if host:
            from .transport import remote_command
            print("\nremote command:\n" + remote_command(payload, predict))
        return 0

    started = time.time()
    try:
        if host:
            result = run_remote(payload, host, predict, timeout=args.timeout)
        else:
            result = run_local(payload, predict, timeout=args.timeout)
    except TransportError as exc:
        print(f"laya-oneshot: {exc}", file=sys.stderr)
        return 2
    elapsed = (time.time() - started) * 1000
    route = (result.body.get("routing") or {}).get("model") or model.rsplit("/", 1)[-1]

    if args.json:
        print(json.dumps(result.body, indent=2, ensure_ascii=False))
    else:
        print(render(result.body, questions, elapsed, result.transport, route))

    threshold = args.threshold if args.threshold is not None else _float_or_none(config.get("threshold"))
    if threshold is not None:
        top = top_probability(result.body)
        if top is not None and top < threshold:
            return 1
    return 0


def _float_or_none(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    sys.exit(main())
