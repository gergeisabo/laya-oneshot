"""Unit tests. No model, no network — the transport is only inspected, never run."""
import base64
import json
import unittest

from laya_oneshot.questions import choose_checkpoint, from_args, load_preset, pick_checkpoint
from laya_oneshot.transport import remote_command
from laya_oneshot.cli import bar, render


class TestQuestions(unittest.TestCase):
    def test_plain_ask_is_yes_no(self):
        q = from_args(["--ask", "Is this urgent?"])
        self.assertEqual(q["q1"]["type"], "noul")
        self.assertEqual(q["q1"]["instructions"], "Is this urgent?")

    def test_choices_attach_to_previous_ask(self):
        q = from_args(["--ask", "Which team?", "--choice", "billing=invoices",
                       "--choice", "sales", "--ask", "Second question?"])
        self.assertEqual(q["q1"]["type"], "choice")
        self.assertEqual(q["q1"]["criteria"]["billing"], "invoices")
        self.assertIsNone(q["q1"]["criteria"]["sales"])
        self.assertEqual(q["q2"]["type"], "noul")

    def test_levels_make_a_score(self):
        q = from_args(["--ask", "How hard?", "--level", "easy", "--level", "hard"])
        self.assertEqual(q["q1"]["type"], "score")
        self.assertEqual(q["q1"]["criteria"], ["easy", "hard"])

    def test_no_ask_raises(self):
        with self.assertRaises(ValueError):
            from_args(["--choice", "billing"])

    def test_every_preset_loads(self):
        for name in ("triage", "email", "guard", "router"):
            preset = load_preset(name)
            self.assertIsInstance(preset, dict)
            self.assertTrue(preset)
            for question in preset.values():
                self.assertIn(question["type"], ("choice", "noul", "score"))

    def test_unknown_preset_lists_alternatives(self):
        with self.assertRaises(ValueError) as ctx:
            load_preset("nope")
        self.assertIn("triage", str(ctx.exception))


class TestCheckpoint(unittest.TestCase):
    def test_ascii_gets_english(self):
        self.assertEqual(pick_checkpoint("refund my money"), "convaiinnovations/laya")

    def test_accents_get_multilingual(self):
        self.assertEqual(pick_checkpoint("kérem a pénzt vissza"),
                         "convaiinnovations/laya-multilingual")

    def test_cyrillic_and_cjk_get_multilingual(self):
        for text in ("верните деньги", "\u8bf7\u9000\u6b3e"):
            self.assertEqual(pick_checkpoint(text), "convaiinnovations/laya-multilingual")

    def test_aliases_resolve_to_repos(self):
        self.assertEqual(pick_checkpoint("x", "laya"), "convaiinnovations/laya")
        self.assertEqual(pick_checkpoint("x", "multilingual"),
                         "convaiinnovations/laya-multilingual")

    def test_explicit_repo_passes_through(self):
        self.assertEqual(pick_checkpoint("x", "someone/custom-laya"), "someone/custom-laya")


class TestCheckpointLanguage(unittest.TestCase):
    """0.1.0 shipped a non-ASCII test only, so accentless Hungarian silently ran on the
    English checkpoint and was confidently wrong. These are the regression tests."""

    def test_accentless_hungarian_is_detected(self):
        text = "kerem a penzt vissza, nem kell a szamla, csak a visszaterites"
        repo, why = choose_checkpoint(text)
        self.assertEqual(repo, "convaiinnovations/laya-multilingual")
        self.assertIn("without accents", why)

    def test_short_accentless_hungarian_with_one_hit(self):
        repo, _ = choose_checkpoint("nem kell")
        self.assertEqual(repo, "convaiinnovations/laya-multilingual")

    def test_plain_english_stays_english(self):
        for text in ("Refund me today or I am cancelling.",
                     "The van is red and the ferry leaves at six.",
                     "Please send the invoice to accounting."):
            self.assertEqual(choose_checkpoint(text)[0], "convaiinnovations/laya", text)

    def test_explicit_language_beats_the_heuristic(self):
        repo, why = choose_checkpoint("Refund me today", language="hu")
        self.assertEqual(repo, "convaiinnovations/laya-multilingual")
        self.assertIn("language=hu", why)
        repo, _ = choose_checkpoint("kerem a penzt vissza", language="en")
        self.assertEqual(repo, "convaiinnovations/laya")

    def test_unknown_language_raises(self):
        with self.assertRaises(ValueError):
            choose_checkpoint("hello", language="klingon")

    def test_requested_model_still_wins(self):
        repo, why = choose_checkpoint("kerem a penzt", requested="laya")
        self.assertEqual(repo, "convaiinnovations/laya")
        self.assertEqual(why, "requested")

    def test_hungarian_with_accents(self):
        repo, why = choose_checkpoint("kérem a pénzt vissza")
        self.assertEqual(repo, "convaiinnovations/laya-multilingual")
        self.assertIn("non-ASCII", why)


