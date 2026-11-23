"""Session start and prompt hooks after the rework (R-17-3, R-12-12, target section 11)."""
import json, os, unittest
from support import *


class TickCleanTests(SisiCase):
    def payload(self, **kw):
        return json.dumps(dict({"session_id": "s1", "cwd": self.proj,
                                "hook_event_name": "SessionStart", "source": "startup"}, **kw))

    def test_clean_home_prints_nothing(self):
        """R-17-3: in a clean home with nothing to act on, session start is silent."""
        self.git_init()
        self.sisi("install")
        r = self.sisi("tick", stdin=self.payload())
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_broken_wiring_still_prints_one_line(self):
        """R-17-2: broken wiring is actionable, so it is the one line printed."""
        os.makedirs(os.path.join(self.home, ".claude"))
        r = self.sisi("tick", stdin=self.payload())
        self.assertIn("sisi doctor", r.stdout)
        self.assertLessEqual(len(r.stdout.strip().splitlines()), 1)

    def test_handover_shown_once_per_session(self):
        """R-12-2: handover items for this project print once per session, not every session."""
        self.git_init()
        self.sisi("install")
        from sisi import handover, scope
        pid = scope.project_id(self.proj)
        handover.add_item({"kind": "learn", "project": pid, "text": "file this fact"})
        r1 = self.sisi("tick", stdin=self.payload())
        self.assertIn("belong to this project", r1.stdout)
        r2 = self.sisi("tick", stdin=self.payload(source="resume"))
        self.assertNotIn("belong to this project", r2.stdout)


class PromptReworkTests(SisiCase):
    def ctx(self, text):
        from sisi import prompt as P
        return P.build_context(text, session="rework")

    def test_typo_fix_is_silent(self):
        """R-17-3: a trivial request gets no injection."""
        self.assertEqual(self.ctx("fix a typo in the README"), "")

    def test_question_is_silent(self):
        """R-17-3, R-12-12: a question naming no work gets no recipe."""
        self.assertEqual(self.ctx("why is the build slow?"), "")

    def test_map_printing_gets_feature_recipe(self):
        """SPEC Appendix B / R-4.1-1: the complex example gets its recipe at prompt time."""
        ctx = self.ctx("add multi-page map printing with selectable paper size")
        self.assertIn("feature", ctx)
        self.assertLessEqual(len(ctx), 2000)

    def test_accent_color_gets_ui_recipe(self):
        """SPEC Appendix A: the presentation example gets a fitting recipe."""
        ctx = self.ctx("change the accent color of one UI component")
        self.assertTrue("web-ui-change" in ctx or "native-gui-change" in ctx, ctx)

    def test_no_handover_notice_in_prompt(self):
        """R-17-3: the per-prompt handover notice is gone."""
        from sisi import handover, scope
        pid = scope.project_id(self.proj)
        handover.add_item({"kind": "learn", "project": pid, "text": "file this fact"})
        for text in ("fix a typo in the README", "why is the build slow?",
                     "add multi-page map printing with selectable paper size"):
            with self.subTest(text=text):
                self.assertNotIn("belong to this project", self.ctx(text))

    def test_no_design_block_anywhere(self):
        """Retired design section: no prompt prints its instruction."""
        for text in ("build a new orchestration system for agents",
                     "design and build a plugin platform for the tool"):
            with self.subTest(text=text):
                self.assertNotIn("design section", self.ctx(text))


if __name__ == "__main__":
    unittest.main()
