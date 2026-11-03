# laya-oneshot

**Typed decisions from an open Laya model that isn't running.** Load, answer, exit — no
daemon, no port, no resident RAM, no API key.

```console
$ laya-oneshot "Third time this year you have double-charged me. Refund it today or I am cancelling."
intent           refund                  ████████████████████████ 1.00   (cancellation 0.00, billing_question 0.00)
is_urgent        yes                     ████████████████░░░░░░░░ 0.67
frustration      2.28                    ██████████████ clearly annoyed
refund_requested yes                     ███████████████████████░ 0.95
churn_risk       no                      █████████████░░░░░░░░░░░ 0.53

laya · 342 tokens · 1574 ms · remote
```

A [Laya](https://github.com/NandhaKishorM/laya) checkpoint is a ~400M-parameter encoder that
answers *typed* questions — yes/no, pick one of N, score on a scale — with probabilities, in
one forward pass. It never generates text, so there is nothing to parse and nothing to
hallucinate. This tool runs one for a single call and then gets out of the way.

## Why not a server?

Because a decision server is a thing that must stay up: it holds ~3 GB resident, keeps a port
open, and needs supervision so it is there when a request arrives. For the way most people
actually use this — a judgement inside a script, a gate in CI, a check an agent makes every
few minutes — the model can be loaded on demand:

| | resident server | `laya-oneshot` |
|---|---|---|
| per call | ~200 ms | 1.2–1.6 s |
| memory when idle | ~2.8 GB | 0 |
| open ports | yes | none |
| what it needs | supervision | nothing |

You trade ~1.2 s for not running a service. If you *do* want the fast path, point it at a
server through the same config file (see below).

## Install

```console
$ pipx install laya-oneshot        # or: uv tool install laya-oneshot
```

The model runtime is the separate [laya-mlx](https://github.com/mizorewww/laya-mlx) package,
needed only on the machine that runs the prediction:

```console
$ pip install "laya-mlx[serve]"     # Apple Silicon; first call downloads ~2 GB of weights
```

## Use

```console
# built-in question sets
laya-oneshot "text"                          # triage: intent, urgency, frustration, churn, refund
laya-oneshot --preset email --file mail.txt  # category, spam, phishing, urgency, needs reply
laya-oneshot --preset guard "$PROMPT"        # jailbreak, injection, sensitive data, harm
laya-oneshot --preset router "user request"  # difficulty, needs code, needs fresh data

# your own questions
laya-oneshot --ask "Is this a bug report?" "the export button throws a 500"
laya-oneshot --ask "Which team?" --choice billing --choice sales --ask "Is it urgent?"

# machine-readable, scriptable
cat ticket.txt | laya-oneshot --json
laya-oneshot --ask "Clearly documentation only?" --threshold 0.85 "$(git log -1 --pretty=%B)"
```

Exit codes: `0` answered above the threshold, `1` answered below it, `2` could not decide.
Presets are plain JSON — copy one from `laya_oneshot/presets/` or pass any file with `--preset path/to/set.json`.

`laya-oneshot --dry-run "text"` prints exactly what would be sent, and runs nothing.

## Running it on another machine

This is the interesting mode: the model lives on a laptop that is otherwise off, and the
machine doing the thinking is something small.

```console
$ laya-oneshot --host me@100.64.0.2 --predict '~/AI/laya/venv/bin/laya-mlx' "text"
```

Put it in the config to stop typing it:

```ini
# ~/.config/laya-oneshot/config
host=me@100.64.0.2
predict=~/AI/laya/venv/bin/laya-mlx
threshold=0.8
```

The remote side needs Python 3, `laya-mlx`, and key-based ssh (`BatchMode=yes`, so it fails
fast instead of prompting). Everything else happens in one ssh round trip: the payload travels
base64-encoded, in a temp dir that is removed on exit. Nothing is installed on the remote host,
and nothing survives the call.

The host has to be awake — a machine that is asleep cannot answer, and you get
`2` with `is it asleep?` rather than a hang.

## The checkpoint trap

`laya-mlx predict` does **not** route by language. Left to itself it answers Hungarian with the
English checkpoint, which does not degrade gracefully — it is confidently wrong:

```console
$ laya-oneshot --model laya "Harmadszor terheltek meg tévesen idén. A pénzt ma visszakérem, különben felmondom a szerződést."
intent           other                   ██████████░░░░░░░░░░░░░░ 0.38

$ laya-oneshot "Harmadszor terheltek meg tévesen idén. A pénzt ma visszakérem, különben felmondom a szerződést."
intent           cancellation            █████████████████████░░░ 0.96
```

`laya-oneshot` picks `convaiinnovations/laya-multilingual` whenever the text contains a
non-ASCII character. Pass `--model` to override. Note also that the multilingual checkpoint
ships **uncalibrated** — treat its numbers as a ranking, not a confidence.

## When not to use it

- Multi-step reasoning, or anything where an ordinary LLM answer would need a citation.
- Anything where a wrong `churn_risk` costs money. It scored `0.009` (definitely not leaving)
  on "refund me today or I'm cancelling" in Hungarian. Train your own head before you trust a
  label like that.
- Long inputs: the English checkpoint reads 512 tokens, the multilingual one 1024 (8192 with
  `max_len`), and accuracy falls away well before the limit.

## Inside Hermes Agent

Two ways, neither of which needs a plugin store:

```console
# 1. as a skill (instructions only, no review, works today)
hermes skills install gergeisabo/laya-oneshot

# 2. as a plugin (one `laya_decide` tool in the agent's toolset)
hermes plugins install gergeisabo/laya-oneshot
hermes plugins enable laya-oneshot
```

The repo carries a `plugin.yaml` that passes `hermes plugins validate` (manifest, capability
probe, security scan, no core overrides). Catalog listing — the one that shows up in
`hermes plugins search` for everyone — is a separate PR to `NousResearch/hermes-agent` pinning
this repository at a full commit SHA; the entry is drafted in `contrib/plugin-catalog-entry.yaml`
once that review is worth opening.

## Measured, not claimed

Five tasks, 115 calls, zero failures, p50 1.4 s / p95 2.4 s (4 concurrent). Ground truth: my own
labels for the synthetic sets, the git file list for the gate test, the folder name for the routing
test. Labels are mine, so treat the numbers as a shape, not a benchmark table.

| Task | Result | What it means |
|---|---|---|
| Email triage, 4 categories, 12 mails | 9/12 (75%) | security mails read as "billing" — BEC is the weak class |
| "Documentation-only?" gate, 29 commits | 26/29 (90%) | 18/18 code commits never passed as docs — safe failure direction |
| Phishing / not, 8 emails (4 scams) | 7/8 (88%) | 4/4 scams caught, 1 false positive on a real reset mail |
| Short text, binary question (control) | 7/8 (88%) | clean 0.00 on off-topic, 0.7–0.8 on infrastructure |
| Hungarian triage, 6 mails | 4/6 (67%) | billing ↔ technical confusion |
| Domain routing over 20 skill docs | **withdrawn** | see below — the labels did not measure the question |

**One test was withdrawn.** I first reported 60% on "route this document to its domain", using the
skill's own folder as ground truth, then 55% after rewriting the label descriptions. Both numbers are
garbage: every one of those documents contains install steps, ssh commands and file paths, so
"is this about server infrastructure?" was answered *truthfully* for nearly all of them — the labels
measured my filing system, not the question. A control with eight short unambiguous texts scored 7/8,
with 0.00 on off-topic input, which is what disproved my "it just says yes" reading.

Two lessons that survived, both about question design rather than model size:

1. **Ask narrow questions.** The bank-details mail scored "billing" 0.61 as a 4-way category, and
   0.99 when asked directly "is this phishing?". Multiple yes/no questions beat one wide choice.
2. **Do not ask a question that is "sort of" true for most of your inputs.** If the answer is
   ambiguous in your own head, the probability you get back means nothing — and it will still look
   confident.

Confidence numbers are not calibrated — right and wrong answers both arrive at 0.5–1.0. Read the
ranking, and put a human behind any threshold you have not tuned on your own examples.

## Credit

The model is [Laya](https://github.com/NandhaKishorM/laya) by Nandakishor M (Convai
Innovations). The Apple Silicon runtime is [laya-mlx](https://github.com/mizorewww/laya-mlx).
The "typed decision" request shape comes from TypeSafe's Jev; `POST /v1/systemone` is their
wire format. Existing CLIs ([semdecide](https://github.com/sharziki/semdecide),
[jevkit](https://github.com/ariel-frischer/jevkit), [go-jev](https://github.com/mattn/go-jev))
call the hosted API — this one exists for people who would rather run open weights on their own
hardware and not keep them running.

MIT.
