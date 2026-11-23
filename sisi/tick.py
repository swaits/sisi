"""Session-start hook. Records the session baseline, checks wiring, prints at most one line. Must be fast."""
import json, os, sys, time

from . import store


MAX_AGE_S = 30 * 86400


def _prune(now=None):
    """Delete per-session state files untouched for 30 days."""
    from . import paths
    d = os.path.join(paths.state(), "sessions")
    cutoff = (now or time.time()) - MAX_AGE_S
    try:
        with os.scandir(d) as it:
            for e in it:
                if e.name.endswith(".json") and e.is_file(follow_symlinks=False) and e.stat().st_mtime < cutoff:
                    try:
                        os.unlink(e.path)
                    except OSError:
                        pass
    except OSError:
        pass


def _export_session(sid):
    """Claude Code lets a SessionStart hook append `export` lines to $CLAUDE_ENV_FILE for later Bash commands, so
    `sisi retro`, `note` and `learn` know the session id. (From Claude Code behaviour, not confirmed in the docs I read.)"""
    f = os.environ.get("CLAUDE_ENV_FILE")
    if f and sid and not str(sid).startswith("cwd-"):
        import shlex
        try:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write("export SISI_SESSION_ID=%s\nexport SISI_TOOL=%s\n" % (shlex.quote(str(sid)), shlex.quote(store.tool() or "claude-code")))
        except OSError:
            pass


def _decision_line():
    """One line for a decision waiting for the owner, via the learning module when it
    provides one; a missing function prints nothing."""
    for mod_name in ("cycle", "retro", "scope"):
        try:
            mod = __import__("sisi." + mod_name, fromlist=["*"])
        except Exception:
            continue
        for name in ("pending_decision_line", "owner_decision_line", "decision_waiting_line",
                     "pending_owner_line"):
            fn = getattr(mod, name, None)
            if callable(fn):
                try:
                    out = fn()
                except TypeError:
                    try:
                        out = fn(os.getcwd())
                    except Exception:
                        return ""
                except Exception:
                    return ""
                return out if isinstance(out, str) else ""
    return ""


def _handover_line(sess, sid, cwd):
    """Handover items for this project, once per session."""
    try:
        if sess.get("handover_shown"):
            return ""
        from . import handover
        notice = handover.notice(cwd)
        if notice:
            sess["handover_shown"] = True
            try:
                store.save_session(sid, sess)
            except Exception:
                pass
            return notice
    except Exception:
        pass
    return ""


def main(args=()):
    try:
        payload = {}
        if sys.stdin is not None and not sys.stdin.isatty():
            try:
                d = json.loads(store.read_stdin() or "{}")
                payload = d if isinstance(d, dict) else {}
            except ValueError:
                pass
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and os.path.isdir(payload.get("cwd")) else os.getcwd()
        sid = payload.get("session_id") or "cwd-%d" % os.getpid()
        rec = {}
        if payload.get("source", "startup") == "startup" or not store.load_session(sid):
            rec = {"session_id": sid, "cwd": cwd, "started": store.now(), "tool": store.tool(),
                   "source": payload.get("source"), "blocks": 0}
            if isinstance(payload.get("model"), str) and payload["model"]:
                rec["model"] = payload["model"]
            try:
                from . import workers as _W
                if _W.is_subagent_payload(payload):
                    rec["subagent"] = True
            except Exception:
                pass
            if isinstance(payload.get("transcript_path"), str):
                rec["transcript_path"] = payload["transcript_path"]
                # Attribution starts here: the gate reads only transcript bytes after this offset.
                rec["attr_tp"] = payload["transcript_path"]
                try:
                    rec["attr_offset"] = os.path.getsize(os.path.expanduser(payload["transcript_path"]))
                except OSError:
                    rec["attr_offset"] = 0
                rec.update(attr_gen=0, attr_pass_gen=0, attr_retro_gen=0, attr_baseline_gen=0,
                           attr_writing=False, attr_files=[], attr_sub_offsets={})
            from . import contract as C, gitutil
            if gitutil.root(cwd):
                rec["head"] = gitutil.head(cwd)
                rec["baseline"] = gitutil.measure(cwd)
                rec["baseline_fp"] = gitutil.fingerprint(cwd, [C.find(cwd)])
            store.save_session(sid, rec)
        _prune()
        from . import wiring
        problem = wiring.quick_problem()
        if problem:
            sys.stdout.write("sisi: %s. Run `sisi doctor`.\n" % problem)
        _export_session(sid)
        try:
            sess = rec or store.load_session(sid)
            model = payload.get("model") if isinstance(payload.get("model"), str) else sess.get("model")
            if model and sess.get("model") != model:
                sess["model"] = model
                store.save_session(sid, sess)
            if model and not sess.get("orch_line_shown"):
                from . import workers as _W
                lines = _W.session_lines(model, payload)
                for ln in lines:
                    sys.stdout.write(ln + "\n")
                if lines:
                    sess["orch_line_shown"] = True
                    store.save_session(sid, sess)
        except Exception as e:
            store.log_error("tick-workers", e)
        try:
            from . import cycle
            note = cycle.due_notice(session=sid if isinstance(sid, str) else None)
            if note:
                sys.stdout.write(note + "\n")
        except Exception as e:
            store.log_error("tick-cycle", e)
        try:
            decision = _decision_line()
            if decision:
                sys.stdout.write(decision + "\n")
        except Exception as e:
            store.log_error("tick-decision", e)
        try:
            sess2 = rec or store.load_session(sid)
            hline = _handover_line(sess2, sid if isinstance(sid, str) else "cwd", cwd)
            if hline:
                sys.stdout.write(hline + "\n")
        except Exception as e:
            store.log_error("tick-handover", e)
    except Exception as e:
        store.log_error("tick", e)
    return 0
