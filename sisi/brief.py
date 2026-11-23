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
        "",
        "## Deliverables and report format",
        "[What to send back, and in what shape: a short report, what changed, the check run.]",
        "",
        "## Files you may change",
        "[The files or folders the worker may change; everything else is read-only.]",
        "",
        "## Verification",
        "[The check the worker must run before reporting, and what output to include.]",
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
