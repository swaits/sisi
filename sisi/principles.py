"""Owner statements, printed by `sisi oracle`. One store: learning records with owner_statement.

`sisi learn` writes them and `sisi oracle` prints them. The old parallel stores
(learn.jsonl, oracle.md) are merged by the migration in lifecycle.py.
"""
from . import learning as L


def statements():
    return [{"text": r.get("proposed", {}).get("description") or r.get("title", ""),
             "scope": r.get("proposed", {}).get("scope") or "user",
             "ts": r.get("created", ""), "id": r.get("id")}
            for r in L.owner_statements()]


def plain_of(rec):
    return rec.get("text") or rec.get("proposed", {}).get("description", "")


def oracle_text():
    recs = statements()
    if not recs:
        return "No owner statements recorded. `sisi learn \"<what you want>\"` adds one.\n"
    lines = ["What the owner wants (recorded with `sisi learn`):"]
    for i, r in enumerate(recs, 1):
        lines.append("%d. %s" % (i, r["text"]))
    return "\n".join(lines) + "\n"


def short_lines(limit_chars=1200):
    out, used = [], 0
    for r in statements():
        t = " ".join(r["text"].split())[:180]
        if used + len(t) > limit_chars:
            break
        out.append(t)
        used += len(t)
    return out
