"""Checks that keep the published repository honest: the README names only real commands, and no file carries
a home path or a personal email address."""
import os, re, subprocess, sys, unittest

from support import REPO, SisiCase


def _tracked_or_untracked_files():
    """Every file that would be published: tracked files plus untracked ones that .gitignore does not hide.
    Falls back to a directory walk when git is unavailable."""
    try:
        r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=REPO,
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return [f for f in r.stdout.splitlines() if os.path.isfile(os.path.join(REPO, f))]
    except (OSError, subprocess.SubprocessError):
        pass
    out = []
    for dp, dns, fns in os.walk(REPO):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__")]
        out += [os.path.relpath(os.path.join(dp, n), REPO) for n in fns if not n.endswith(".pyc")]
    return out


def _text(rel):
    try:
        with open(os.path.join(REPO, rel), "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\0" in data:
        return None
    return data.decode("utf-8", "replace")


# Paths under /home/ or /Users/ that are placeholders in tests and examples, not real people.
_ALLOWED_HOME_USERS = {"alice", "bob", "user", "you", "name", "username", "example", "me"}
HOME_RE = re.compile(r"(?<![\w.])/(?:home|Users)/([A-Za-z0-9_.-]+)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

# Values that change under the text and make it go stale: a release number, a count of things in the
# library or the tool list, a year, or words tied to when the sentence was written. A reader who needs
# such a fact is pointed at the command or file that gives the live answer (`sisi --version`,
# `sisi status`, `sisi doctor`, `sisi verifiers`, CHANGELOG.md) instead. Two-part versions (the
# minimum Python) and rung numbers do not match these patterns.
THREE_PART_VERSION_RE = re.compile(r"(?<![\w.])v?\d+\.\d+\.\d+\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
COUNT_RE = re.compile(r"(?<![\w.-])\d[\d,]*\s+(?:[A-Za-z-]+\s+)?"
                      r"(?:techniques|verifiers|recipes|tests|lessons|tools|harnesses)\b", re.I)
STALE_WORDS_RE = re.compile(r"\b(?:currently|today|as of)\b", re.I)
# A tool version quoted as evidence says what a fact was checked on, so it stays: for example a line
# in docs/harnesses.md naming the OpenCode version a limit was checked against.
VERSION_EVIDENCE_RE = re.compile(r"\b(?:verified on|checked against|on\s+[A-Z][\w-]*\s+v\d+\.\d+\.\d+)\b", re.I)
README_WORD_CEILING = 1790  # about a tenth above the README when set; raise it deliberately


def _stale_value_findings(text, rel, allow_version_evidence=False):
    findings = []
    for lineno, line in enumerate((text or "").splitlines(), 1):
        evidence = allow_version_evidence and VERSION_EVIDENCE_RE.search(line)
        for name, pattern in (("three-part version", THREE_PART_VERSION_RE), ("year", YEAR_RE),
                              ("count", COUNT_RE), ("stale word", STALE_WORDS_RE)):
            if name == "three-part version" and evidence:
                continue
            for m in pattern.finditer(line):
                findings.append("%s:%d: %s %r" % (rel, lineno, name, m.group(0)))
    return findings


class PublishableTree(unittest.TestCase):
    def test_no_home_paths(self):
        bad = []
        for rel in _tracked_or_untracked_files():
            text = _text(rel)
            for m in HOME_RE.finditer(text or ""):
                if m.group(1).rstrip(".-").lower() not in _ALLOWED_HOME_USERS:
                    bad.append("%s: %s" % (rel, m.group(0)))
        self.assertEqual(bad, [], "home paths in files that would be published")

    def test_no_email_addresses_except_noreply_and_examples(self):
        bad = []
        for rel in _tracked_or_untracked_files():
            for m in EMAIL_RE.finditer(_text(rel) or ""):
                addr = m.group(0)
                local, _, domain = addr.rpartition("@")
                if "noreply" in addr.lower() or domain.lower() in ("example.com", "example.org", "example.net", "b.co"):
                    continue
                # decorators and npm scopes such as @scope/pkg.js are not addresses: they have no local part
                bad.append("%s: %s" % (rel, addr))
        self.assertEqual(bad, [], "email addresses in files that would be published")

    def test_the_scan_can_fail(self):
        self.assertTrue(HOME_RE.search("see /home/alice/x"))
        self.assertIsNone(HOME_RE.search("see /homepage/x"))
        self.assertTrue(EMAIL_RE.search("write to a.person" + "@corp.example"))

    def test_required_project_files_exist(self):
        for f in ("LICENSE", "README.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md", "VERSION", ".editorconfig",
                  ".github/workflows/ci.yml", "docs/README.md", "docs/design.md"):
            self.assertTrue(os.path.isfile(os.path.join(REPO, f)), f)
        self.assertFalse(os.path.exists(os.path.join(REPO, "docs", "superpowers")))


NOT_BUILT = {"build", "inbox"}  # designed in docs/design.md, named in the README as not built


class ReadmeIsHonest(SisiCase):
    def test_every_subcommand_in_the_readme_exists(self):
        text = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
        help_text = self.sisi("help").stdout
        from sisi import learn_cli
        import argparse
        ap = argparse.ArgumentParser()
        sub = ap.add_subparsers()
        learn_cli.register(sub)
        hidden = set(sub.choices)  # data-layer commands that are real but not listed in `sisi help`
        named = set(re.findall(r"`sisi ([a-z][a-z-]*)", text)) | set(re.findall(r"^ {4}(?:\$ )?sisi ([a-z][a-z-]*)", text, re.M))
        self.assertTrue(named, "the README names no sisi commands")
        for cmd in sorted(named - NOT_BUILT):
            self.assertTrue(re.search(r"\bsisi [^\n]*\b%s\b" % re.escape(cmd), help_text) or cmd in hidden, cmd)
        # The README may name commands only to say they are not built. If one gets built, the README must change.
        for cmd in NOT_BUILT:
            self.assertEqual(self.sisi(cmd).returncode, 64, cmd + " now exists: update the README status section")

    def test_readme_sub_subcommands_are_in_help(self):
        text = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
        help_text = self.sisi("help").stdout
        for m in set(re.findall(r"`sisi (contract|verifiers|canon|overlay|dev) ([a-z-]+)", text)):
            self.assertIn(m[1], help_text, " ".join(m))

    def test_python_version_claim_matches_ci_and_code(self):
        text = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
        ci = open(os.path.join(REPO, ".github", "workflows", "ci.yml"), encoding="utf-8").read()
        m = re.search(r"Python (3\.\d+) or newer", text)
        self.assertTrue(m, "README must state the minimum Python version as 'Python 3.x or newer'")
        self.assertIn('"%s"' % m.group(1), ci)

    def test_every_documented_file_link_exists(self):
        for doc in ("README.md", "CONTRIBUTING.md", "SECURITY.md", os.path.join("docs", "README.md")):
            base = os.path.dirname(os.path.join(REPO, doc))
            for target in re.findall(r"\]\(([^)#\s]+)", open(os.path.join(REPO, doc), encoding="utf-8").read()):
                if re.match(r"^[a-z]+:", target):
                    continue
                self.assertTrue(os.path.exists(os.path.join(base, target)), "%s -> %s" % (doc, target))


class NoStaleValues(unittest.TestCase):
    def test_readme_has_no_stale_values(self):
        text = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
        self.assertEqual(_stale_value_findings(text, "README.md"), [],
                         "hardcoded values that will go stale in the README")

    def test_docs_have_no_stale_values(self):
        rels = ["CONTRIBUTING.md", "SECURITY.md"]
        rels += [os.path.join("docs", n) for n in sorted(os.listdir(os.path.join(REPO, "docs")))
                 if n.endswith(".md")]
        findings = []
        for rel in rels:
            findings += _stale_value_findings(_text(rel), rel, allow_version_evidence=True)
        self.assertEqual(findings, [], "hardcoded values that will go stale in the docs")

    def test_readme_word_count_stays_under_ceiling(self):
        words = len(open(os.path.join(REPO, "README.md"), encoding="utf-8").read().split())
        self.assertLessEqual(words, README_WORD_CEILING,
                             "README has %d words, ceiling %d; cut or raise it deliberately"
                             % (words, README_WORD_CEILING))

    def test_the_stale_scan_can_fail(self):
        bad = _stale_value_findings(
            "Version 0.1.0 had 140 verification techniques and 20 recipes in 2026; today it grows.",
            "sample")
        self.assertGreaterEqual(len(bad), 5, bad)
        self.assertTrue(_stale_value_findings("checked on Foo v1.2.3", "sample"))
        allowed = "Python 3.9 or newer; rung 1, rung 2, rung 3, rung 4, rung 5, rung 6."
        self.assertEqual(_stale_value_findings(allowed, "sample"), [])
        evidence = "no delivery could be confirmed on Foo v1.2.3 in headless runs"
        self.assertEqual(_stale_value_findings(evidence, "sample", allow_version_evidence=True), [])


if __name__ == "__main__":
    unittest.main()
