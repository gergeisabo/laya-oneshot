"""Build a question set, and pick the checkpoint that suits the text.

The Laya CLI does **not** route by language: left alone it answers Hungarian with
the English checkpoint and collapses silently (measured: ``intent=other 0.38``
instead of ``cancellation 0.96``). So the checkpoint is chosen here.

Choosing by "contains a non-ASCII character" is not enough, and that mistake shipped
in 0.1.0: Hungarian written without accents (``kerem a penzt vissza``) is pure ASCII, so
it silently ran on the English checkpoint — which is not weaker there, it is confidently
wrong. 0.2.0 adds a word-level Hungarian test and an explicit ``language`` override for
streams whose language is already known, because a heuristic should not be the last word.
"""
from __future__ import annotations

import json
import re
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

# Words that are evidence of Hungarian and cannot be confused with English. Deliberately
# excludes short ambiguous tokens that happen to exist in English too: a, az, is, de, meg,
# mar, ar, van, volt, lesz, ott, itt, ha, mi — including them produced false positives.
_HU_WORDS = frozenset("""
hogy nem kell csak mert kerem kerek kerlek szeretnek szeretnem szeretnénk tudnal tudnál
koszonom köszönöm szamla számla szamlat számlát miatt utan után elott előtt alatt vagyok vagyunk
nekem neki ezt azt ezeket azokat majd tudom latom látom udvozlettel üdvözlettel rendben miert miért
mikor mennyi mennyibe arajanlat árajánlat megrendeles megrendelés szallitas szállítás fizetes fizetés
visszaterites visszatérítés hiba hibas hibás mukodik működik nincs nagyon most megint valami valamit
semmi mindig soha kene kéne lehet tudna tudnánk lenne voltak vannak lesznek kaptam kaptunk kuldott
küldött valasz válasz uzenet üzenet hivas hívás talalkozo találkozó hatarido határidő szamlaszam
számlaszám atutalás átutalás bankkartya bankkártya terheles terhelés egyenleg kifizetes kifizetés
""".split())

# Hungarian digraphs are common in Hungarian and rare in English. Used only as a tiebreak.
_HU_DIGRAPHS = ("sz", "gy", "ny", "ty", "zs", "cs", "ly")


def _hungarian_score(state: str) -> tuple[int, int]:
    """(distinct Hungarian words, digraph occurrences) for lowercase ASCII text."""
    words = re.findall(r"[a-z\u00c0-\u017f]+", state.lower())
    hits = sum(1 for w in words if w in _HU_WORDS)
    digraphs = sum(state.lower().count(d) for d in _HU_DIGRAPHS)
    return hits, digraphs


def choose_checkpoint(state: str, requested: str | None = None,
                      language: str | None = None) -> tuple[str, str]:
    """Return (repo id, why). Explicit request beats explicit language beats the heuristic."""
    if requested:
        return ALIASES.get(requested, requested), "requested"
    lang = (language or "auto").strip().lower()
    if lang in ("hu", "hun", "hungarian", "multilingual", "multi"):
        return REPO_MULTILINGUAL, f"language={lang}"
    if lang in ("en", "eng", "english"):
        return REPO_ENGLISH, f"language={lang}"
    if lang not in ("auto", ""):
        raise ValueError(f"unknown language {language!r} — use en, hu or auto")
    non_ascii = any(ord(c) > 127 for c in state)
    if non_ascii:
        return REPO_MULTILINGUAL, "non-ASCII characters"
    hits, digraphs = _hungarian_score(state)
    if hits >= 2 or (hits == 1 and len(state.split()) <= 6) or digraphs >= 4:
        return REPO_MULTILINGUAL, f"Hungarian words without accents ({hits} hits, {digraphs} digraphs)"
    return REPO_ENGLISH, "ASCII text, no Hungarian markers"


def pick_checkpoint(state: str, requested: str | None = None) -> str:
    """Back-compat wrapper: the repo id only."""
    return choose_checkpoint(state, requested)[0]


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
