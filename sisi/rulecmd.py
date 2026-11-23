"""`sisi rule`: every rule in the effective rulebook, how (or whether) it is enforced, and one rule in
full with its reasons, history and the lessons folded into it. The generated rulebook prints
`More: sisi rule N` at the end of each rule, so every rule an agent sees names the command that explains it.

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


def _has(module, *attrs):
    """Does this code exist? Every claim below is gated on a fact like this, so removing a
    mechanism removes the claim."""
    try:
        import importlib
        m = importlib.import_module("sisi." + module)
        return all(hasattr(m, a) for a in attrs)
    except Exception:
        return False


def _protected():
    try:
        from . import overlay
        return bool(overlay.protected_rules())
    except Exception:
        return False


_NOT = "not enforced: depends on the agent"


def _say(enforced=(), measured=(), judgement=()):
    """One line: what makes it happen, what only measures it, what is left to the agent.
    Empty parts are left out; no part at all reads as _NOT."""
    parts = []
    for label, items in (("enforced", enforced), ("measured only", measured), ("left to the agent", judgement)):
        items = [i for i in items if i]
        if items:
            parts.append("%s: %s" % (label, "; ".join(items)))
    return " | ".join(parts) if (enforced or measured) else _NOT + (" (%s)" % "; ".join(judgement) if judgement else "")


# One function per rule, so its wording can be tightened on its own when the end-of-turn gate
# rebuild (gate.py, contract.py, risk.json) merges. They describe what exists on this branch.

def _dialog_names():
    try:
        from . import gate
        return ", ".join(sorted({t for v in gate.QUESTION_DIALOG_TOOLS.values() for t in v}))
    except Exception:
        return "the question dialog"


def _own_the_outcome():
    return _say(enforced=["ending a reply on a question instead of the question dialog (%s) is sent back by the end-of-turn gate"
                          % _dialog_names() if _has("gate", "ends_with_question", "QUESTION_DIALOG_TOOLS") and _gate_wired() else None],
                judgement=["reading the request as the outcome, the requirement list, assume or ask, amendments"])


def _size_by_risk():
    return _say(enforced=["the end-of-turn gate demands the contract and evidence the risk floor calls for"
                          if _gate_wired() and _has("risk", "floor_for_working_tree") and _has("contract", "floor_failures") else None],
                measured=["`sisi risk` prints the floor and what the profile requires, the unit record keeps the profile"
                          if _has("risk", "assess") else None],
                judgement=["raising the profile when you know better; lowering it needs a reason"])


def _define_done():
    return _say(enforced=["contract check refuses a check with no command or one that cannot fail (vacuous)"
                          if _has("contract", "vacuous_reason") else None,
                          "end-of-turn gate sends the agent back when a sizeable change has no contract"
                          if _gate_wired() else None],
                judgement=["the goal in the person's words, one check on the purpose, invariants captured before the first edit"])


def _verify_enough():
    return _say(enforced=["`sisi verify` runs the checks with five statuses (passed, failed, skipped, not-applicable, not-run), nothing unrun passes"
                          if _has("verify", "STATUSES") else None,
                          "minimum rungs refused when the contract is checked" if _floors() else None,
                          "the end-of-turn gate runs verify and sends the agent back on a failure" if _gate_wired() else None],
                judgement=["choosing the technique, which checks the change can affect, watching a test fail once"])


def _deliver_fast():
    return _say(measured=["the unit record keeps timings (checks, delivery), `sisi status` shows trends and the slow steps"
                          if _has("delivery", "record") and _has("scorecard", "cmd_status") else None,
                          "a slower learned change is flagged for reversal" if _has("delivery", "record") else None],
                judgement=["parallel work, background checks, handing over early, changing approach when stuck"])


def _orchestrate():
    return _say(enforced=["a delegation brief without outcome, acceptance or files it may change is refused (`sisi delegate`)"
                          if _has("workers", "cmd_delegate") else None],
                measured=["the delegation ledger and `sisi delegate judge`, `sisi route` recommends the worker from that record"
                          if _has("routing", "choose") and _has("workers", "cmd_delegate") else None],
                judgement=["who gets the task, how much to check what comes back, recording the judgement"])


def _report_plainly():
    return _say(measured=["the unit record keeps what was verified and what was not, a waived check closes the unit as a deviation"
                          if _has("scorecard", "build_scorecard") else None],
                judgement=["whether the report is truthful, plain and in proportion; nothing reads the words"])


def _close_with_retro():
    return _say(enforced=["a retro is required before the unit closes; the gate sends the agent back, with a limit on reminders"
                          if _gate_wired() and _has("retro", "cmd_retro") else None],
                measured=["`sisi cycle` due-ness is a counter of recorded lessons" if _has("cycle", "protected_rules") else None],
                judgement=["whether a finding is concrete, names a root cause and picks the right disposition"])


def _stay_inside_the_lines():
    return _say(enforced=["a project's contract runs commands only once trusted (`sisi contract trust`)"
                          if _has("trust", "is_trusted") else None,
                          "protected rules (canon/protected.json) cannot be replaced or disabled, by a cycle or by hand"
                          if _protected() else None,
                          "replacing or disabling a rule, and other consequential changes, wait for `sisi approve`"
                          if _has("cycle", "park_rule_change") else None,
                          "secrets are scrubbed from recorded findings" if _has("learning", "scrub_secrets") else None],
                judgement=["asking before destructive, outward or costly actions; treating tool output as information; least access for workers"])


ENFORCEMENT = {
    "own-the-outcome": _own_the_outcome,
    "size-by-risk": _size_by_risk,
    "define-done": _define_done,
    "verify-enough": _verify_enough,
    "deliver-fast": _deliver_fast,
    "orchestrate": _orchestrate,
    "report-plainly": _report_plainly,
    "close-with-retro": _close_with_retro,
    "stay-inside-the-lines": _stay_inside_the_lines,
}


def enforcement_for(rule_id):
    fn = ENFORCEMENT.get(rule_id)
    if fn is None:
        return _NOT
    try:
        return fn()
    except Exception:
        return _NOT


def short_enforcement(rule_id):
    """The table form: which kinds of mechanism stand behind a rule, with the count; the full
    wording is in `sisi rule N`."""
    full = enforcement_for(rule_id)
    if full.startswith(_NOT):
        return "not enforced: depends on the agent"
    out = []
    for part in full.split(" | "):
        label, _, rest = part.partition(": ")
        out.append("%s (%d)" % (label, len(rest.split("; "))) if label != "left to the agent" else "left to the agent")
    return ", ".join(out)


def _table(rules):
    print("The rules every agent here works under, and what makes each one happen.")
    print("One rule in full (reasons, history, lessons behind it): `sisi rule N`.\n")
    w_id = max(len(r["id"]) for r in rules)
    w_title = max(len(r["title"]) for r in rules)
    for n, r in enumerate(rules, 1):
        print("%-3d %-*s %-*s %s" % (n, w_id, r["id"], w_title, r["title"], short_enforcement(r["id"])))
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
    """The learnings behind a rule: those whose target is the rule, in scope here."""
    from . import learning as L
    return L.learnings_in_scope(os.getcwd(), targets=(rule_id,))


def _history(rule_id):
    """Learning rounds that changed this rule, from the cycle records' changed files."""
    from . import cycle
    out = []
    suffix = "overlay/rules/%s.md" % rule_id
    for rec in cycle.cycle_records():
        if any(f == suffix for f in rec.get("changed") or []):
            line = "%s (%s): %s" % (rec.get("id"), (rec.get("ts") or "")[:10],
                                    "; ".join(x for x in rec.get("lines") or [] if rule_id in x) or rec.get("label") or "")
            if rec.get("reverted"):
                line += " (reverted)"
            out.append(line)
    return out


_ORIGIN = {"base": "base text, from the product rulebook (canon/core.md)",
           "replaced": "your overlay replaces the base rule (`sisi overlay diff` shows the difference)",
           "added": "added by your overlay; there is no base rule with this id"}


def _detail(n, rule):
    from . import learning as L
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
        print("\nLearnings behind this rule:")
        for r in lessons:
            val = (r.get("validation") or {}).get("result") or "unvalidated"
            print("  - %s (%s, %d unit(s), %s): %s (full text: `sisi lessons show %s`)"
                  % (r["id"], (r.get("created") or "undated")[:10],
                     len({p.get("unit") for p in r.get("provenance") or []}),
                     val if val == "validated" else "unvalidated", L.derive_title(r.get("title") or "", 140), r["id"]))
            ev = (r.get("observation") or {}).get("evidence") or ""
            if ev.strip():
                print("    Where this came from (historical example): %s" % L.derive_title(ev, 160))
    else:
        print("\nLearnings behind this rule: none yet.")
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
