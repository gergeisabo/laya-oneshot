---
name: laya-oneshot
description: "Use when a fast typed judgment is needed on text."
version: 1.0.0
author: Gergely Szabo
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [decisions, classification, triage, laya, local-models]
    category: productivity
    related_skills: []
---

# Typed decisions in about a second

`laya-oneshot` answers typed questions about a piece of text — yes/no, pick one of N, score on a
scale — with probabilities, from an open ~400M-parameter encoder. It generates no text, so there
is nothing to parse and nothing to hallucinate. The model is loaded for one call and the process
exits: no daemon, no port, no resident memory.

## When to use

- Sorting or triaging text (support mail, tickets, notes, transcripts).
- A yes/no gate before an action, a redirect, or an expensive model call.
- Picking one of a small, named set of labels.
- A 1–4 severity or urgency score.

Don't use it for multi-step reasoning, long documents, or any decision where being confidently
wrong costs money.

## Commands

    laya-oneshot "text"                            # triage preset
    laya-oneshot --preset email --file mail.txt    # category, spam, phishing, urgency, needs reply
    laya-oneshot --preset guard "$PROMPT"          # jailbreak, injection, sensitive data, harm
    laya-oneshot --preset router "user request"    # difficulty, needs code, needs fresh data
    laya-oneshot --ask "Is this a bug report?" "the export throws a 500"
    laya-oneshot --ask "Which team?" --choice billing --choice sales --ask "Is it urgent?"
    cat ticket.txt | laya-oneshot --json

Exit codes: `0` answered above the threshold, `1` below it, `2` could not decide. `--dry-run`
prints the payload without running anything.

## Reading the answer

The JSON mirrors Jev: `answers.<id>` carries `type` plus `probabilities` (choice), `noul` (a
probability for yes), or `score` (a number, with the level labels). Trust the ordering more than
the digits — and specifically do not trust a `churn_risk`-style label until it has been trained on
your own data; it has been measured wrong on textbook cases.

## If it is slow or unreachable

The model usually lives on another machine (`host=` and `predict=` in
`~/.config/laya-oneshot/config`). A call takes ~1.5 s cold. `exit 2` with "is it asleep?" means the
model host is asleep, not that the tool is broken. Install with
`uv tool install git+https://github.com/gergeisabo/laya-oneshot`.
