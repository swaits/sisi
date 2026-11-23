"""Scope is earned (see learning.earned_scope), and `sisi learn`: the one write path for owner statements.

Project identity helpers stay here for handover and friends. A learning is in force in its
origin project at once and elsewhere only with provenance from at least two units in at least
two projects, or as an owner statement made at user (or organization) scope: a project-scoped
statement is delivered only in its project.
"""
import os, sys

from . import learning as L


def project_id(cwd):
    return L.project_key(cwd)


def project_label(pid):
    return os.path.basename(str(pid).rstrip("/")) if pid else "(unknown project)"


USAGE = ("usage: sisi learn [--scope user|project] \"<what you want>\"\n"
         "       sisi learn --withdraw ID --reason \"<why it was recorded by mistake>\"")


def cmd_learn(argv):
    """sisi learn [--scope user|project] TEXT — record an owner statement, live at once.
    sisi learn --withdraw ID --reason WHY — withdraw one recorded by mistake (kept in history)."""
    from . import lifecycle
    lifecycle.migrate_learnings()  # old statements and lessons join the store before a new one is added
    scope, withdraw, reason = "user", None, None
    text = []
    it = iter(argv)
    for a in it:
        if a == "--scope":
            scope = next(it, "user")
        elif a.startswith("--scope="):
            scope = a.split("=", 1)[1]
        elif a == "--withdraw":
            withdraw = next(it, None)
        elif a == "--reason":
            reason = next(it, None)
        else:
            text.append(a)
    if withdraw:
        if not (reason or "").strip():
            print("sisi learn: --withdraw needs --reason \"<why>\"", file=sys.stderr)
            return 2
        try:
            rec = L.withdraw(withdraw, reason.strip())
        except L.LearningError as e:
            print("sisi learn: %s" % e, file=sys.stderr)
            return 2
        print("withdrew owner statement %s: kept in history, never delivered again" % rec["id"])
        return 0
    if scope not in L.SCOPES:
        print("sisi learn: --scope must be one of %s" % "|".join(L.SCOPES), file=sys.stderr)
        return 2
    statement = " ".join(text).strip()
    if len(statement) < 8:
        print(USAGE, file=sys.stderr)
        return 2
    origin = L.statement_origin(statement)
    rec = L.new_record(statement, "owner statement", "value",
                       "promote" if scope != "project" else "record",
                       os.getcwd(), L.unit_id(), change=statement, mechanism="knowledge",
                       scope=scope, expect="the agent acts on this statement",
                       owner_statement=True, entered_via="learn", origin=origin)
    print("recorded owner statement %s (%s; printed by `sisi oracle`; withdraw a mistake with "
          "`sisi learn --withdraw %s --reason ...`)" % (rec["id"], origin, rec["id"]))
    return 0
