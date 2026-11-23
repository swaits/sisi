"""SPEC.md is pinned by hash, and every normative statement in it is extracted verbatim into
docs/spec/requirements.json: the extraction is checked for well-formedness, for verbatim
occurrence in the specification, and for completeness against every keyword sentence."""
import hashlib, json, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "SPEC.md")
SUMS = os.path.join(ROOT, "docs", "spec", "SHA256SUMS")
REQUIREMENTS = os.path.join(ROOT, "docs", "spec", "requirements.json")

LEVELS = {"MUST", "MUST NOT", "SHOULD", "SHOULD NOT", "MAY", "DEFINITION"}
ID_RE = re.compile(r"^R-(0|[0-9]+(\.[0-9]+)?|[A-D])-[0-9]+$")
KEYWORD_RE = re.compile(r"\b(MUST NOT|MUST|SHOULD NOT|SHOULD|MAY)\b")
LIST_MARKER_RE = re.compile(r"^\s*(?:-\s+|\d+\.\s+)")


def strip_markdown(line):
    line = LIST_MARKER_RE.sub("", line)
    line = line.replace("**", "").replace("*", "")
    line = re.sub(r"\\(.)", r"\1", line)
    return re.sub(r"\s+", " ", line).strip()


def normalised_spec():
    with open(SPEC, encoding="utf-8") as fh:
        lines = [strip_markdown(line) for line in fh]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def split_sentences(text):
    """Split on sentence-final punctuation; a '.' between digits (decimals, section
    numbers, p50/p95-style tokens have none) is not a boundary, and a closing quote
    after the punctuation stays with its sentence."""
    protected = re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + "\x01" + m.group(2), text)
    parts, start, i = [], 0, 0
    while i < len(protected):
        if protected[i] in ".!?":
            j = i + 1
            while j < len(protected) and protected[j] in "”\"’')":
                j += 1
            if j < len(protected) and protected[j] == " ":
                k = j
                while k < len(protected) and protected[k] == " ":
                    k += 1
                if k < len(protected) and (protected[k].isupper() or protected[k].isdigit()
                                           or protected[k] in "“\"("):
                    parts.append(protected[start:j])
                    start, i = k, k
                    continue
        i += 1
    parts.append(protected[start:])
    return [p.replace("\x01", ".").strip() for p in parts if p.strip()]


def load_requirements():
    with open(REQUIREMENTS, encoding="utf-8") as fh:
        return json.load(fh)


class PinnedSourceTests(unittest.TestCase):
    def test_spec_files_match_sha256sums(self):
        expected = {}
        with open(SUMS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    digest, name = line.split(None, 1)
                    expected[name.strip()] = digest
        for name in ("SPEC.md", "docs/spec/engineering_organization_spec.docx"):
            self.assertIn(name, expected)
            with open(os.path.join(ROOT, name), "rb") as fh:
                actual = hashlib.sha256(fh.read()).hexdigest()
            self.assertEqual(actual, expected[name], name)


class RequirementsFormTests(unittest.TestCase):
    def test_requirements_are_well_formed(self):
        reqs = load_requirements()
        self.assertIsInstance(reqs, list)
        ids = [r["id"] for r in reqs]
        self.assertEqual(len(ids), len(set(ids)), "duplicate requirement ids")
        counters = {}
        for r in reqs:
            self.assertRegex(r["id"], ID_RE, r["id"])
            self.assertIn(r["level"], LEVELS, r["id"])
            self.assertTrue(r["section"], r["id"])
            self.assertTrue(r["title"], r["id"])
            self.assertTrue(r["text"], r["id"])
            counters[r["section"]] = counters.get(r["section"], 0) + 1
            self.assertEqual(r["id"], "R-%s-%d" % (r["section"], counters[r["section"]]),
                             "ids must be numbered consecutively from 1 within each section")

    def test_requirements_meet_sanity_floor(self):
        reqs = load_requirements()
        self.assertGreaterEqual(len(reqs), 150)
        top = {r["section"].split(".")[0] for r in reqs}
        for n in range(1, 21):
            self.assertIn(str(n), top, "no requirement in section %d" % n)
        self.assertIn("D", top, "no requirement in appendix D")


class VerbatimTests(unittest.TestCase):
    def test_every_text_and_lead_occurs_verbatim_in_spec(self):
        spec = normalised_spec()
        for r in load_requirements():
            self.assertIn(r["text"], spec, r["id"])
            if "lead" in r:
                self.assertIn(r["lead"], spec, r["id"])


class CompletenessTests(unittest.TestCase):
    def test_every_keyword_sentence_is_covered(self):
        reqs = load_requirements()
        covered = set()
        for r in reqs:
            covered.add(r["text"])
            if "lead" in r:
                covered.add(r["lead"])
        missing = []
        with open(SPEC, encoding="utf-8") as fh:
            for lineno, raw in enumerate(fh, 1):
                line = strip_markdown(raw)
                if line.startswith("The words MUST, MUST NOT"):
                    continue  # the definitions paragraph, not a requirement
                if not KEYWORD_RE.search(line):
                    continue
                for sentence in split_sentences(line):
                    if KEYWORD_RE.search(sentence) and sentence not in covered:
                        missing.append("%d: %s" % (lineno, sentence))
        self.assertEqual(missing, [], "keyword sentences not in requirements.json:\n"
                         + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()
