"""The owner's standing principles: `sisi learn` statements in the user tier (plus core
statements until the product carries them, and not-yet-tiered ones meanwhile), live at once.

A statement takes effect the moment it is recorded: `sisi oracle` prints it, request-time
delivery hands it over, and a contract's design section must answer its objections. There is
no quarantine and no holding file. The oracle is a proper document (oracle.md in the personal
folder) whose structure a learning round owns through the whole-document edit in
sisi/documents.py, tracing every statement into the text like any other document; until a
round integrates a statement, `sisi oracle` prints it under its own heading so it is never
parked unread.
"""
import os

from . import paths, store

EMPTY = """# sisi oracle

What the human wants, so a thing is asked once ever. Empty so far: it is filled from
preferences the human stated (`sisi learn`), which take effect at once.
"""


def statements():
    """The standing principles, in the order recorded: user-tier statements (how this owner
    wants work done), plus core statements until the product carries them, plus not-yet-tiered
    statements, which are still delivered while they wait for a tier."""
    from . import scope as _scope
    out = []
    for rec in store.read("learn"):
        text = " ".join(str(rec.get("text") or "").split())
        if text and _scope.tier_of(rec.get("scope")) != "project":
            out.append(dict(rec, text=text))
    return out


def core_statements():
    return [r for r in statements() if r.get("scope") == "core"]


def unscoped_statements():
    """Statements with no tier yet (old two-way `everywhere` included; a round tiers them)."""
    from . import scope as _scope
    return [rec for rec in store.read("learn")
            if (rec.get("text") or "").strip() and _scope.tier_of(rec.get("scope")) == "unscoped-tier"]


def plain_of(rec):
    """The principle in plain words on one line: the stored plain form when a round wrote one,
    else the statement itself, tidied into a sentence."""
    plain = " ".join(str(rec.get("plain") or "").split())
    if plain:
        return plain
    t = " ".join(str(rec.get("text") or "").split()).strip("\"")
    if t and t[-1] not in ".!?":
        t += "."
    return t


def date_of(rec):
    return (rec.get("ts") or "")[:10]


def short_lines(limit_chars=None):
    """One short plain line per principle, for request-time and contract-init delivery."""
    out, total = [], 0
    for rec in statements():
        line = "- " + plain_of(rec)
        if limit_chars is not None and total + len(line) + 1 > limit_chars and out:
            out.append("- ... and more (`sisi oracle` prints them all)")
            break
        out.append(line)
        total += len(line) + 1
    return out


def _principle_block(rec):
    date = date_of(rec)
    return '- %s\n  > "%s"%s' % (plain_of(rec), rec["text"], " (%s)" % date if date else "")


def _oracle_file_text():
    try:
        with open(paths.data_file("oracle.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def oracle_text():
    """The oracle document as agents should read it now: the round-written document when one
    exists, with any not-yet-integrated statements printed after it, never hidden."""
    recs = statements()
    file_text = _oracle_file_text()
    if file_text:
        missing = [r for r in recs if r["text"] not in file_text]
        if not missing:
            return file_text
        return (file_text.rstrip("\n") + "\n\n## Not yet integrated\n\n"
                "Recorded since the last learning round rewrote this document; in force now.\n\n"
                + "\n".join(_principle_block(r) for r in missing) + "\n")
    if not recs:
        return EMPTY
    lines = ["# sisi oracle", "",
             "What the human wants, so a thing is asked once ever. Statements recorded with "
             "`sisi learn` take effect at once; a learning round rewrites this document as a "
             "whole and traces every statement into it.", "",
             "## Standing principles", ""]
    lines += [_principle_block(r) for r in recs]
    return "\n".join(lines) + "\n"


def oracle_path():
    return paths.data_file("oracle.md")
