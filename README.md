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

The host has to be awake. A sleeping machine cannot answer, and it will not wake for ssh, so a
batch that runs overnight will silently collect failures. Two things make that survivable:

- `--wait SECONDS` keeps retrying while the host is unreachable, then gives up with exit `2` and
  the words *"this is not a negative answer"* — so a sleeper is never scored as a `no`.
- On macOS, `caffeinate -s` in a LaunchAgent keeps the machine awake **only while it is on AC
  power**: plugged in it stays reachable, unplugged it naps as usual. It asserts no CPU and no
  memory — the model still loads per call.

If a host is unreachable, check the transport before the model: `netbird status` / `ping` first, and
only then the service. On 2026-11-03 a ten-minute sleep of the model host produced exactly the
same `exit 2` as a broken server would have.

## The checkpoint trap

`laya-mlx predict` does **not** route by language. Left to itself it answers Hungarian with the
English checkpoint, which does not degrade gracefully — it is confidently wrong:

```console
$ laya-oneshot --model laya "Harmadszor terheltek meg tévesen idén. A pénzt ma visszakérem, különben felmondom a szerződést."
intent           other                   ██████████░░░░░░░░░░░░░░ 0.38

$ laya-oneshot "Harmadszor terheltek meg tévesen idén. A pénzt ma visszakérem, különben felmondom a szerződést."
intent           cancellation            █████████████████████░░░ 0.96
```

0.1.0 picked the checkpoint from one test: "does the text contain a non-ASCII character?" That
misses **Hungarian written without accents**, which is common in chat and short replies, so
`kerem a penzt vissza` ran on the English checkpoint — silently, and confidently wrong. 0.2.0
tests for Hungarian words and digraphs as well:

```console
$ laya-oneshot --dry-run --ask "Is this urgent?" "kerem a penzt vissza, nem kell a szamla"
"model": "convaiinnovations/laya-multilingual",
"checkpoint_because": "Hungarian words without accents (6 hits, 4 digraphs)"
```

The check is a heuristic, so you can skip it: `--language hu` (or `en`) forces the checkpoint,
and `language=hu` in the config applies it to every call. Set it explicitly in any pipeline whose
language you already know — a heuristic should not be the last word. `--model` still overrides both.

Note also that the multilingual checkpoint ships **uncalibrated** — treat its numbers as a ranking,
not a confidence.

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

## Measured, not claimed — and the answer is "not for production"

Three rounds of testing. The first two were mine, on small hand-built sets, and they looked
encouraging. The third was 1,099 scored calls with majority-class baselines, and it killed every use
case. Read that one first.

### Round 3 — 1,099 calls, four use cases, all rejected

| Use case | Result |
|---|---|
| "Documentation-only?" gate, 238 commits | **130/226 code commits passed the 0.9 gate as docs** — worse than "always say code" (95%). I reproduced it independently on 40 commits: 28/40 cleared 0.9. Ship the `git diff --name-only` rule (238/238, free) |
| "Is this thread waiting for me?" on 62 real mail threads | waiting recall **0.182** against a required 0.95; the sender blocklist it would replace is at 1.000 |
| Phishing pre-flag on 33 real receipts/alerts + 12 scams | precision **0.279**; 31 of 33 legitimate mails flagged, 24 at p = 1.000 |
| "Is this page text talking to the AI?" (30 injections, 49 pages) | best false-alarm rate at recall 0.90 was **20.4%** (limit 10%), and the two hardest misses are the attacker-shaped ones |

Full report: `2026-11-03-laya-oneshot-use-case-tests.md` in the owner's vault. The numbers above are
reproducible from the scripts in this repo plus the corpus named there.

**What that means for you: don't put this in a pipeline that matters.** A 400M-parameter encoder
reading wording cannot tell a receipt from a fraud, or a code fix from a docstring change, however
confident it looks. On every use case that was measured properly, a deterministic rule — file
extension, sender address, a regex — was exact, free, and beat it.

### Rounds 1–2, for the record (small sets, since refuted)

| Task | Result | Status |
|---|---|---|
| "Documentation-only?" gate, 29 commits | 26/29 (90%), *"18/18 code commits never passed"* | **refuted** in round 3 |
| Phishing / not, 8 emails (4 scams) | 7/8 (88%) | **refuted** at scale (precision 0.279) |
| Email triage, 4 categories, 12 mails | 9/12 (75%) | superseded |
| Short text, binary question (control) | 7/8 (88%), 0.00 on off-topic | holds — it does discriminate on short clean text |
| Domain routing over 20 skill docs | 60%, then 55% | **withdrawn** — the labels measured my filing system, not the question |

Two things that did survive, and they are about question design rather than model size:

1. **Ask narrow questions.** A bank-change scam scored "billing" 0.61 inside a 4-way category and
   0.99 when asked directly "is this phishing?" — though round 3 showed even 0.99 does not mean the
   flag is worth anything, because real receipts also score 1.000.
2. **Do not ask a question that is "sort of" true for most of your inputs.** If the answer is
   ambiguous in your own head, the probability you get back means nothing — and it will still look
   confident.

The probabilities are not calibrated. Right and wrong answers both arrive at 0.5–1.0.

**So why does this repo exist?** As the smallest working example of the *operating model*: an open
encoder, loaded per call on a machine that is otherwise off, over ssh, with no daemon and no key. The
plumbing is the contribution. The model is a demo, and the honest thing to say about a demo is where
it stops.

## Credit

The model is [Laya](https://github.com/NandhaKishorM/laya) by Nandakishor M (Convai
Innovations). The Apple Silicon runtime is [laya-mlx](https://github.com/mizorewww/laya-mlx).
The "typed decision" request shape comes from TypeSafe's Jev; `POST /v1/systemone` is their
wire format. Existing CLIs ([semdecide](https://github.com/sharziki/semdecide),
[jevkit](https://github.com/ariel-frischer/jevkit), [go-jev](https://github.com/mattn/go-jev))
call the hosted API — this one exists for people who would rather run open weights on their own
hardware and not keep them running.

MIT.
