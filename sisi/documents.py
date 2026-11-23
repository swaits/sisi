"""Rulebook structure and budget checks. The per-lesson trace regime is gone.

Kept: what a cycle needs to prove about rule text — every rule keeps an id and a Why,
and the rendered rulebook stays inside its line and character budgets.
"""
from . import overlay


class DocumentError(Exception):
    pass


def check_rule_text(text, rid=None):
    """Parse and check one rule; returns the parsed rule or raises DocumentError."""
    try:
        r = overlay.parse_rule_file(text, rid)
    except Exception as e:
        raise DocumentError("rule text does not parse: %s" % e)
    body = r.get("body") or r.get("text") or ""
    if "Why" not in body and "why" not in body.split(":", 1)[0].lower():
        raise DocumentError("rule %r has no Why paragraph" % r.get("id"))
    return r


def traces_for_lesson(lesson_id):
    return []  # the per-lesson trace regime is retired; provenance lives on the learning record


def trace_lines(kind, entry_id):
    return []


def check_budgets(rendered=None):
    """(ok, message) for the rendered rulebook against the overlay budgets."""
    rendered = overlay.render() if rendered is None else rendered
    s = overlay.size(rendered)
    if s["lines"] > overlay.MAX_LINES or s["chars"] > overlay.MAX_CHARS:
        return False, ("rulebook over budget: %d lines (max %d), %d chars (max %d)"
                       % (s["lines"], overlay.MAX_LINES, s["chars"], overlay.MAX_CHARS))
    return True, "%d lines, %d chars, inside budget" % (s["lines"], s["chars"])
