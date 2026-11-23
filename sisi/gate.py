"""End-of-turn gate (Stop hook): may this agent stop now? JSON on stdin; a send-back is
{"decision":"block","reason":...} on stdout, exit 0. Anything that goes wrong inside sisi allows
(fail open) and is logged to the state dir.

The flow is target.md section 7, and each stop answers these in order:

 1. Did THIS session change anything since its last settled stop? If not, the turn ends silently
    (a paused unit with no new change, a closed unit, another session's edits: all silent).
 2. What does the change need? The floor comes from the paths changed (sisi/risk.py); the contract
    may raise it, and lowers it only with a reason (sisi/assure.py).
 3. Enforce what that profile's row of canon/risk.json requires, and nothing else; run the
    selected fast checks (sisi/verify.py). One send-back lists everything missing at once.
 4. All green and the unit still open: close it if the retro is recorded, otherwise offer the two
    ways on (the retro, or `sisi unit pause`), once. A trivial change is asked nothing.

Send-backs are bounded (`gate.max_blocks`); when they run out the unit is released as `unverified`
and says why. A subagent is never sent back and never asked for a retro: its last message is its
report. Who made which edit is attributed in sisi/attribution.py, so a session is never sent back
for another session's work in the same tree.
"""
import hashlib, json, os, sys, time

from . import assure, attribution, contract as C, gitutil, risk, store, trust, unit as U, verify as V
from .questions import QUESTION_DIALOG_TOOLS, ends_with_question  # noqa: F401  (rulecmd and the tests name them here)

# watch.py asks the gate's shell classifier whether a command may write
_shell_may_write = attribution.shell_may_write

SENTINELS = ("*shell*", "*shell-unmeasured*", "*subagent*")


