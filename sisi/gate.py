"""End-of-turn gate. Claude Code Stop hook: JSON on stdin, block = JSON {"decision":"block","reason":...} on stdout, exit 0.
Anything that goes wrong inside sisi allows (fail open) and is logged to the state dir."""
import hashlib, json, os, re, shlex, sys, time

from . import contract as C, deep as D, gitutil, paths, store, trust, verify as V


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
        if msg is None:  # a clean stop is one of the places the cycle-due counter is checked (no scheduler)
            try:
                from . import cycle
                note = cycle.due_notice(session=self.sid)
                if note:
                    msg = note + " (This turn may end; the cycle is background work, not a send-back.)"
            except Exception as e:
                store.log_error("gate-cycle-notice", e)
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


# ---------------------------------------------------------------- attribution
# Attribution reads this session's own transcript (Claude-Code-shaped JSONL: assistant records whose
# message.content holds tool_use blocks). Only bytes after the per-session offset stored in the session
# record are read, so a long transcript costs only its new tail; subagent transcripts found under
# <transcript-without-.jsonl>/subagents/** are read the same way and count as this session's edits.
# Edit/Write/MultiEdit/NotebookEdit (and any tool whose name says it writes) count, with the file paths
# in their input. Shell (Bash) commands count when they plausibly write: a redirect, tee/dd-of, an
# in-place editor (sed -i, perl -i, awk -i inplace), git apply/checkout/restore/reset/clean/mv/rm,
# patch, cp/mv/rm/touch/mkdir, or any program that is not on the provably read-only list (ls, cat,
# grep, git status/diff/log/..., test runners and interpreters therefore count: they can write).
# Known blind spots: a read-only-looking command that writes through indirection sisi cannot see
# (a script reached by a read-only interpreter flag combination that slips the lists, a daemon, or a
# tool whose transcript shape is not Claude-Code JSONL), and writes made between the last complete
# transcript line and a crash. A missing/unreadable transcript, a corrupt line, or a shell command
# that cannot be tokenised is treated as an edit by this session (fail strict, never fail open here);
# so is an unread tail over 64 MB, which is skipped (offset moved to its end) rather than scanned
# inside the gate's time budget.

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_READONLY_CMDS = {"ls", "cat", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag", "wc", "file",
                  "stat", "du", "df", "which", "type", "pwd", "date", "env", "printenv", "sort",
                  "uniq", "cut", "tr", "jq", "yq", "diff", "cmp", "md5sum", "sha1sum", "sha256sum",
                  "basename", "dirname", "realpath", "readlink", "ps", "top", "free", "uname",
                  "hostname", "id", "whoami", "less", "more", "man", "help", "history"}
_READONLY_GIT = {"status", "diff", "log", "show", "rev-parse", "ls-files", "ls-tree", "describe",
                 "blame", "grep", "cat-file", "branch", "tag", "remote", "config", "add", "commit"}
_GH_READ = {("run", "list"), ("run", "view"), ("run", "watch"), ("pr", "list"), ("pr", "view"),
            ("pr", "status"), ("pr", "diff"), ("pr", "checks"), ("issue", "list"), ("issue", "view"),
            ("issue", "status"), ("repo", "view"), ("repo", "list"), ("release", "list"),
            ("release", "view"), ("workflow", "list"), ("workflow", "view"), ("auth", "status")}
_WRITE_WORDS = ("edit", "write", "create", "delete", "move", "rename", "patch", "apply", "insert")
_SHELL_WRITE_RE = re.compile(
    r">>?[^=]|\btee\b|\bdd\b[^;&|]*\bof=|\bsed\b[^;&|]*\s-[a-z]*i|\bperl\b[^;&|]*\s-[a-z]*i"
    r"|\bawk\b[^;&|]*inplace|\bgit\s+(apply|checkout|restore|reset|clean|mv|rm)\b"
    r"|\bpatch\b|\b(cp|mv|rm|touch|mkdir|rmdir|install|ln)\b", re.I)


