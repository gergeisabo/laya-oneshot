"""Build a question set, and pick the checkpoint that suits the text.

The Laya CLI does **not** route by language: left alone it answers Hungarian with
the English checkpoint and collapses silently (measured: ``intent=other 0.38``
instead of ``cancellation 0.96``). So the checkpoint is chosen here, from the
script of the state.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ENGLISH = "convaiinnovations/laya"
REPO_MULTILINGUAL = "convaiinnovations/laya-multilingual"

# Router names (what an HTTP service calls them) -> Hugging Face repo ids (what the CLI wants).
ALIASES = {
    "laya": REPO_ENGLISH,
    "laya:en": REPO_ENGLISH,
    "english": REPO_ENGLISH,
    "laya:multilingual": REPO_MULTILINGUAL,
    "multilingual": REPO_MULTILINGUAL,
    "laya:typed-decisions": "convaiinnovations/laya-typed-decisions",
}


def pick_checkpoint(state: str, requested: str | None = None) -> str:
    """Non-ASCII text almost always means non-English; the English checkpoint is not
    merely weaker there, it is confidently wrong."""
    if requested:
        return ALIASES.get(requested, requested)
    return REPO_MULTILINGUAL if any(ord(c) > 127 for c in state) else REPO_ENGLISH


def from_args(tokens: list[str]) -> dict:
    """Turn ``--ask "..." [--choice a --choice b] [--level x]`` into a question set.

    Options bind to the question before them, so the sequence on the command line
    is the sequence of the conversation.
    """
    out: dict[str, dict] = {}
    pending: str | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "--ask":
            pending = f"q{len(out) + 1}"
            out[pending] = {"type": "noul", "instructions": tokens[i + 1]}
            i += 2
        elif token == "--choice" and pending:
            label, _, desc = tokens[i + 1].partition("=")
            question = out[pending]
            question.setdefault("criteria", {})[label] = desc or None
            question["type"] = "choice"
            i += 2
        elif token == "--level" and pending:
            question = out[pending]
            question.setdefault("criteria", []).append(tokens[i + 1])
            question["type"] = "score"
            i += 2
        else:
            i += 1
    if not out:
        raise ValueError("--ask needs at least one question")
    return out


def load_preset(name_or_path: str) -> dict:
    path = Path(name_or_path)
    if path.suffix == ".json" and path.exists():
        return json.loads(path.read_text())
    builtin = Path(__file__).parent / "presets" / f"{name_or_path}.json"
    if builtin.exists():
        return json.loads(builtin.read_text())
    available = sorted(p.stem for p in (Path(__file__).parent / "presets").glob("*.json"))
    raise ValueError(f"unknown preset {name_or_path!r} — available: {', '.join(available)}")
