"""`sisi rule`: every rule in the effective rulebook, how (or whether) it is enforced, and one rule in
full with its reasons, history and the lessons folded into it. The generated rulebook prints
`More: sisi rule N` under each rule, so every rule an agent sees names the command that explains it.

The enforcement wording is derived from code facts (which hooks are wired, whether the gate carries
the question check, whether the floors exist), not from prose: if a mechanism is removed, this
output stops claiming it. A rule with no entry below is reported honestly as depending on the agent.
"""
import os, sys


def _gate_wired():
    try:
        from . import wiring
        return "Stop" in wiring.hook_cmds()
    except Exception:
        return False


def _floors():
    try:
        from . import contract, paths
        return os.path.exists(paths.canon("floors.json")) and callable(contract.floor_failures)
    except Exception:
        return False


def _question_gate():
    try:
        from . import gate
        return bool(gate.QUESTION_DIALOG_TOOLS) and callable(gate.ends_with_question)
    except Exception:
        return False


def _design_gate():
    try:
        from . import design, gate
        return callable(design.validate_design) and callable(gate._design_required)
    except Exception:
        return False


def _delivery_measured():
    try:
        from . import delivery
        return callable(delivery.record)
    except Exception:
        return False


_NOT = "not enforced: depends on the agent"

ENFORCEMENT = {
    "choose-the-approach": lambda: ("end-of-turn check sends a large change back when the contract's "
                                    "design section is missing or fails validation (small edits and "
                                    "subagents exempt)"
                                    if _gate_wired() and _design_gate() else _NOT),
    "know-done": lambda: ("end-of-turn check sends the agent back (no contract on a large change)"
                          if _gate_wired() else _NOT),
    "strongest-check": lambda: ("minimum rungs refused when the contract is checked; the choice of check depends on the agent"
                                if _floors() else _NOT),
    "protect-working": lambda: ("contract invariants are run by the end-of-turn check; writing them depends on the agent"
                                if _gate_wired() else _NOT),
    "feedback-as-amendment": lambda: _NOT,
    "decide-dont-ask": lambda: ("end-of-turn check: ending by asking in reply text instead of the question dialog is sent back"
                                if _question_gate() else _NOT),
    "finish-by-verifying": lambda: ("end-of-turn check runs the checks and sends the agent back on a failure"
                                    if _gate_wired() else _NOT),
    "retro-every-time": lambda: ("retro required before stopping (end-of-turn check)"
                                 if _gate_wired() else _NOT),
    "deliver-quickly": lambda: ("not enforced: measured only (`sisi time`); a slower learned change is flagged for reversal"
                                if _delivery_measured() else _NOT),
}


def enforcement_for(rule_id):
    fn = ENFORCEMENT.get(rule_id)
    if fn is None:
        return _NOT
    try:
        return fn()
    except Exception:
        return _NOT


def _table(rules):
    print("The rules every agent here works under, and what makes each one happen.")
    print("One rule in full (reasons, history, lessons behind it): `sisi rule N`.\n")
    w_id = max(len(r["id"]) for r in rules)
    w_title = max(len(r["title"]) for r in rules)
    for n, r in enumerate(rules, 1):
        print("%-3d %-*s %-*s %s" % (n, w_id, r["id"], w_title, r["title"], enforcement_for(r["id"])))
    return 0


def _why_paragraphs(body):
    out, cur = [], []
    for line in (body or "").split("\n") + [""]:
        if line.strip():
            cur.append(line)
        elif cur:
            para = "\n".join(cur)
            if para.lstrip().startswith("Why:"):
                out.append(para)
            cur = []
    return out


def _folded_lessons(rule_id):
    try:
        from . import retro
        if not os.path.exists(retro.db_path()):
            return []
        con = retro.connect()
        try:
            return [dict(r) for r in con.execute(
                "SELECT * FROM lessons WHERE folded_into=? OR folded_into=? ORDER BY id",
                (rule_id, "rule:" + rule_id))]
        finally:
            con.close()
    except Exception:
        return []


def _history(rule_id):
    """Learning rounds that changed this rule, from the cycle records' changed-files evidence."""
    try:
        from . import cycle
        out = []
        suffix = "rules/%s.md" % rule_id
        for rec in cycle.cycle_records():
            changed = rec.get("changed_files") or {}
            if any(k.endswith(suffix) for k in changed):
                line = "%s (%s): %s" % (rec.get("id"), (rec.get("ts") or "")[:10], rec.get("summary") or "")
                if rec.get("reverted"):
                    line += " (reverted)"
                out.append(line)
        return out
    except Exception:
        return []


_ORIGIN = {"base": "base text, from the product rulebook (canon/core.md)",
           "replaced": "your overlay replaces the base rule (`sisi overlay diff` shows the difference)",
           "added": "added by your overlay; there is no base rule with this id"}


def _detail(n, rule):
    from . import retro
    print("Rule %d: %s {#%s}\n" % (n, rule["title"], rule["id"]))
    print(rule["body"].strip("\n"))
    why = _why_paragraphs(rule["body"])
    if why:
        print("\nWhy, in short:")
        for p in why:
            print("  " + "\n  ".join(p.split("\n")))
    print("\nHow it is enforced: %s." % enforcement_for(rule["id"]).rstrip("."))
    print("Origin: %s." % _ORIGIN.get(rule.get("origin") or "base", rule.get("origin") or "base"))
    hist = _history(rule["id"])
    print("\nHistory: " + ("no learning round has changed this rule." if not hist else ""))
    for h in hist:
        print("  - " + h)
    lessons = _folded_lessons(rule["id"])
    if lessons:
        print("\nLessons folded into this rule:")
        for r in lessons:
            date = (retro._get(r, "last_seen") or retro._get(r, "applied_at") or "")[:10]
            print("  - #%d (%s, seen %d times): %s (full text: `sisi lessons show %d`)"
                  % (r["id"], date or "undated", r["count"] or 0,
                     retro.heading_text(r, 140), r["id"]))
            try:
                from . import documents as _docs
                for _key, _t in _docs.traces_for_lesson(r["id"]):
                    if _t.get("fragment"):
                        print("    carried in %s by: %r" % (_key, _t["fragment"]))
            except Exception:
                pass
            if (r.get("moment") or "").strip():
                print("    Where this came from (historical example): %s"
                      % retro.word_cut(r["moment"], 160))
    else:
        print("\nLessons folded into this rule: none yet.")
    return 0


def main(args):
    from . import overlay
    args = [a for a in args if a not in ("-h", "--help")]
    try:
        _pre, rules = overlay.effective()
    except Exception as e:
        print("sisi rule: %s" % e, file=sys.stderr)
        return 1
    if not args:
        return _table(rules)
    if len(args) != 1:
        print("usage: sisi rule [N|ID]", file=sys.stderr)
        return 1
    want = args[0]
    if want.isdigit():
        n = int(want)
        if 1 <= n <= len(rules):
            return _detail(n, rules[n - 1])
    else:
        for n, r in enumerate(rules, 1):
            if r["id"] == want:
                return _detail(n, r)
    print("sisi rule: no rule %r (see `sisi rule`)" % want, file=sys.stderr)
    return 1