def _shell_may_write(command):
    """True: plausibly writes files. False: provably read-only. None: cannot be tokenised."""
    if not isinstance(command, str) or not command.strip():
        return False
    if _SHELL_WRITE_RE.search(command):
        return True
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    segments, cur = [], []
    for tok in tokens:
        if tok in (";", "&", "|", "&&", "||"):
            segments.append(cur)
            cur = []
        else:
            cur.append(tok)
    segments.append(cur)
    for seg in segments:
        i = 0
        while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in ("sudo", "command", "exec", "time", "nice")):
            i += 1
        if i >= len(seg):
            continue
        prog = os.path.basename(seg[i])
        rest = seg[i + 1:]
        if prog in ("cd", "export", "unset", "set", "alias", "umask", "wait", "jobs", "fg", "bg",
                    "exit", "return", "break", "continue", "shift", "readonly", "local", "declare",
                    "typeset", "echo", "printf", "true", "false", ":", "test", "[", "[[", "eval"):
            if prog == "eval":
                return True
            continue
        if prog == "find":
            if any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint") for a in rest):
                return True
            continue
        if prog == "git":
            sub = next((a for a in rest if not a.startswith("-")), "")
            if sub == "stash":  # only listing a stash leaves the tree alone; push/pop/apply change it
                tail = rest[rest.index(sub) + 1:]
                if not tail or tail[0] in ("list", "show"):
                    continue
                return True
            if sub in _READONLY_GIT and not (sub == "config" and any(not a.startswith("-") for a in rest[rest.index(sub) + 1:])):
                continue  # add/commit touch .git only, never a working-tree file
            return True
        if prog == "gh":
            pair = tuple(a for a in rest if not a.startswith("-"))[:2]
            if pair in _GH_READ:
                continue
            if pair and pair[0] == "api" and not any(a in ("-X", "--method", "-f", "-F", "--field", "--raw-field")
                                                     or a.startswith(("-f", "-F")) for a in rest):
                continue
            return True
        if prog == "sisi":
            # sisi writes only personal data and state, never the project — except contract
            # init/waive/trust, which do record something about (or in) this project.
            if rest and rest[0] == "contract":
                if len(rest) > 1 and rest[1] in ("init", "waive", "trust", "untrust"):
                    return True
                continue
            continue
        if prog in _READONLY_CMDS:
            if prog in ("sed", "awk", "jq", "yq") and any("inplace" in a or a.startswith("-i") for a in rest):
                return True
            continue
        return True  # interpreters, build/test runners, scripts, anything unlisted: can write
    return False


def _input_files(inp):
    out = []
    if isinstance(inp, dict):
        for k in ("file_path", "notebook_path", "path", "filename", "filePath"):
            if isinstance(inp.get(k), str) and inp[k]:
                out.append(inp[k])
    return out


def _parse_transcript_chunk(data, measured=False):
    """Parse complete JSONL bytes. Returns (edits, files, writing, corrupt, consumed_bytes, shell_edits).
    In measured mode Bash calls are not guessed from their text at all: the before/after tree
    measurement (sisi/watch.py) has already attributed whatever they actually changed — except
    `sisi contract init/waive/trust`, which record project state outside the measured files."""
    if data.endswith(b"\n") or not data:
        consumed, body = len(data), data
    else:
        cut = data.rfind(b"\n")
        tail = data[cut + 1:]
        try:
            json.loads(tail.decode("utf-8", "replace"))
            consumed, body = len(data), data  # a complete final line without its newline yet
        except ValueError:
            consumed, body = cut + 1, data[:cut + 1]  # partial line: leave it for the next read
    edits, files, writing, corrupt, shell_edits = 0, [], False, 0, 0
    for raw in body.split(b"\n"):
        if not raw.strip():
            continue
        if len(raw) > 131072 and b"tool_use" not in raw and b"Bash" not in raw:
            continue  # a huge tool-result line: no tool call hides in it worth parsing
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            corrupt += 1
            edits += 1  # an unreadable line may be the edit we cannot see: count it
            writing = True
            continue
        if not isinstance(d, dict):
            continue
        content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
        for x in content if isinstance(content, list) else []:
            if not isinstance(x, dict) or x.get("type") != "tool_use":
                continue
            name = x.get("name") or ""
            inp = x.get("input") if isinstance(x.get("input"), dict) else {}
            if name in EDIT_TOOLS or any(w in name.lower() for w in _WRITE_WORDS):
                edits += 1
                writing = True
                files += _input_files(inp)
            elif name in ("Bash", "Shell", "bash", "shell"):
                cmd = inp.get("command") if isinstance(inp.get("command"), str) else inp.get("cmd")
                if measured:
                    if isinstance(cmd, str) and re.search(r"\bsisi\s+contract\s+(init|waive|trust|untrust)\b", cmd):
                        edits += 1
                        shell_edits += 1
                        writing = True
                        files.append(".sisi/contract.json")
                    continue  # everything else was measured, not guessed
                may = _shell_may_write(cmd)
                if may is None:
                    corrupt += 1
                    edits += 1
                    shell_edits += 1
                    writing = True
                elif may:
                    edits += 1
                    shell_edits += 1
                    writing = True
    return edits, files, writing, corrupt, consumed, shell_edits


