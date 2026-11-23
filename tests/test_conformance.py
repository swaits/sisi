"""docs/spec/conformance.json judges every requirement in docs/spec/requirements.json
exactly once, in order, with an allowed status, existing evidence for met and partial
entries, a gap for everything not met, and a non-empty how. The same validation is
runnable as a summary: python3 tests/test_conformance.py --summary."""
import collections
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "docs", "spec", "requirements.json")
CONFORMANCE = os.path.join(ROOT, "docs", "spec", "conformance.json")
BEFORE = os.path.join(ROOT, "docs", "reconciliation", "conformance-before.json")

STATUSES = {"met", "partial", "missing", "not-applicable"}


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_requirements():
    return load_json(REQUIREMENTS)


def load_conformance():
    return load_json(CONFORMANCE)


def top_section(req):
    return req["section"].split(".")[0]


def validate_entries(entries, reqs):
    """Return a list of problems; an empty list means the table conforms."""
    problems = []
    if not isinstance(entries, list):
        return ["conformance entries are not a list"]
    want = [r["id"] for r in reqs]
    got = [e.get("id") for e in entries if isinstance(e, dict)]
    if got != want:
        problems.append("ids must appear exactly once, in requirements.json order")
        missing = [i for i in want if i not in got]
        extra = [i for i in got if i not in want]
        if missing:
            problems.append("missing ids: " + ", ".join(missing))
        if extra:
            problems.append("unknown ids: " + ", ".join(extra))
        if len(got) != len(set(got)):
            problems.append("duplicate ids present")
    for e in entries:
        if not isinstance(e, dict):
            problems.append("entry is not an object: %r" % (e,))
            continue
        rid = e.get("id", "<no id>")
        if e.get("status") not in STATUSES:
            problems.append("%s: status %r not in allowed set" % (rid, e.get("status")))
        if not (e.get("how") or "").strip():
            problems.append("%s: how is empty" % rid)
        if e.get("status") in ("met", "partial"):
            evidence = e.get("evidence") or ""
            path = evidence.split(":")[0]
            if not path or not os.path.exists(os.path.join(ROOT, path)):
                problems.append("%s: evidence path does not exist: %r" % (rid, evidence))
        if e.get("status") != "met" and not (e.get("gap") or "").strip():
            problems.append("%s: gap is empty for status %r" % (rid, e.get("status")))
    return problems


def summary_counts(entries, reqs):
    overall = collections.Counter(e["status"] for e in entries)
    by_section = collections.OrderedDict()
    section_of = {r["id"]: top_section(r) for r in reqs}
    for e in entries:
        by_section.setdefault(section_of[e["id"]], collections.Counter())[e["status"]] += 1
    return overall, by_section


def print_summary(entries=None, reqs=None, out=print):
    entries = load_conformance() if entries is None else entries
    reqs = load_requirements() if reqs is None else reqs
    overall, by_section = summary_counts(entries, reqs)
    total = sum(overall.values())
    out("overall (%d): %s" % (total, " ".join(
        "%s=%d" % (s, overall.get(s, 0))
        for s in ("met", "partial", "missing", "not-applicable"))))
    for section, counts in by_section.items():
        out("section %s (%d): %s" % (section, sum(counts.values()), " ".join(
            "%s=%d" % (s, counts.get(s, 0))
            for s in ("met", "partial", "missing", "not-applicable"))))


class ConformanceFormTests(unittest.TestCase):
    def test_conformance_covers_every_requirement_once_in_order(self):
        self.assertEqual(validate_entries(load_conformance(), load_requirements()), [])

    def test_removing_an_id_fails_validation(self):
        entries = load_conformance()
        reqs = load_requirements()
        broken = [e for e in entries if e["id"] != reqs[10]["id"]]
        problems = validate_entries(broken, reqs)
        self.assertTrue(problems, "validation must fail when an id is removed")
        self.assertTrue(any(reqs[10]["id"] in p for p in problems), problems)

    def test_before_copy_matches_and_names_its_commit(self):
        before = load_json(BEFORE)
        self.assertEqual(before["entries"], load_conformance())
        self.assertEqual(before["date"], "2026-11-23")
        self.assertRegex(before["commit"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    if "--summary" in sys.argv[1:]:
        print_summary()
    else:
        unittest.main()
