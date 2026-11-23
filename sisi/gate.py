"""End-of-turn gate. Claude Code Stop hook: JSON on stdin, block = JSON {"decision":"block","reason":...} on stdout, exit 0.
Anything that goes wrong inside sisi allows (fail open) and is logged to the state dir."""
import hashlib, json, os, sys, time

from . import contract as C, deep as D, gitutil, store, trust, verify as V


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


def _new_waiver(project, sess):
    """Latest waiver for this project made during this session and not yet applied."""
    since, seen, best = sess.get("started") or "", sess.get("waiver_ns", 0), None
    for w in store.read("waivers"):
        if w.get("project") == project and w.get("ts", "") >= since and w.get("ns", 0) > seen:
            best = w
    return best


class _Ctx:
    def __init__(self, sess, sid, cfg, fp):
        self.sess, self.sid, self.cfg, self.fp = sess, sid, cfg, fp

    def save(self):
        store.save_session(self.sid, self.sess)

    def allow(self, msg=None):
        self.sess.update(blocks=0, last_fp=self.fp, last_decision="allow")
        self.save()
        return "allow", msg

    def block(self, template, contract_id=None, project=None, kind="fast"):
        """One path for every kind of block: strikes, 3-strike release as UNVERIFIED."""
        s, maxb = self.sess, int(self.cfg["gate"].get("max_blocks", 3))
        blocks = int(s.get("blocks", 0))
        if blocks >= maxb:
            if kind == "retro":
                self.allow()
                return "allow", ("sisi: no retrospective was recorded after %d reminders, so the gate let this turn end. "
                                 "Run `sisi retro` before you finish if you still can." % maxb)
            store.append("results", {"ts": store.now(), "contract": contract_id, "project": project, "check": "gate",
                                     "item": "gate", "kind": None, "rung": None, "status": "unverified",
                                     "duration_s": 0.0, "tool": store.tool(), "session": self.sid})
            _, _ = self.allow()
            return "allow", ("sisi: result is UNVERIFIED. The gate has sent this work back %d times and it is still "
                             "not verified, so it let the turn end. Report the work as unverified." % maxb)
        s["req_blocks"] = int(s.get("req_blocks", 0)) + 1  # send-backs during this request, for the delivery row
        s.update(blocks=blocks + 1, last_fp=self.fp, last_decision="block", last_msg=template, last_kind=kind,
                 last_contract=contract_id, last_project=project)
        self.save()
        return "block", template.replace("{n}", "%d of %d" % (blocks + 1, maxb))


