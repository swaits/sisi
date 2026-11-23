"""Which edits were this session's own. The gate reads this, never another session's work.

Attribution reads this session's own transcript (Claude-Code-shaped JSONL: assistant records whose
message.content holds tool_use blocks). Only bytes after the per-session offset stored in the session
record are read, so a long transcript costs only its new tail; subagent transcripts found under
<transcript-without-.jsonl>/subagents/** are read the same way and count as this session's edits.
Edit/Write/MultiEdit/NotebookEdit (and any tool whose name says it writes) count, with the file paths
in their input. Shell commands are measured by the before/after hooks (sisi/watch.py) where those are
installed; where they are not, a shell command counts when it plausibly writes: a redirect, tee/dd-of,
an in-place editor, git apply/checkout/restore/reset/clean/mv/rm, patch, cp/mv/rm/touch/mkdir, or any
program that is not on the provably read-only list (test runners and interpreters therefore count:
they can write).
Known blind spots: a read-only-looking command that writes through indirection sisi cannot see, a
daemon, a tool whose transcript is not Claude-Code JSONL, and writes made between the last complete
transcript line and a crash. A missing or unreadable transcript, a corrupt line, or a shell command
that cannot be tokenised is treated as an edit by this session (fail strict, never fail open here);
so is an unread tail over 64 MB, which is skipped rather than scanned inside the gate's time budget.
"""
import json, os, re, shlex

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


def shell_may_write(command):
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


def parse_chunk(data, measured=False):
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
        e, fl, w, corrupt, consumed, sh = parse_chunk(data, measured=bool(sess.get("attr_measured")))
        edits, files, writing = e, fl, w
        unknown = unknown or corrupt > 0
        offset += consumed
    if store_key == "sub":
        offsets[path] = offset
    else:
        sess["attr_offset"] = offset
    return edits, files, writing, unknown, sh


def subagent_transcripts(tp):
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


def update(sess, tp):
    """Refresh this session's edit count from its own (and its native subagents') transcripts.

    Returns {"gen", "writing", "unknown", "edits", "files", "shell_edits"} or None when no transcript
    path is known at all (the caller then falls back to comparing the tree with its last settled
    state). Fails towards edited: `unknown` is true whenever the transcript cannot be trusted."""
    if not isinstance(tp, str) or not tp:
        return None
    if sess.get("attr_tp") != tp:
        sess.update(attr_tp=tp, attr_offset=0, attr_gen=0, attr_writing=False, attr_files=[], attr_sub_offsets={})
    sess.setdefault("attr_gen", 0)
    unknown = False
    total, all_files, shell_total = 0, [], 0
    for key, path in [("main", tp)] + [("sub", s) for s in subagent_transcripts(tp)]:
        e, fl, w, unk, sh = _scan_one(sess, key, path)
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


def observed_edits(transcript):
    """(edited, files, start_ts) from a subagent's own transcript: did it write, which files did its
    edit tools name, and when did it start (sisi's timestamp format, or None). A shell command that
    may write counts as an edit with no known file."""
    edited, files, start = False, [], None
    with open(os.path.expanduser(transcript), encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if start is None and isinstance(d.get("timestamp"), str) and len(d["timestamp"]) >= 19:
                start = d["timestamp"][:19] + "Z"
            content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
            for x in content if isinstance(content, list) else []:
                if not (isinstance(x, dict) and x.get("type") == "tool_use"):
                    continue
                inp = x.get("input") if isinstance(x.get("input"), dict) else {}
                if x.get("name") in EDIT_TOOLS:
                    edited = True
                    files += [f for f in _input_files(inp) if f not in files]
                elif x.get("name") in ("Bash", "Shell") and shell_may_write(inp.get("command")) is not False:
                    edited = True
    return edited, files[:100], start