class TestWaitFlag(unittest.TestCase):
    def test_remote_failure_is_not_a_negative_answer(self):
        from laya_oneshot.transport import TransportError
        from laya_oneshot.cli import _with_wait
        calls = {"n": 0}

        def boom(*a, **k):
            calls["n"] += 1
            raise TransportError("no route to host")

        import laya_oneshot.cli as cli_mod
        original = cli_mod.run_remote
        cli_mod.run_remote = boom
        try:
            with self.assertRaises(TransportError) as ctx:
                _with_wait("host", {"state": "x"}, "laya-mlx", 5, 0)
            self.assertIn("not a negative answer", str(ctx.exception))
            self.assertEqual(calls["n"], 1)
            calls["n"] = 0
            with self.assertRaises(TransportError):
                _with_wait("host", {"state": "x"}, "laya-mlx", 5, 2)
            self.assertGreaterEqual(calls["n"], 2)
        finally:
            cli_mod.run_remote = original


class TestRemoteCommand(unittest.TestCase):
    def payload(self):
        return {"state": "hello", "questions": {"q1": {"type": "noul", "instructions": "?"}},
                "model": "convaiinnovations/laya"}

    def test_payload_travels_base64(self):
        cmd = remote_command(self.payload())
        blob = base64.b64encode(json.dumps(self.payload()).encode()).decode()
        self.assertIn(blob, cmd)

    def test_no_heredoc_and_cleans_up(self):
        cmd = remote_command(self.payload())
        self.assertIn("mktemp -d", cmd)
        self.assertIn("rm -rf", cmd)
        self.assertNotIn("<<", cmd)

    def test_state_is_never_interpolated_into_the_shell(self):
        payload = self.payload()
        payload["state"] = "'; rm -rf / #"
        cmd = remote_command(payload)
        self.assertNotIn("rm -rf / #", cmd)

    def test_avoid_zsh_reserved_names(self):
        # `status` is read-only in zsh: using it as a variable killed the remote call once.
        self.assertNotIn("status=", remote_command(self.payload()))

    def test_model_is_shell_quoted(self):
        payload = self.payload()
        payload["model"] = "convaiinnovations/laya; touch /tmp/pwned"
        cmd = remote_command(payload)
        self.assertIn("touch /tmp/pwned", cmd)      # inside quotes, not executed as a separate command
        self.assertNotIn("; touch /tmp/pwned;", cmd)


class TestRender(unittest.TestCase):
    body = {
        "answers": {
            "intent": {"type": "choice", "choice": "refund",
                       "probabilities": {"refund": 0.97, "cancellation": 0.02, "other": 0.01}},
            "is_urgent": {"type": "noul", "noul": 0.71},
            "frustration": {"type": "score", "score": 2.1},
        },
        "usage": {"input_tokens": 342},
    }
    questions = {"frustration": {"type": "score", "criteria": ["calm", "civil", "annoyed", "angry"]}}

    def test_renders_each_question_type(self):
        out = render(self.body, self.questions, 1234.0, "remote", "laya")
        self.assertIn("refund", out)
        self.assertIn("yes", out)
        self.assertIn("annoyed", out)
        self.assertIn("laya · 342 tokens · 1234 ms · remote", out)

    def test_bar_extremes(self):
        self.assertEqual(bar(0.0, 4), "░░░░")
        self.assertEqual(bar(1.0, 4), "████")


if __name__ == "__main__":
    unittest.main()
