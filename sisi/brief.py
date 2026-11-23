"""The delegation contract: what a brief must contain before work is handed to a worker.

Eight parts. Three of them (outcome, acceptance, the files the worker may change) are
required before `sisi delegate` will run a brief at all; `sisi delegate check` reports
every part a brief lacks. A part counts as present only when its heading is there and
the text under it is more than a placeholder.
"""
import re

PARTS = [
    ("outcome", "Outcome and scope", ("outcome", "scope", "goal"), True),
    ("context", "Context and sources of truth", ("context", "source"), False),
    ("constraints", "Constraints and interfaces", ("constraint", "interface"), False),
    ("acceptance", "Acceptance", ("acceptance", "accept"), True),
    ("deliverables", "Deliverables and report format", ("deliverable", "report"), False),
    ("files", "Files you may change", ("files", "may change"), True),
    ("verification", "Verification", ("verification", "verify"), False),
    ("budget", "Budget and escalation", ("budget", "escalat"), False),
]

_REQUIRED = {p[0] for p in PARTS if p[3]}
_PLACEHOLDER = re.compile(r"^[\s\[\]().>-]*(\.\.\.|todo|tbd|fill in|replace me)?[\s\[\]().>-]*$", re.I)


def template():
    lines = [
        "You are a worker. Do this task yourself; do not delegate it further.",
        "",
        "## Outcome and scope",
        "[The outcome wanted, and what is out of scope.]",
        "",
        "## Context and sources of truth",
        "[What the worker needs to know, and which files or documents are authoritative.]",
        "",
        "## Constraints and interfaces",
        "[What must not change: interfaces, formats, behaviour others depend on.]",
        "",
        "## Acceptance",
        "[How the result will be judged: the check that decides accepted or rejected.]",
        "[Every size, speed or brevity requirement is a number with the command that measures it.]",
        "[If the worker writes data for another module to read, name that reader and require one end-to-end test that shows the reader's behaviour changes.]",
        "[If you ask for a classifier, matcher or heuristic and a labelled set, the labels come from a different worker, or a held-out part is written first.]",
        "",
        "## Deliverables and report format",
        "[What to send back, and in what shape: a short report, what changed, the check run.]",
        "[For numbered items: a commit after each, with a one-line \"done / next\" note in the message.]",
        "",
        "## Files you may change",
        "[The files or folders the worker may change; everything else is read-only.]",
        "",
        "## Verification",
        "[The check the worker must run before reporting, and what output to include.]",
        "[For an approval gate, trust check or validation step, list the abuse cases the tests must cover: omit the field that triggers the gate, forge the field that marks trust, make the failing-before step fail for an unrelated reason.]",
        "[New test modules are run about 30 times, with copies in parallel, before the report.]",
        "",
        "## Budget and escalation",
        "[Time or cost budget; when to stop and escalate instead of guessing.]",
        "",
    ]
    return "\n".join(lines)


def _heading_part(line):
    text = line.strip().lower().lstrip("#-*> ").rstrip(":").strip()
    if not text:
        return None
    for key, _title, needles, _req in PARTS:
        if any(n in text for n in needles):
            return key
    return None


def _filled(lines):
    for line in lines:
        text = line.strip()
        if not text:
            continue
        if text.startswith("[") and text.endswith("]"):
            continue
        if _PLACEHOLDER.match(text):
            continue
        return True
    return False


_TITLES = {t.lower() for _k, t, _n, _r in PARTS}


def _is_heading(line):
    stripped = line.strip()
    if stripped.startswith("#") or stripped.endswith(":"):
        return True
    return stripped.lower().lstrip("#-*> ").rstrip(":").strip() in _TITLES


def sections(text):
    """{part key: [content lines]} for every part heading found in the brief."""
    out = {}
    current = None
    for line in (text or "").splitlines():
        part = _heading_part(line) if _is_heading(line) else None
        if part is not None:
            current = part
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append(line)
    return out