def _scan_one(sess, store_key, path):
    """Advance one transcript's offset in the session record. Returns (edits, files, writing, unknown)."""
    offsets = sess.setdefault("attr_sub_offsets", {}) if store_key == "sub" else None
    try:
        size = os.path.getsize(os.path.expanduser(path))
    except OSError:
        return 0, [], False, True, 0  # missing or unreadable: unknown, treated as edited by the caller
    if store_key == "sub":
        offset = int(offsets.get(path, 0) or 0)
    else:
        offset = int(sess.get("attr_offset", 0) or 0)
    unknown = False
    if offset > size:
        offset, unknown = 0, True  # truncated or replaced: rescan, and do not trust the gap
    if size - offset > 64 * 1024 * 1024:
        # Too much unread tail to scan inside the gate's budget: skip it and count it as a
        # possible edit by this session (strict), rather than guessing it was someone else's.
        if store_key == "sub":
            offsets[path] = size
        else:
            sess["attr_offset"] = size
        return 1, [], True, True, 0
    edits, files, writing, sh = 0, [], False, 0
    try:
        with open(os.path.expanduser(path), "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return 0, [], False, True, 0
    if data:
        e, fl, w, corrupt, consumed, sh = _parse_transcript_chunk(data, measured=bool(sess.get("attr_measured")))
        edits, files, writing = e, fl, w
        unknown = unknown or corrupt > 0
        offset += consumed
    if store_key == "sub":
        offsets[path] = offset
    else:
        sess["attr_offset"] = offset
    return edits, files, writing, unknown, sh


def _subagent_transcripts(tp):
    """Native subagent transcripts under this session's transcript, Claude Code layout."""
    if not isinstance(tp, str) or not tp.endswith(".jsonl"):
        return []
    root = os.path.join(os.path.expanduser(tp)[:-len(".jsonl")], "subagents")
    out = []
    for dirpath, dirs, names in os.walk(root):
        dirs.sort()
        for n in sorted(names):
            if n.startswith("agent-") and n.endswith(".jsonl"):
                out.append(os.path.join(dirpath, n))
    return out


def _update_attribution(sess, tp):
    """Refresh this session's edit count from its own (and its native subagents') transcripts.

    Returns {"gen", "writing", "unknown"} or None when no transcript path is known at all
    (the caller then falls back to the pre-attribution behaviour). Fails towards edited."""
    if not isinstance(tp, str) or not tp:
        return None
    if sess.get("attr_tp") != tp:
        sess.update(attr_tp=tp, attr_offset=0, attr_gen=0, attr_pass_gen=0, attr_retro_gen=0,
                    attr_baseline_gen=0, attr_writing=False, attr_files=[], attr_sub_offsets={})
    sess.setdefault("attr_gen", 0)
    sess.setdefault("attr_pass_gen", 0)
    sess.setdefault("attr_retro_gen", 0)
    sess.setdefault("attr_baseline_gen", 0)
    unknown = False
    total, all_files, shell_total = 0, [], 0
    e, fl, w, unk, sh = _scan_one(sess, "main", tp)
    total += e
    shell_total += sh
    all_files += fl
    unknown = unknown or unk
    if w:
        sess["attr_writing"] = True
    for sub in _subagent_transcripts(tp):
        e, fl, w, unk, sh = _scan_one(sess, "sub", sub)
        total += e
        shell_total += sh
        all_files += fl
        unknown = unknown or unk
        if w:
            sess["attr_writing"] = True
    sess["attr_gen"] = int(sess.get("attr_gen", 0)) + total
    if all_files:
        have = sess.setdefault("attr_files", [])
        for f in all_files:
            if f not in have:
                have.append(f)
        del have[:-500]
    if unknown:
        sess["attr_writing"] = True
    return {"gen": int(sess["attr_gen"]), "writing": bool(sess.get("attr_writing")), "unknown": bool(unknown),
            "edits": total, "files": all_files, "shell_edits": shell_total}


def _changed_paths(top, cwd, own_files):
    """Up to five working-tree paths changed against HEAD that this session did not edit."""
    try:
        rels = gitutil.measure(cwd, gitutil.head(cwd))["files"]
    except Exception:
        return []
    own = set()
    for f in own_files or []:
        own.add(os.path.normpath(f))
        if top:
            try:
                own.add(os.path.normpath(os.path.relpath(f, top)))
            except ValueError:
                pass
    out = []
    for r in rels:
        if os.path.normpath(r) not in own:
            out.append(r)
        if len(out) >= 5:
            break
    return out


def _other_sessions(top, cwd, changed, sid, tp):
    """Session ids that plausibly made `changed` edits, from session records and sibling transcripts."""
    found = []

    def note(x):
        if x and x != sid and x not in found:
            found.append(x)

    def mentions(path, limit=2 * 1024 * 1024):
        try:
            with open(os.path.expanduser(path), "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - limit))
                data = f.read()
        except OSError:
            return False
        return any(os.path.basename(c).encode() in data or c.encode() in data for c in changed)

    try:
        names = sorted(os.listdir(os.path.join(paths.state(), "sessions")))
    except OSError:
        names = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(paths.state(), "sessions", n), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(r, dict):
            continue
        osid = r.get("session_id") or n[:-5]
        if osid == sid:
            continue
        proj = r.get("req_project") or r.get("cwd")
        if top and proj and gitutil.root(proj) not in (top, proj) and os.path.realpath(proj) != os.path.realpath(top):
            # a record for another folder says nothing about this tree
            if os.path.realpath(proj) != os.path.realpath(cwd):
                continue
        files = r.get("attr_files") or []
        hit = any(os.path.basename(f) in [os.path.basename(c) for c in changed] or
                  (top and os.path.normpath(os.path.join(top, c)) == os.path.normpath(f)) for f in files for c in changed)
        if hit:
            note(osid)
        elif isinstance(r.get("transcript_path"), str) and changed and mentions(r["transcript_path"]):
            note(osid)
    if isinstance(tp, str) and changed:
        try:
            sibs = sorted(os.listdir(os.path.dirname(os.path.expanduser(tp)) or "."))
        except OSError:
            sibs = []
        for n in sibs:
            if n.endswith(".jsonl") and os.path.join(os.path.dirname(os.path.expanduser(tp)), n) != os.path.expanduser(tp):
                p = os.path.join(os.path.dirname(os.path.expanduser(tp)), n)
                if mentions(p):
                    note(n[:-len(".jsonl")])
    return found[:3]


# ---------------------------------------------------------------- rule 5: ask through the dialog
# Tools with a confirmed question dialog whose transcripts sisi can read in Claude-Code shape.
# Codex's request_user_input is behind a flag that is off by default, OpenCode's question tool has
# no readable transcript file here, and the other tools name no dialog at all, so they are exempt.
QUESTION_DIALOG_TOOLS = {"claude-code": ("AskUserQuestion",), "qwen": ("ask_user_question",)}
_RHETORICAL = (r"^who (wouldn'?t|couldn'?t|doesn'?t)\b", r"^what could possibly\b",
               r"^(isn'?t|aren'?t) it (obvious|clear)\b")


def ends_with_question(text):
    """True when a final message ends by asking the reader a question. The rule, exactly: after
    removing fenced code blocks, blockquote lines and inline code, the last sentence of the last
    paragraph ends with a question mark that is not inside a closing quote (a quoted question),
    and the sentence does not start with a known rhetorical form."""
    if not isinstance(text, str) or not text.strip():
        return False
    kept, in_fence = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.lstrip().startswith(">"):
            continue
        kept.append(re.sub(r"`[^`]*`", "", line))
    paras = [p.strip() for p in re.split(r"\n\s*\n", "\n".join(kept)) if p.strip()]
    if not paras:
        return False
    para = " ".join(paras[-1].split())
    t = para.rstrip("*_ ")
    if t.endswith(('?"', "?\"", "?'", "?’", "?”")):  # the question mark sits inside a quotation
        return False
    t = t.rstrip(')]*_ ')
    if not t.endswith("?"):
        return False
    start = max(t.rfind(".", 0, len(t) - 1), t.rfind("!", 0, len(t) - 1), t.rfind("?", 0, len(t) - 1)) + 1
    sentence = t[start:].strip().lower()
    return not any(re.match(p, sentence) for p in _RHETORICAL)


def _last_turn(tp):
    """(final assistant text, tool names used) after the last message the human typed, from the
    transcript tail. None when the turn cannot be bounded (the caller then exempts the turn)."""
    try:
        size = os.path.getsize(os.path.expanduser(tp))
        with open(os.path.expanduser(tp), "rb") as f:
            f.seek(max(0, size - 2 * 1024 * 1024))
            data = f.read()
    except OSError:
        return None
    from . import harvest
    recs = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue  # a cut first line or a corrupt one: it cannot be the turn's evidence either way
        if isinstance(d, dict):
            recs.append(d)
    last_human = -1
    for i, d in enumerate(recs):
        if d.get("type") == "user":
            try:
                if harvest.typed_text(d)[0] is not None:
                    last_human = i
            except Exception:
                pass
    if last_human < 0:
        return None
    final, tools = "", set()
    for d in recs[last_human + 1:]:
        content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
        texts = []
        for x in content if isinstance(content, list) else []:
            if not isinstance(x, dict):
                continue
            if x.get("type") == "tool_use" and isinstance(x.get("name"), str):
                tools.add(x["name"])
            elif x.get("type") == "text" and isinstance(x.get("text"), str):
                texts.append(x["text"])
        if texts and d.get("type") in ("assistant", None):
            final = "\n".join(texts)
    return final, tools


def _question_sendback(payload):
    """('block', reason) when this turn ended by asking in reply text and no question dialog was
    used in it; None otherwise. At most once per final message, keyed by its hash in the session
    record, so a session can never be trapped. Subagents and dialog-less tools are exempt."""
    tool = store.tool()
    dialogs = QUESTION_DIALOG_TOOLS.get(tool or "")
    if not dialogs:
        return None
    if payload.get("agent_id") or payload.get("agent_transcript_path"):
        return None  # a subagent has no human to ask through a dialog
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and os.path.isdir(payload.get("cwd")) else os.getcwd()
    sid = _session_key(payload, cwd)
    sess = store.load_session(sid)
    tp = payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else sess.get("transcript_path")
    if not isinstance(tp, str) or not tp:
        return None
    turn = _last_turn(tp)
    if not turn:
        return None
    final, tools = turn
    if any(d in tools for d in dialogs) or not ends_with_question(final):
        return None
    key = hashlib.sha1(final.encode("utf-8", "replace")).hexdigest()[:16]
    if sess.get("q_block_key") == key:
        return None
    sess["q_block_key"] = key
    sess["req_blocks"] = int(sess.get("req_blocks", 0)) + 1
    store.save_session(sid, sess)
    return "block", ("sisi: you ended by asking the human a question in the text of your reply. Ask it through the "
                     "tool's question dialog (%s), with options to pick from and the one you recommend marked — or "
                     "decide it yourself, record the assumption, and finish without the question. "
                     "(Rule 5 in full: `sisi rule 5`.)" % dialogs[0])


def _decide(payload):
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
    tp = sess.get("transcript_path") if isinstance(sess.get("transcript_path"), str) else None
    try:
        attr = _update_attribution(sess, tp) if tp else None
    except Exception as e:  # attribution must never break the gate: fail towards strict, not open
        store.log_error("gate-attribution", e)
        attr = {"gen": int(sess.get("attr_gen", 0) or 0), "writing": True, "unknown": True}
    if attr is not None:
        try:
            from . import watch
            if watch.consume_pending(sess, sid, cwd):
                attr["unknown"] = True  # a shell command with a before but no after: strict
        except Exception as e:
            store.log_error("gate-watch-pending", e)
        since_pass = sess.setdefault("attr_since_pass", [])
        top0 = gitutil.root(cwd)
        for f in attr.get("files") or []:
            rel = f
            if os.path.isabs(f) and top0:
                try:
                    rel = os.path.relpath(f, top0)
                except ValueError:
                    rel = f
            if rel not in since_pass:
                since_pass.append(rel)
        if attr.get("shell_edits") and not sess.get("attr_measured") and "*shell*" not in since_pass:
            since_pass.append("*shell*")  # a text-classified shell edit: its paths are unknown
        try:
            store.save_session(sid, sess)  # persist the offset even on an early return below
        except Exception:
            pass

    def _own_since(key):
        if attr is None:
            return None  # no transcript path known: pre-attribution behaviour
        return bool(attr["unknown"] or int(sess.get("attr_gen", 0) or 0) > int(sess.get(key, 0) or 0))

    own_since_pass = _own_since("attr_pass_gen")
    own_since_retro = _own_since("attr_retro_gen")
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
            if attr is not None:
                sess["attr_retro_gen"] = int(sess.get("attr_gen", 0) or 0)
            return False
        return True

    _csp = {}

    def changed_paths_since_pass():
        if "v" not in _csp:
            v = None
            if attr is not None:
                try:
                    from . import watch
                    v = watch.changed_since_pass(sid, cwd)
                except Exception as e:
                    store.log_error("gate-watch-diff", e)
            _csp["v"] = v if v is not None else _changed_paths(top, cwd, [])
        return _csp["v"]

    def own_responsible():
        """This session answers for the failing tree when a path that changed since the last
        passing state is attributed to it (edit tool path, or a measured command window), or
        when attribution is uncertain. Gen-only fallback when no path differs (e.g. the
        contract itself changed, which the stat snapshot does not track)."""
        if attr is None:
            return True
        if attr["unknown"]:
            return True
        changed = changed_paths_since_pass()
        if not changed:
            return bool(own_since_pass)
        since = set(sess.get("attr_since_pass") or [])
        if "*shell*" in since or "*shell-unmeasured*" in since:
            return True
        return any(p in changed for p in since)

    def other_allow(failing_text, contract_id=None):
        """Someone else's failing tree: allow once per distinct tree state, recorded unverified."""
        if sess.get("other_notice_fp") == fp:
            return ctx.allow()
        sess["other_notice_fp"] = fp
        store.append("results", {"ts": store.now(), "contract": contract_id, "project": project if path else repo_key,
                                 "check": "gate", "item": "gate", "kind": None, "rung": None,
                                 "status": "unverified", "duration_s": 0.0, "tool": store.tool(), "session": sid})
        own_paths = set(sess.get("attr_since_pass") or [])
        changed = [p for p in changed_paths_since_pass() if p not in own_paths][:5] \
            or _changed_paths(top, cwd, sess.get("attr_files") or [])
        others = _other_sessions(top, cwd, changed, sid, tp)
        lines = ["sisi: the contract is NOT satisfied, but this session has not edited files since the "
                 "checks last passed (or since it started), so this turn may end. Do not report this work "
                 "as done; the result is recorded as UNVERIFIED. Relay this to the human.",
                 "Failing checks:\n" + failing_text]
        if changed:
            lines.append("Files changed in the tree that this session did not edit (likely another "
                         "session's work in progress): " + ", ".join(changed))
        if others:
            lines.append("The changed files appear in the transcript/session record of session(s): "
                         + ", ".join(others))
        else:
            lines.append("Files changed by another session are the likely cause; no other session "
                         "could be identified from the records available.")
        return ctx.allow("\n".join(lines))

    def other_tree_changed():
        """The tree moved since this session's last pass or its start (dirty-vs-HEAD is the
        fallback proxy when no start fingerprint was ever recorded for the session)."""
        if fp is not None:
            if sess.get("attr_pass_fp"):
                return fp != sess["attr_pass_fp"]
            if sess.get("baseline_fp") is not None:
                return fp != sess["baseline_fp"]
            if sess.get("last_fp") is not None:
                return fp != sess["last_fp"]
        return bool(_changed_paths(top, cwd, sess.get("attr_files") or []))

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
            own_before_pass = own_since_pass
            responsible_before_pass = own_responsible() if attr is not None else True
            other_before_pass = attr is not None and not responsible_before_pass and other_tree_changed()
            if attr is not None:
                sess["attr_pass_gen"] = int(sess.get("attr_gen", 0) or 0)
                sess["attr_pass_fp"] = fp
                sess["attr_since_pass"] = []
                try:
                    from . import watch
                    watch.save_pass_snapshot(sid, cwd)
                except Exception as e:
                    store.log_error("gate-watch-pass", e)
            if dfail:
                tails = "\n".join("- deep check %s [%s]:\n%s" % (i["id"], i["status"], "\n".join("    " + l for l in i["tail"].splitlines()[-15:]))
                                  for i in ds["failed"])
                if other_before_pass:
                    return other_allow(tails[:4000], c["id"] if c else None)
                return ctx.block("sisi: the fast checks pass, but the deep checks failed on the current tree "
                                 "(send-back {n}). Fix the work, then re-run them with `sisi verify --deep "
                                 "--background` (see `sisi verify --state`). Do not report this work as done.\n\n%s"
                                 % tails[:4000], c["id"], project, kind="deep")
            changed = fp is None or fp != sess.get("baseline_fp")
            if need_retro(changed if attr is None else bool(own_since_retro)):
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
        if attr is not None and not own_responsible() and other_tree_changed():
            return other_allow(V.failure_report(results), c["id"] if c else None)
        msg = ("sisi: the contract at %s is not satisfied (send-back {n}). Fix the work, then run "
               "`sisi verify` until it passes. Do not report this work as done.\n\n%s"
               % (path, V.failure_report(results)))
        try:
            from . import retro
            failing = " ".join("%s %s %s" % (r["id"], r.get("kind") or "", r.get("claim") or "")
                                for r in results if r["status"] in ("failed", "timeout"))
            block = retro.lessons_block(failing, "gate", session=sid)
            if block:
                msg += "\n\n" + block
        except Exception as e:
            store.log_error("gate-lessons", e)
        return ctx.block(msg, c["id"] if c else None, project)

    if not top:
        return "allow", None
    if sess.get("baseline") is None:
        sess.update(baseline=gitutil.measure(cwd), head=gitutil.head(cwd), started=sess.get("started") or store.now())
        sess["baseline_fp"] = fp
        if attr is not None:
            sess["attr_baseline_gen"] = int(sess.get("attr_gen", 0) or 0)
        store.save_session(sid, sess)
        return "allow", None
    if attr is not None and not _own_since("attr_baseline_gen") and not attr["unknown"]:
        return ctx.allow()  # this session edited nothing here: no retro, no growth send-back for others' work
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
        if need_retro(bool(sess.get("waiver_ns")) if attr is None else bool(own_since_retro)):
            from . import retro
            return ctx.block(retro.TEMPLATE, kind="retro")
        return ctx.allow()
    return ctx.block("sisi: this session has changed %d lines and %d files since its start and there is no "
                     "contract (send-back {n}). Write `.sisi/contract.json` (`sisi contract init` makes the "
                     "skeleton; give it at least one check with a real command), then run `sisi verify`. If "
                     "the change needs no checks, run `sisi contract waive \"<reason>\"` instead." % (dl, df))


def decide(payload):
    """The gate's answer: the contract/retro decision, then — only on an otherwise-clean stop —
    the rule-5 question check, which sends the agent back at most once per final message."""
    action, msg = _decide(payload)
    if action != "allow":
        return action, msg
    try:
        q = _question_sendback(payload)
    except Exception as e:  # the question check must never break the gate
        store.log_error("gate-question", e)
        q = None
    return q if q else (action, msg)


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
                if isinstance(x, dict) and x.get("type") == "tool_use" and x.get("name") in ("Bash", "Shell"):
                    inp = x.get("input") if isinstance(x.get("input"), dict) else {}
                    if _shell_may_write(inp.get("command")) is not False:
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
