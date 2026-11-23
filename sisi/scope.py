"""Scope is earned (see learning.earned), and `sisi learn`: the one write path for owner statements.

Project identity helpers stay here for handover and friends. The old claim-based tiers
(core/user/project checked only for naming) are gone: a learning is in force in its origin
project at once and elsewhere only with provenance from at least two units in at least two
projects, or as an owner statement.
"""
import os, sys

from . import learning as L


def project_id(cwd):
    return L.project_key(cwd)


def project_label(pid):
    return os.path.basename(str(pid).rstrip("/")) if pid else "(unknown project)"


def visible_in(rec, cwd):
    return L.in_scope(rec, cwd)


def cmd_learn(argv):
    """sisi learn [--scope user|project] TEXT — record an owner statement, live at once."""
    scope = "user"
    text = []
    it = iter(argv)
    for a in it:
        if a == "--scope":
            scope = next(it, "user")
        elif a.startswith("--scope="):
            scope = a.split("=", 1)[1]
        else:
            text.append(a)
    if scope not in L.SCOPES:
        print("sisi learn: --scope must be one of %s" % "|".join(L.SCOPES), file=sys.stderr)
        return 2
    statement = " ".join(text).strip()
    if len(statement) < 8:
        print("usage: sisi learn [--scope user|project] \"<what you want>\"", file=sys.stderr)
        return 2
    rec = L.new_record(statement, "owner statement", "value",
                       "promote" if scope != "project" else "record",
                       os.getcwd(), L.unit_id(), change=statement, mechanism="knowledge",
                       scope=scope, expect="the agent acts on this statement",
                       owner_statement=True, entered_via="learn")
    print("recorded owner statement %s (printed by `sisi oracle`)" % rec["id"])
    return 0
