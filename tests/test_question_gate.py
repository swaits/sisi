"""Rule 1 (own-the-outcome) enforcement: ending a turn by asking the human a question in reply text sends the agent back
once, where a question dialog exists and was not used in that turn (Claude Code)."""
import json, os, unittest
from support import *
from sisi import gate

ASK = [
    "All checks pass. Should I also update the changelog?",
    "Done. Do you want the button blue or grey?",
    "The migration is ready.\n\nWhich name should the new column have?",
    "Implemented and verified. Shall I open the pull request now?",
    "Fixed. What do you think of the new layout?",
    "Tests are green. Would you like me to remove the old parser too?",
    "Ready when you are. Can I go ahead and delete the legacy table?",
    "The export works. Do we need the legacy format as well?",
    "All set. Is Thursday still the target for this?",
    "The build passes. Should we ship it?",
]

NOT_ASK = [
    "All checks pass. The changelog is updated.",
    "Who wouldn't want a faster build?",
    "The issue asked: \"why does it crash on startup?\" and the fix answers it.",
    "Done.\n\n```\nresult = value if ready else fallback  # what about None?\n```",
    "> Should we cache this?\n\nNo: the data changes on every request, so I left it uncached.",
    "Fixed the `a ? b : c` case and the suite passes.",
    "What could possibly go wrong? Quite a lot, so the change is behind a flag.",
    "The report ends with the customer's words: \"can you fix it by Friday?\"",
    "Verified: rung 3, 41 examples, all passing.",
    "Why did it fail? Because the fixture was stale; it is regenerated now and checks pass.",
    "Shipped. The remaining question of naming is recorded as an assumption in the contract.",
    "Isn't it obvious in hindsight? The guard was inverted; fixed and pinned by a test.",
]


class DetectionTests(unittest.TestCase):
    def test_labelled_set(self):
        hits = [t for t in ASK if gate.ends_with_question(t)]
        alarms = [t for t in NOT_ASK if gate.ends_with_question(t)]
        self.assertEqual(len(hits), len(ASK), "missed: %r" % [t for t in ASK if t not in hits])
        self.assertEqual(alarms, [], "false alarms: %r" % alarms)


def transcript(path, final_text, dialog=False):
    recs = [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z",
         "message": {"role": "user", "content": "please fix the widget"}},
    ]
    if dialog:
        recs.append({"type": "assistant", "timestamp": "2026-01-01T00:01:00Z",
                     "message": {"role": "assistant", "content": [
                         {"type": "tool_use", "name": "AskUserQuestion", "input": {"questions": []}}]}})
    recs.append({"type": "assistant", "timestamp": "2026-01-01T00:02:00Z",
                 "message": {"role": "assistant", "content": [{"type": "text", "text": final_text}]}})
    with open(path, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


class GateQuestionTests(SisiCase):
    def setUp(self):
        super().setUp()
        self.git_init()
        self.tp = os.path.join(self.tmp, "t.jsonl")
        os.environ["SISI_TOOL"] = "claude-code"

    def payload(self, **kw):
        p = {"session_id": "qsess", "cwd": self.proj, "transcript_path": self.tp}
        p.update(kw)
        return p

    def test_asking_in_prose_sends_back_once(self):
        transcript(self.tp, "Fixed and verified. Should I also update the docs?")
        action, msg = gate.decide(self.payload())
        self.assertEqual(action, "block", msg)
        self.assertIn("dialog", msg.lower())
        action2, _ = gate.decide(self.payload())
        self.assertEqual(action2, "allow", "second stop on the same message must not trap the session")

    def test_dialog_used_in_turn_is_exempt(self):
        transcript(self.tp, "Fixed and verified. Should I also update the docs?", dialog=True)
        action, _ = gate.decide(self.payload())
        self.assertEqual(action, "allow")

    def test_plain_finish_is_allowed(self):
        transcript(self.tp, "Fixed and verified. All checks pass.")
        action, _ = gate.decide(self.payload())
        self.assertEqual(action, "allow")

    def test_subagent_is_exempt(self):
        transcript(self.tp, "Fixed and verified. Should I also update the docs?")
        action, _ = gate.decide(self.payload(agent_id="agent-1"))
        self.assertEqual(action, "allow")

    def test_tool_without_dialog_is_exempt(self):
        os.environ["SISI_TOOL"] = "cursor"
        transcript(self.tp, "Fixed and verified. Should I also update the docs?")
        action, _ = gate.decide(self.payload())
        self.assertEqual(action, "allow")


if __name__ == "__main__":
    unittest.main()
