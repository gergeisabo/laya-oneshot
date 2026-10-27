---
name: typed-decisions
description: Use when a fast yes/no, choice or score judgment is needed on text.
---

# Typed decisions

`laya-oneshot` answers typed questions about a piece of text with probabilities, in about a
second, without a model server or an API key. It never generates prose, so there is nothing
to parse and nothing to hallucinate.

    laya-oneshot "text to judge"                       # triage: intent, urgency, churn, refund
    laya-oneshot --preset email --file mail.txt        # category, spam, phishing, urgency
    laya-oneshot --preset guard "$PROMPT"              # jailbreak, injection, sensitive data
    laya-oneshot --ask "Is this a bug report?" --threshold 0.8 "..."

Exit codes: `0` answered above threshold, `1` below threshold, `2` could not decide (model
unreachable). Pass `--json` for the raw Jev-shaped response.

Do not use it for multi-step reasoning or anything you would not trust a 400M-parameter
encoder with. It is a fast filter in front of the expensive call, not a replacement for it.
