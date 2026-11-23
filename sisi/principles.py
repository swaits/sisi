"""Owner statements, printed by `sisi oracle`. One store: learning records with owner_statement.

`sisi learn` writes them and `sisi oracle` prints them. Statements that predate the learning
store are brought in by lifecycle.migrate_learnings, which runs here first, so nothing goes silent.
"""
from . import learning as L


def statements():
    """The owner statements in force in the current project: user-scope ones everywhere, a
    project-scoped one only in its own project."""
    import os
    from . import lifecycle
    lifecycle.migrate_learnings()
    here = os.getcwd()
    return [{"text": r.get("proposed", {}).get("description") or r.get("title", ""),
             "scope": r.get("proposed", {}).get("scope") or "user",
             "ts": r.get("created", ""), "id": r.get("id"),
             "origin": r.get("statement_origin") or ""}
            for r in L.owner_statements() if L.in_scope(r, here)]


def oracle_text():
    recs = statements()
    if not recs:
        return ("The oracle is empty: no owner statements recorded. "
                "`sisi learn \"<what you want>\"` adds one.\n")
    lines = ["Standing principles — what the owner wants, in their words "
             "(recorded with `sisi learn`; this is the oracle):"]
    for i, r in enumerate(recs, 1):
        date = " (%s)" % str(r["ts"])[:10] if r.get("ts") else ""
        flag = " [relayed by an agent, not found in a message the owner typed]" if r["origin"] == "relayed by an agent" else ""
        lines.append('%d. "%s"%s%s' % (i, r["text"], date, flag))
    return "\n".join(lines) + "\n"