def missing_parts(text):
    """Titles of the parts that are absent or still placeholders, in template order."""
    found = sections(text)
    return [title for key, title, _n, _r in PARTS
            if key not in found or not _filled(found[key])]


def missing_required(text):
    """Titles of the parts `sisi delegate` refuses to run without."""
    found = sections(text)
    return [title for key, title, _n, _r in PARTS
            if key in _REQUIRED and (key not in found or not _filled(found[key]))]


# ---------------------------------------------------------------- advice (never blocks)

_VAGUE = re.compile(r"\b(short|fast|small|brief|concise|quick)\b", re.I)
_GATE = re.compile(r"\b(approv\w*|trust\w*|validat\w*|untrusted)\b", re.I)
_ABUSE = re.compile(r"\b(abuse|misuse)\b", re.I)
_TESTS = re.compile(r"\btests?\b", re.I)
_REPEAT = re.compile(r"\brepeat|\b\d+ times\b|in parallel", re.I)
_FOR_OTHERS = re.compile(r"(for|that) (other|another|downstream) modules? (to|will|that)? ?(read|consume|use)|"
                         r"(other|another) modules? (reads?|will read|consumes?)", re.I)
_READER = re.compile(r"\b(read by|reader is|reader:|the reader|consumer is|consumer:)\s+[`\w./]+", re.I)
_HEURISTIC = re.compile(r"\b(classifier|matcher|heuristic)\b", re.I)
_LABELS = re.compile(r"\blabell?ed\b|\blabels\b|ground truth", re.I)
_LABELS_INDEPENDENT = re.compile(r"different worker|another worker|other worker|held[- ]?out|blind", re.I)
_NUMBERED = re.compile(r"^\s*(\d+[.)]|item \d+)\s", re.I | re.M)
_COMMIT_PER_ITEM = re.compile(r"commit (after|per|for) each|done ?/ ?next", re.I)


def _written(text):
    """The lines the brief's author wrote: the template's bracketed guidance does not count."""
    return [ln for ln in (text or "").splitlines()
            if not (ln.strip().startswith("[") and ln.strip().endswith("]"))]


def advice(text):
    """Short pieces of advice about a brief, each with its reason. Advice never blocks a delegation."""
    lines = _written(text)
    body = "\n".join(lines)
    acceptance = sections("\n".join(lines)).get("acceptance", [])
    out = []
    vague = sorted({m.group(1).lower() for ln in acceptance if not re.search(r"\d", ln) for m in _VAGUE.finditer(ln)})
    if vague:
        out.append("Acceptance says %s with no number: state each size, speed or brevity limit as a number "
                   "and the command that measures it." % "/".join(vague))
    if _GATE.search(body) and not _ABUSE.search(body):
        out.append("It mentions approval, trust or validation but lists no abuse cases: name them (omit the "
                   "trigger field, forge the trust mark, fail the before-step for an unrelated reason).")
    if _TESTS.search(body) and not _REPEAT.search(body):
        out.append("It asks for tests but not a repeat run: run new test modules about 30 times, with copies "
                   "in parallel, before reporting (exposes time and order dependence).")
    if _FOR_OTHERS.search(body) and not _READER.search(body):
        out.append("The worker writes data for other modules to read, but no reader is named: name it and ask "
                   "for one end-to-end test showing its behaviour changes.")
    if _HEURISTIC.search(body) and _LABELS.search(body) and not _LABELS_INDEPENDENT.search(body):
        out.append("It asks for a classifier, matcher or heuristic and a labelled set from the same worker: the "
                   "labels should come from a different worker, or a held-out part be written first.")
    if len(_NUMBERED.findall(body)) >= 2 and not _COMMIT_PER_ITEM.search(body):
        out.append("It has numbered items but no commit per item: ask for a commit after each, with a "
                   "\"done / next\" note, so an interruption loses at most one.")
    return out