def decide(payload):
    """Return ('allow', message_or_None) or ('block', reason)."""
    cfg = store.config()
    g = cfg["gate"]
    if not g.get("enabled", True):
        return "allow", None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and os.path.isdir(payload.get("cwd")) else os.getcwd()
    sid = _session_key(payload, cwd)
    os.environ["SISI_SESSION_ID"] = sid
    sess = store.load_session(sid)
    if not (sess.get("started") or sess.get("first_seen")):
        sess["first_seen"] = store.now()
        store.save_session(sid, sess)
    since = sess.get("started") or sess.get("first_seen")
    path = C.find(cwd)
    sess["req_contract"], sess["req_project"] = bool(path), cwd
    if isinstance(payload.get("transcript_path"), str):
        sess["transcript_path"] = payload["transcript_path"]  # `sisi retro` reads the request's start from it
    c, errs = None, []
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
            errs = ["cannot read contract: %s" % e]
        if c is not None and C.is_unedited_skeleton(c):
            path = None  # nothing real written yet: behave as if there is no contract
            sess["req_contract"] = False
    top = gitutil.root(cwd)
    sess["req_project"] = top or (project if path else cwd)
    fp = gitutil.fingerprint(cwd, [path]) if top else None
    ctx = _Ctx(sess, sid, cfg, fp)
    ds = None
    if path and c is not None and not C.validate(c):
        try:
            ds = D.deep_state(c, project, fp)
        except Exception as e:
            store.log_error("gate-deep", e)
    dfail = bool(ds and ds["state"] == "failed" and ds["fresh"])  # deep failure on the current tree
    retro_on = bool(cfg.get("retro", {}).get("required", True))
    repo_key = top or (project if path else cwd)

    def need_retro(real_work):
        """True when real work was done and no retro covers the current tree state yet."""
        if not (retro_on and real_work):
            return False
        sess["real_work"] = True
        from . import retro
        if retro.satisfied(repo_key, since, fp):
            sess["retro_done"] = True
            return False
        return True

    w = _new_waiver(top, sess) if (top and not path) else None  # a fresh waiver re-opens the decision
    # A turn that changed nothing is not punished and not re-checked.
    if fp is not None and not w:
        if sess.get("last_fp") is not None:
            same, last = fp == sess["last_fp"], sess.get("last_decision")
        else:
            same, last = fp == sess.get("baseline_fp"), "allow"
        if same and last == "allow" and not dfail:
            return "allow", None
        retro_clear = False
        if same and last == "block" and sess.get("last_kind") == "retro":
            from . import retro
            retro_clear = retro.satisfied(repo_key, since, fp)
        if same and last == "block" and sess.get("last_msg") and not retro_clear \
                and not (sess.get("last_kind") == "deep" and not dfail):
            return ctx.block(sess["last_msg"], sess.get("last_contract"), sess.get("last_project"),
                             kind=sess.get("last_kind", "fast"))

    if path:
        deadline = time.time() + float(g.get("budget_s", 120))
        if c is not None:
            errs = C.validate(c)
        if errs:
            results = [{"item": "contract", "id": "contract", "status": "failed", "kind": None, "rung": None,
                        "claim": "contract is invalid", "duration_s": 0.0, "tail": "\n".join(errs)}]
        else:
            t_run = time.time()
            results = V.run(c, project, deadline, cfg["verify"]["default_timeout_s"], tiers=("fast",))
            sess["req_check_s"] = float(sess.get("req_check_s", 0.0)) + (time.time() - t_run)
            V.record(c, project, results, fp)
        if V.ok(results):
            if dfail:
                tails = "\n".join("- deep check %s [%s]:\n%s" % (i["id"], i["status"], "\n".join("    " + l for l in i["tail"].splitlines()[-15:]))
                                  for i in ds["failed"])
                return ctx.block("sisi: the fast checks pass, but the deep checks failed on the current tree "
                                 "(send-back {n}). Fix the work, then re-run them with `sisi verify --deep "
                                 "--background` (see `sisi verify --state`). Do not report this work as done.\n\n%s"
                                 % tails[:4000], c["id"], project, kind="deep")
            changed = fp is None or fp != sess.get("baseline_fp")
            if need_retro(changed):
                from . import retro
                return ctx.block(retro.TEMPLATE, c["id"] if c else None, project, kind="retro")
            if ds and ds["state"] != "fresh-pass" and sess.get("deep_notice") != (fp or "nofp"):
                sess["deep_notice"] = fp or "nofp"
                text = ("sisi: the fast checks pass, but the deep checks are %s (%d item%s). The work is NOT yet "
                        "verified end to end: report it as not yet done, say that deep checks are pending, and "
                        "start them with `sisi verify --deep --background` (progress: `sisi verify --state`)."
                        % (ds["state"], ds["items"], "" if ds["items"] == 1 else "s"))
                return ctx.allow({"message": "sisi: deep checks %s; the work is not yet fully verified" % ds["state"],
                                  "context": text})
            return ctx.allow()
        return ctx.block("sisi: the contract at %s is not satisfied (send-back {n}). Fix the work, then run "
                         "`sisi verify` until it passes. Do not report this work as done.\n\n%s"
                         % (path, V.failure_report(results)), c["id"] if c else None, project)

    if not top:
        return "allow", None
    if sess.get("baseline") is None:
        sess.update(baseline=gitutil.measure(cwd), head=gitutil.head(cwd), started=sess.get("started") or store.now())
        sess["baseline_fp"] = fp
        store.save_session(sid, sess)
        return "allow", None
    # Fix 4: growth is measured from the session start, or from the latest waiver.
    if w:
        sess["baseline"] = {"lines": w.get("lines", 0), "files": w.get("files", [])}
        sess["head"] = w.get("head")
        sess["waiver_ns"] = w.get("ns", 0)
        sess["blocks"] = 0
    now = gitutil.measure(cwd, sess.get("head"))
    base = sess["baseline"]
    dl = max(0, now["lines"] - base["lines"])
    df = len(set(now["files"]) - set(base["files"]))
    if not (dl > int(g.get("growth_lines", 40)) or df > int(g.get("growth_files", 3))):
        if need_retro(bool(sess.get("waiver_ns"))):  # a waiver in this session means real work happened
            from . import retro
            return ctx.block(retro.TEMPLATE, kind="retro")
        return ctx.allow()
    return ctx.block("sisi: this session has changed %d lines and %d files since its start and there is no "
                     "contract (send-back {n}). Write `.sisi/contract.json` (`sisi contract init` makes the "
                     "skeleton; give it at least one check with a real command), then run `sisi verify`. If "
                     "the change needs no checks, run `sisi contract waive \"<reason>\"` instead." % (dl, df))


EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def subagent_edits(transcript):
    """(edited_files, start_ts) from a subagent transcript (JSONL). start_ts is in sisi's timestamp format, or None."""
    edited, start = False, None
    with open(os.path.expanduser(transcript), encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if start is None and isinstance(d.get("timestamp"), str) and len(d["timestamp"]) >= 19:
                start = d["timestamp"][:19] + "Z"
            content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
            for x in content if isinstance(content, list) else []:
                if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") in EDIT_TOOLS:
                    edited = True
    return edited, start


def decide_subagent(payload):
    """SubagentStop: only the retro requirement, only when the subagent edited files (read from its transcript)."""
    cfg = store.config()
    if not cfg.get("retro", {}).get("required", True) or not cfg["gate"].get("enabled", True):
        return "allow", None
    tp = payload.get("agent_transcript_path")
    if not isinstance(tp, str):
        return "allow", None  # cannot tell whether it changed files: do not block
    edited, start = subagent_edits(tp)
    if not edited or not start:
        return "allow", None
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and os.path.isdir(payload.get("cwd")) else os.getcwd()
    from . import retro
    if retro.satisfied(retro.repo_of(cwd), start, None):
        return "allow", None
    key = "sub-%s" % (payload.get("agent_id") or "unknown")
    sess = store.load_session(key)
    blocks, maxb = int(sess.get("blocks", 0)), int(cfg["gate"].get("max_blocks", 3))
    if blocks >= maxb:
        return "allow", None
    sess["blocks"] = blocks + 1
    store.save_session(key, sess)
    return "block", retro.TEMPLATE.replace("{n}", "%d of %d" % (blocks + 1, maxb))


def _record_delivery(payload):
    """The request is delivered: write one delivery row. Never raises, never changes the gate's answer."""
    try:
        from . import delivery
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and os.path.isdir(payload.get("cwd")) else os.getcwd()
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
    elif isinstance(msg, dict):
        # Documented for Stop: hookSpecificOutput.additionalContext reaches the model (and continues the turn once).
        sys.stdout.write(json.dumps({"systemMessage": msg["message"], "hookSpecificOutput": {
            "hookEventName": "Stop", "additionalContext": msg["context"]}}) + "\n")
    elif msg:
        sys.stdout.write(json.dumps({"systemMessage": msg}) + "\n")
    return 0