def _read_payload():
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        d = json.loads(store.read_stdin() or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _session_key(payload, cwd):
    sid = payload.get("session_id")
    return sid if isinstance(sid, str) and sid else "cwd-" + hashlib.sha1(cwd.encode()).hexdigest()[:12]


def _cwd(payload):
    c = payload.get("cwd")
    return c if isinstance(c, str) and os.path.isdir(c) else os.getcwd()


def _new_waiver(project, sess):
    """Latest `sisi contract waive` for this project made during this session and not yet applied."""
    since, seen, best = sess.get("started") or sess.get("first_seen") or "", sess.get("waiver_ns", 0), None
    for w in store.read("waivers"):
        if w.get("project") == project and w.get("ts", "") >= since and w.get("ns", 0) > seen:
            best = w
    return best


# ---------------------------------------------------------------- who changed what

def _absorb_subagents(sess, sid):
    """Edits a subagent reported at its own stop count as this session's edits (hosts that keep the
    subagent's transcript elsewhere are covered this way)."""
    seen = int(sess.get("sub_seen_ns", 0) or 0)
    top = max(seen, 0)
    for r in store.read("subagents"):
        if r.get("session") != sid or int(r.get("ns", 0)) <= seen:
            continue
        top = max(top, int(r["ns"]))
        if not r.get("edited"):
            continue
        sess["attr_gen"] = int(sess.get("attr_gen", 0) or 0) + 1
        since = sess.setdefault("attr_since_pass", [])
        for f in r.get("files") or []:
            if f not in since:
                since.append(f)
        if not r.get("files") and "*subagent*" not in since:
            since.append("*subagent*")
    sess["sub_seen_ns"] = top


def _note_own_paths(sess, attr, top):
    """Record this scan's edited paths (relative to the repository) as edited since the last settled stop."""
    since = sess.setdefault("attr_since_pass", [])
    for f in attr.get("files") or []:
        rel = f
        if os.path.isabs(f) and top:
            try:
                rel = os.path.relpath(f, top)
            except ValueError:
                rel = f
        if rel not in since:
            since.append(rel)
    if attr.get("shell_edits") and not sess.get("attr_measured") and "*shell*" not in since:
        since.append("*shell*")  # a text-classified shell edit: its paths are unknown


def _own_changed(sess, sid, cwd, top, attr):
    """Paths changed since this session's last settled stop that this session made (or may have made).
    Never another session's work: that is what lets two sessions share a tree."""
    changed = None
    try:
        from . import watch
        changed = watch.changed_since_pass(sid, cwd)
    except Exception as e:
        store.log_error("gate-watch-diff", e)
    if changed is None:  # no settled snapshot yet: the tree against the session's start
        base = set((sess.get("baseline") or {}).get("files") or [])
        since = set(sess.get("attr_since_pass") or [])
        try:
            now = gitutil.measure(cwd, sess.get("head"))["files"]
        except Exception:
            now = []
        changed = [f for f in now if f not in base or f in since]
    changed = [f for f in changed if not f.startswith(".sisi" + os.sep) and not f.startswith(".sisi/")]
    since = set(sess.get("attr_since_pass") or [])
    if attr is None or attr["unknown"] or any(s in since for s in SENTINELS):
        return changed
    return [f for f in changed if f in since]


def _claims_unit(sess, contract_path):
    """This session wrote the open contract itself (`sisi contract init`, or an edit of the file)."""
    if not contract_path:
        return False
    rel = C.REL.replace(os.sep, "/")
    mine = [f.replace(os.sep, "/") for f in list(sess.get("attr_files") or []) + list(sess.get("attr_since_pass") or [])]
    return any(f == rel or f.endswith("/" + rel) for f in mine)


def _diff_text(project, base):
    return U._git_diff_text(project, base)


# ---------------------------------------------------------------- the stop

class _Stop:
    """One stop: the session record, and the few ways a stop can end."""

    def __init__(self, sess, sid, cfg, fp, attr):
        self.sess, self.sid, self.cfg, self.fp, self.attr = sess, sid, cfg, fp, attr
        self.maxb = int(cfg["gate"].get("max_blocks", 3))

    def save(self):
        store.save_session(self.sid, self.sess)

    def settle(self, cwd):
        """This stop leaves nothing pending: the next change is measured from here."""
        s = self.sess
        s.update(dirty=False, blocks=0, settled_fp=self.fp, last_fp=self.fp, last_decision="allow", sb_unit=0,
                 attr_since_pass=[])
        try:
            from . import watch
            watch.save_pass_snapshot(self.sid, cwd)
        except Exception as e:
            store.log_error("gate-watch-pass", e)
        self.save()

    def allow(self, cwd, msg=None, settle=True):
        if settle:
            self.settle(cwd)
        else:
            self.sess.update(blocks=0, last_decision="allow")
            self.save()
        return "allow", msg

    def block(self, text, contract_id, project, counts=True):
        s = self.sess
        if counts:
            s["req_blocks"] = int(s.get("req_blocks", 0)) + 1  # send-backs during this request, for the delivery row
            s["blocks"] = int(s.get("blocks", 0)) + 1
            s["sb_unit"] = int(s.get("sb_unit", 0)) + 1
        s.update(last_fp=self.fp, last_decision="block")
        self.save()
        return "block", text.replace("{n}", "%d of %d" % (s.get("blocks", 1), self.maxb))

    def exhausted(self):
        return int(self.sess.get("blocks", 0)) >= self.maxb

    def refresh(self, cwd, path):
        """The contract file is part of the tree's fingerprint: take it again after the gate edited it."""
        self.fp = gitutil.fingerprint(cwd, [path]) if gitutil.root(cwd) and path else self.fp


def _release(stop, cwd, c, path, project, why):
    """The send-backs ran out: the turn ends, the unit is released as unverified and says why."""
    why = [w for w in why if w][:4]
    store.append("results", {"ts": store.now(), "contract": c["id"] if c else None, "project": project,
                             "check": "gate", "item": "gate", "kind": None, "rung": None, "status": "unverified",
                             "reason": "; ".join(why)[:500], "duration_s": 0.0, "tool": store.tool(),
                             "session": stop.sid})
    if c is not None and path:
        try:
            c["unverified"] = {"ts": store.now(), "send_backs": stop.maxb, "why": why}
            C.save(path, c)
            stop.refresh(cwd, path)
        except OSError as e:
            store.log_error("gate-release", e)
    stop.allow(cwd)
    return "allow", ("sisi: result is UNVERIFIED. The gate has sent this work back %d times and it is still not "
                     "verified (%s), so it let the turn end. Report the work as unverified and say what is "
                     "missing." % (stop.maxb, "; ".join(why) or "see the last message"))


def _offer_text(c, profile, anomaly):
    why = ("every check for unit %s passes" % c["id"]) if not anomaly else \
        ("unit %s passes, and it shows something worth a look (%s)" % (c["id"], anomaly))
    return assure.fit([
        "sisi: %s (%s change). Two ways on, then finish:" % (why, profile),
        "- record what you learned: `sisi retro` prints this unit's record; then",
        '  `sisi retro --finding "<what happened, with the evidence>" --cause "<root cause>" '
        '--impact value|correctness|time|cost|attention --disposition record --limits "<where it applies>"`',
        "  records it and closes the unit. (`sisi retro --help` shows `promote` and `drop`.)",
        '- or, if this work now waits on something (a review, a decision, a deploy):',
        '  `sisi unit pause "<what it waits for>"`. The turn ends and nothing more is asked until the tree changes.',
    ])


def _technique_note(c, profile, sess):
    """Once per unit, never blocking: a logic-or-higher change with no check stronger than examples."""
    if c is None or assure.ORDER[profile] < assure.ORDER["logic"] or assure.stronger_technique(c):
        return None
    if sess.get("technique_noted") == c.get("id"):
        return None
    sess["technique_noted"] = c.get("id")
    return ("Note (not a send-back): no check in this contract uses a technique stronger than example tests "
            "(a proof, properties, fuzzing or a comparison with a reference: rung 2 or better). "
            "`sisi verifiers for \"<the claim you need to show>\"` ranks the options.")


def _anomaly(c, project, sess):
    """Why a trivial unit still earns a retro: two send-backs, or a human correction inferred from the transcript."""
    if int(sess.get("sb_unit", 0)) >= 2:
        return "the gate sent the agent back %d times" % int(sess["sb_unit"])
    try:
        from . import harvest
        t0 = harvest.epoch(c["started"]) if isinstance(c.get("started"), str) else None
        stats = U._transcript_stats(project, t0, time.time()) if t0 is not None else None
        if stats and stats.get("corrections"):
            return "the human corrected the agent"
    except Exception as e:
        store.log_error("gate-anomaly", e)
    return None


def _decide(payload):
    """Return ('allow', message_or_None) or ('block', reason)."""
    cfg = store.config()
    if not cfg["gate"].get("enabled", True):
        return "allow", None
    from . import workers
    if workers.is_subagent_payload(payload):
        return decide_subagent(payload)
    cwd = _cwd(payload)
    sid = _session_key(payload, cwd)
    os.environ["SISI_SESSION_ID"] = sid
    sess = store.load_session(sid)
    if sess.get("subagent"):
        return "allow", None  # a session another agent started: its last message is its report to that agent
    if not (sess.get("started") or sess.get("first_seen")):
        sess["first_seen"] = store.now()
    top = gitutil.root(cwd)
    path = C.find(cwd)
    sess["req_contract"], sess["req_project"] = bool(path), top or cwd
    if isinstance(payload.get("transcript_path"), str):
        sess["transcript_path"] = payload["transcript_path"]  # `sisi retro` reads the request's start from it
    tp = sess.get("transcript_path") if isinstance(sess.get("transcript_path"), str) else None

    # 1. what did this session itself change since its last settled stop?
    try:
        attr = attribution.update(sess, tp) if tp else None
    except Exception as e:  # attribution must never break the gate: fail towards strict, not open
        store.log_error("gate-attribution", e)
        attr = {"gen": int(sess.get("attr_gen", 0) or 0), "writing": True, "unknown": True, "files": []}
    if attr is not None:
        try:
            from . import watch
            if watch.consume_pending(sess, sid, cwd):
                attr["unknown"] = True  # a shell command with a before but no after: strict
        except Exception as e:
            store.log_error("gate-watch-pending", e)
        _absorb_subagents(sess, sid)
        _note_own_paths(sess, attr, top)
    fp = gitutil.fingerprint(cwd, [path]) if top else None
    if attr is not None:
        gen = int(sess.get("attr_gen", 0) or 0)
        if attr["unknown"] or gen > int(sess.get("seen_gen", 0) or 0):
            sess["dirty"] = True
        sess["seen_gen"] = gen
    elif fp is None or fp != sess.get("settled_fp", sess.get("baseline_fp")):
        sess["dirty"] = True  # no transcript to read: the tree against its last settled state
    stop = _Stop(sess, sid, cfg, fp, attr)
    store.save_session(sid, sess)

    # the open unit
    c, errs, project = None, [], top or cwd
    if path:
        project = C.project_dir(path)
        if not trust.is_trusted(project):
            if sess.get("untrusted_notice") != project:
                sess["untrusted_notice"] = project
                store.save_session(sid, sess)
                return "allow", "sisi: " + trust.hint(project)
            return "allow", None
        try:
            c = C.load(path)
        except (OSError, ValueError) as e:
            errs, c = ["cannot read contract: %s" % e], {}
        if c is not None and c and C.is_unedited_skeleton(c):
            c, path = None, None  # nothing real written yet: behave as if there is no contract
            sess["req_contract"] = False
        elif isinstance(c, dict) and c.get("status") == "closed":
            c, path = None, None  # the unit is archived; new work stands or falls on its own
            sess["req_contract"] = False
        elif isinstance(c, dict) and c.get("status") == "paused":
            if not sess.get("dirty") or top is None or c.get("pause_fp") == fp:
                return stop.allow(cwd, settle=bool(sess.get("dirty")))  # a recorded wait, no new change
            U.resume(c, path)  # the tree changed since the pause: the wait is over
            stop.refresh(cwd, path)
    if not sess.get("dirty"):
        return _late_close(stop, cwd, c, path, project)

    # 2. the profile
    if top is None:
        if c is None:
            return stop.allow(cwd)
        floor, reasons, own_floor = "isolated", ["not a git repository: the change cannot be measured"], None
    else:
        own = _own_changed(sess, sid, cwd, top, attr)
        own_floor, own_reasons = risk.assess(own, diff_text=_diff_text(project, sess.get("head")),
                                             patterns=risk.load_patterns(project))
        claimed = c is not None and (attr is None or _claims_unit(sess, path))  # no transcript: every change is ours
        if own_floor == "trivial" and not claimed and not (c is not None and sess.get("last_unit") == c.get("id")):
            return stop.allow(cwd)  # documentation and the like, or nothing of this session's: nothing is asked
        if c is not None:
            files = gitutil.measure(project, c.get("base_head"))["files"]
            floor, reasons = risk.assess(files, diff_text=_diff_text(project, c.get("base_head")),
                                         patterns=risk.load_patterns(project))
            floor = max(floor, own_floor, key=lambda p: assure.ORDER[p])
        else:
            floor, reasons = own_floor, own_reasons
    profile, info = assure.effective_profile(floor, c)
    if c is not None:
        sess["last_unit"] = c.get("id")
    req = assure.requirements(profile)

    # a fresh waiver for a change with no unit: recorded as a deviation, the contract is not demanded
    w = _new_waiver(top or project, sess) if c is None else None
    if w:
        sess["waiver_ns"] = w.get("ns", 0)
        return stop.allow(cwd)

    if profile == "trivial" or not req.get("contract"):
        return _trivial(stop, cwd, c, path, project, profile)

    # 3. what the profile requires, and the selected fast checks
    results, deadline = [], time.time() + float(cfg["gate"].get("budget_s", 120))
    if c is not None and not errs:
        errs = C.validate(c)
    if c is not None and not errs:
        t_run = time.time()
        results = V.run(c, project, deadline, cfg["verify"]["default_timeout_s"], tiers=("fast",), contract_path=path)
        sess["req_check_s"] = float(sess.get("req_check_s", 0.0)) + (time.time() - t_run)
        V.record(c, project, results, fp)
    ds = None
    if req.get("all_checks") and c is not None and not errs:
        try:
            from . import deep as D
            ds = D.deep_state(c, project, fp)
        except Exception as e:
            store.log_error("gate-deep", e)
    failing = V.blocking(results)
    if ds and ds["state"] == "failed" and ds["fresh"]:
        failing = failing + [{"id": i["id"], "status": "failed", "reason": "deep", "tail": i["tail"]} for i in ds["failed"]]
    miss = assure.missing(profile, c, project, results, errs, ds["state"] if ds else None)

    if miss or failing:
        return _send_back(stop, cwd, c, path, project, profile, info, reasons, miss, failing, results)

    # 4. all green
    if c is not None and c.get("unverified"):
        c.pop("unverified")  # re-verified since the gate released it
        C.save(path, c)
        stop.refresh(cwd, path)
    note = _technique_note(c, profile, sess)
    if c is None:  # a waived change, or nothing that needs a unit
        return stop.allow(cwd, note)
    findings = []
    try:
        from . import learning
        findings = learning.findings_for_unit(project, c["id"])
    except Exception as e:
        store.log_error("gate-findings", e)
    if findings:
        return _close(stop, cwd, c, path, project, profile, note)
    if not cfg.get("retro", {}).get("required", True):
        return stop.allow(cwd, note)
    if sess.get("offered") == [c["id"], fp]:
        return stop.allow(cwd, note)  # offered once for this state of the tree; not repeated
    sess["offered"] = [c["id"], fp]
    text = _offer_text(c, profile, None)
    return stop.block(text + ("\n" + note if note else ""), c["id"], project, counts=False)


def _trivial(stop, cwd, c, path, project, profile):
    """A trivial change asks nothing, unless the unit shows an anomaly: then the retro is asked once."""
    sess = stop.sess
    if c is None or not stop.cfg.get("retro", {}).get("required", True):
        return stop.allow(cwd)
    why = _anomaly(c, project, sess)
    if not why:
        return stop.allow(cwd)
    try:
        from . import learning
        if learning.findings_for_unit(project, c["id"]):
            return _close(stop, cwd, c, path, project, profile, None)
    except Exception as e:
        store.log_error("gate-findings", e)
    if sess.get("offered") == [c["id"], None]:
        return stop.allow(cwd)
    sess["offered"] = [c["id"], None]
    return stop.block(_offer_text(c, profile, why), c["id"], project, counts=False)


def _late_close(stop, cwd, c, path, project):
    """This session changed nothing, but a retro was recorded for the open unit it evaluated before:
    the unit closes now rather than waiting for the next change."""
    s = stop.sess
    if c is not None and path and c.get("status") == "open" and s.get("last_unit") == c.get("id") \
            and not c.get("unverified"):
        try:
            from . import learning
            if learning.findings_for_unit(project, c["id"]):
                rec, msg, ok = U.close_unit(c, path, project)
                if ok:
                    stop.refresh(cwd, path)
                    return stop.allow(cwd, _cycle_note(stop.sid))
        except Exception as e:
            store.log_error("gate-late-close", e)
    return "allow", None


def _cycle_note(sid):
    try:
        from . import cycle
        note = cycle.due_notice(session=sid)
        return note + " (This turn may end; the cycle is background work, not a send-back.)" if note else None
    except Exception as e:
        store.log_error("gate-cycle-notice", e)
        return None


def _close(stop, cwd, c, path, project, profile, note):
    rec, msg, ok = U.close_unit(c, path, project)
    if not ok:  # it cannot close as delivered: say why, like any other send-back
        return _send_back(stop, cwd, c, path, project, profile, {}, [], [(msg.replace("sisi: ", ""), "")], [], [])
    stop.refresh(cwd, path)
    cyc = _cycle_note(stop.sid)
    return stop.allow(cwd, "\n".join(x for x in (note, cyc) if x) or None)


def _send_back(stop, cwd, c, path, project, profile, info, reasons, miss, failing, results):
    uid = c["id"] if c else None
    why = ["%s" % m[0] for m in miss] + ["%s failed" % f["id"] for f in failing]
    if stop.exhausted():
        return _release(stop, cwd, c, path, project, why)
    lines = ["sisi: this %s change is not ready to hand over (send-back {n})." % profile]
    if reasons:
        lines[0] = lines[0][:-1] + " because %s." % reasons[0][:160]
    if info.get("refused"):
        lines.append("The contract declares %r, but the change is %r; add risk.why to lower it on the record."
                     % (info.get("declared"), info.get("floor")))
    if miss:
        lines.append("Missing:")
        lines += ["- %s -> %s" % (a, b) if b else "- %s" % a for a, b in miss]
    if failing:
        lines.append("Failing checks:")
        lines += assure.failure_lines(failing, per_check=3)
    lines.append("Fix these, then run `sisi verify`. Do not report this work as done.")
    note = _technique_note(c, profile, stop.sess)
    if note:
        lines.append(note)
    return stop.block(assure.fit(lines), uid, project)


def decide(payload):
    """The gate's answer: the contract decision, then — only on an otherwise-clean stop —
    the rule-5 question check, which sends the agent back at most once per final message."""
    action, msg = _decide(payload)
    if action != "allow":
        return action, msg
    try:
        from . import questions
        q = questions.sendback(payload)
    except Exception as e:  # the question check must never break the gate
        store.log_error("gate-question", e)
        q = None
    return q if q else (action, msg)


def decide_subagent(payload):
    """SubagentStop: never blocks and never asks for a retro. A subagent's last message is its
    report to its parent and stays that. What it observed is recorded for the parent's gate: that
    it edited, and which files its edit tools named."""
    try:
        tp = payload.get("agent_transcript_path")
        if isinstance(tp, str) and tp and isinstance(payload.get("session_id"), str):
            edited, files, _start = attribution.observed_edits(tp)
            store.append("subagents", {"ts": store.now(), "ns": time.time_ns(), "session": payload["session_id"],
                                       "agent": payload.get("agent_id"), "project": _cwd(payload),
                                       "edited": edited, "files": files})
    except Exception as e:
        store.log_error("gate-subagent", e)
    return "allow", None


def _record_delivery(payload):
    """The request is delivered: write one delivery row. Never raises, never changes the gate's answer."""
    try:
        from . import delivery
        cwd = _cwd(payload)
        sid = _session_key(payload, cwd)
        delivery.record(payload, store.load_session(sid), sid, cwd)
    except Exception as e:
        store.log_error("gate-delivery", e)


def main(args=()):
    try:
        payload = _read_payload()
        action, msg = (decide_subagent if "--subagent" in args else decide)(payload)
    except Exception as e:  # fail open
        store.log_error("gate", e)
        return 0
    if action == "allow" and "--subagent" not in args:
        _record_delivery(payload)
    if action == "block":
        sys.stdout.write(json.dumps({"decision": "block", "reason": msg}) + "\n")
    elif msg:
        sys.stdout.write(json.dumps({"systemMessage": msg}) + "\n")
    return 0
