"""The product is universal: no file that ships may name this owner, a home path, a price, or a
specific AI model. Host tool names (Claude Code, Codex, OpenCode and the like) are legitimate
where an adapter or its docs need them; model ids and model-family names used as instructions
are not. Every exception is one allowlist line with its reason."""
import os, re, subprocess, unittest

from support import REPO

# One line per exception: (relative path, exact text on the line, reason).
ALLOWLIST = [
    ("README.md", "github.com/swaits/sisi", "the project's own repository URL, needed to install"),
    ("README.md", "Stephen Waits", "legal copyright attribution, matching LICENSE"),
    ("SECURITY.md", "github.com/swaits/sisi", "the project's own repository URL, needed to report privately"),
    ("sisi/gate.py", "Claude-Code-shaped", "host transcript format name, not a model id"),
    ("verifiers/intent/domain-evidence-report.md", "", "worked example with test-data amounts, not a price"),
    ("verifiers/intent/owner-acceptance-runbook.md", "", "worked example with test-data amounts, not a price"),
    ("sisi/workers.py", "", "TEMPORARY: being rewritten by the orchestration worker under this same rule; remove at merge"),
    ("sisi/routing.py", "", "TEMPORARY: being rewritten by the orchestration worker under this same rule; remove at merge"),
]
HOST_IDS = {"claude-code", "gemini-cli"}

OWNER_RES = [
    ("owner handle or name", re.compile(r"swaits", re.I)),
    ("owner given name", re.compile(r"\bStephen\b")),
    ("owner surname", re.compile(r"\bWaits\b")),
]
HOME_RE = re.compile(r"(?<![\w.])/(?:home|Users)/([A-Za-z0-9_.-]+)")
_ALLOWED_HOME_USERS = {"alice", "bob", "user", "you", "name", "username", "example", "me"}
CURRENCY_RE = re.compile(r"[$£€]\s?\d{2,}(?:[.,]\d+)*|[$£€]\s?\d+\.\d{2}")
MODEL_ID_RE = re.compile(r"\b(?:claude|gpt|gemini|llama|mistral|qwen|deepseek|kimi)-[a-z0-9][a-z0-9.-]*\b", re.I)
MODEL_RES = [
    ("model family name", re.compile(r"\b(?:haiku|sonnet|opus|fable)\b", re.I)),
]

SCAN_PREFIXES = ("sisi/", "canon/", "done/", "verifiers/", "bin/")
SCAN_FILES = {"config.default.json", "README.md", "CONTRIBUTING.md", "SECURITY.md"}
SKIP_DIRS = {"docs/spec/", "docs/reconciliation/"}


def _files():
    try:
        r = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, timeout=30)
        names = r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    if not names:
        names = []
        for dp, dns, fns in os.walk(REPO):
            dns[:] = [d for d in dns if d not in (".git", "__pycache__")]
            names += [os.path.relpath(os.path.join(dp, n), REPO) for n in fns]
    out = []
    for n in names:
        if any(n.startswith(p) for p in SKIP_DIRS):
            continue
        if n.startswith(SCAN_PREFIXES) or n in SCAN_FILES or (n.startswith("docs/") and n.endswith(".md")):
            if os.path.isfile(os.path.join(REPO, n)):
                out.append(n)
    return sorted(out)


def _allowed(rel, line):
    return any(rel == p and (not frag or frag in line) for p, frag, _ in ALLOWLIST)


def findings(rel, text):
    out = []
    whole_file_skip = any(rel == p and not frag for p, frag, _ in ALLOWLIST)
    if whole_file_skip:
        return out
    for i, line in enumerate((text or "").splitlines(), 1):
        if _allowed(rel, line):
            continue
        for name, pat in OWNER_RES:
            if pat.search(line):
                out.append("%s:%d: %s: %s" % (rel, i, name, line.strip()[:90]))
        for m in HOME_RE.finditer(line):
            if m.group(1).rstrip(".-").lower() not in _ALLOWED_HOME_USERS:
                out.append("%s:%d: home path: %s" % (rel, i, line.strip()[:90]))
        if CURRENCY_RE.search(line):
            out.append("%s:%d: currency amount: %s" % (rel, i, line.strip()[:90]))
        for m in MODEL_ID_RE.finditer(line):
            if m.group(0).lower() not in HOST_IDS:
                out.append("%s:%d: model id: %s" % (rel, i, line.strip()[:90]))
        for name, pat in MODEL_RES:
            if pat.search(line):
                out.append("%s:%d: %s: %s" % (rel, i, name, line.strip()[:90]))
    return out


class ProductIsUniversal(unittest.TestCase):
    def test_no_owner_specific_or_perishable_material(self):
        bad = []
        for rel in _files():
            try:
                with open(os.path.join(REPO, rel), encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            if "\0" in text:
                continue
            bad += findings(rel, text)
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_scan_can_fail(self):
        self.assertTrue(findings("x.py", "ask swaits about it"))
        self.assertTrue(findings("x.py", "Stephen said so"))
        self.assertTrue(findings("x.py", "see /home/someone/project"))
        self.assertTrue(findings("x.py", "it costs $12 per run"))
        self.assertTrue(findings("x.py", "use claude-example-1 for this"))
        self.assertTrue(findings("x.py", "send it to the haiku worker"))
        self.assertEqual(findings("x.py", "run it in Claude Code or Codex"), [])
        self.assertEqual(findings("x.py", "see /home/alice/project"), [])
        # an added offender in a scanned file is caught
        self.assertTrue(findings("sisi/example.py", "TODO: ask Stephen to check"))


if __name__ == "__main__":
    unittest.main()
