"""Owner statements, printed by `sisi oracle`. One store: learning records with owner_statement.

`sisi learn` writes them and `sisi oracle` prints them. The old parallel stores
(learn.jsonl, oracle.md) are merged by the migration in lifecycle.py; until an install
has migrated, statements are still read from learn.jsonl so nothing goes silent.
"""
import json, os

from . import learning as L, paths


def _legacy_statements():
    try:
        from . import store
        rows = store.read("learn")  # also folds any quarantine file in, losslessly
    except Exception:
        rows = []
        try:
            with open(paths.data_file("learn.jsonl"), encoding="utf-8") as f:
                rows = [json.loads(x) for x in f if x.strip()]
        except (OSError, ValueError):
            pass
    return [{"text": r.get("text") or r.get("statement") or "",
             "scope": r.get("scope") or "user", "ts": r.get("ts") or "", "id": None}
            for r in rows if (r.get("text") or r.get("statement"))]


def statements():
    recs = [{"text": r.get("proposed", {}).get("description") or r.get("title", ""),
             "scope": r.get("proposed", {}).get("scope") or "user",
             "ts": r.get("created", ""), "id": r.get("id")}
            for r in L.owner_statements()]
    if recs or os.path.exists(L.learnings_path()):
        return recs
    return _legacy_statements()


def plain_of(rec):
    return rec.get("text") or rec.get("proposed", {}).get("description", "")


def oracle_text():
    recs = statements()
    if not recs:
        legacy = paths.data_file("oracle.md")
        if os.path.exists(legacy):
            try:
                with open(legacy, encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
        return ("The oracle is empty: no owner statements recorded. "
                "`sisi learn \"<what you want>\"` adds one.\n")
    lines = ["Standing principles — what the owner wants, in their words "
             "(recorded with `sisi learn`; this is the oracle):"]
    for i, r in enumerate(recs, 1):
        date = " (%s)" % str(r["ts"])[:10] if r.get("ts") else ""
        lines.append('%d. "%s"%s' % (i, r["text"], date))
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
