"""Harvest: turn raw agent transcripts into a sqlite database in the state dir (harvest.db).

No model calls. Incremental: each file's size and mtime are remembered and an unchanged file is skipped;
a file that grew or changed is re-read whole and its rows replaced. Transcripts are streamed line by line
(in binary, with a cheap byte-level pre-filter so the multi-megabyte tool-result lines are never parsed).

Sources sit behind one interface (`Source`): `discover(home)` yields `FileRef`s and `parse(ref)` returns
`(session_dict, [message_dict])`. Only `ClaudeCodeSource` exists. A Muse JSONL or OpenCode sqlite source
would subclass `Source` and be added to `SOURCES`; nothing else in the pipeline knows about Claude Code.

WHAT COUNTS AS TEXT THE HUMAN TYPED (the rule, settled by inspecting real records)
A transcript `user` record is typed by the human only if ALL hold:
  1. the session is a main session (subagent transcripts have no human; their first user record is a
     brief written by the parent agent and is stored as `first_message` of a subagent session only);
  2. it is not a tool result (`toolUseResult` key / `tool_result` content blocks);
  3. it is not `isMeta` and not `isCompactSummary` (system reminders, hook output, skill expansions,
     peer/subagent hand-backs and compaction summaries are all flagged this way);
  4. its `origin` is absent or `{"kind": "human"}` (`task-notification`, `peer`, ... are machine events);
  5. after removing wrappers, text remains or an image was attached. Wrappers removed: `<pasted_content>`,
     `<t3_context>` and `<assistant_citations>` blocks, `[Image ...]`, `[File: ...]`, `[Terminal: ...]`
     and `[Assistant quote](...)` placeholders. Wrappers that make the whole record non-human are
     dropped entirely: `<task-notification>`, `<local-command-*>`, `<system-reminder>`,
     `<artifact-content-authored-by-others/>`, "This session is being continued", "Caveat:".
     A slash command (`<command-name>`) counts only through its `<command-args>` text, if any.
     `[Request interrupted by user...]` is counted as an interruption, not as a message.
Messages the human typed while the agent was working are not `user` records: Claude Code stores them as
`attachment` records of type `queued_command` (commandMode "prompt"); they are read with the same rules
and de-duplicated against a user record with the same text within 30 s.

WHAT COUNTS AS MACHINE-WRITTEN (first message of a main session; the reason is stored)
Any of: the first typed message is absent; entrypoint sdk-cli (T3's auxiliary calls for titles and branch
names); an opening such as "You are a/an ...", "Act as ...", "You're a ..."; worker vocabulary ("do not
delegate", "you are a worker", "Done means", "# Constraints", "what to send back", "act as the ... sub-agent");
typed text over 3,500 chars; 3+ markdown headings in over 1,500 chars; a known tool-generated prompt ("A
process crashed on this ... machine", "Generate a title that will help ..."). A human merely mentioning
sub-agents is not machine-written.
Pasted content does not count towards length (it is a human attachment). The heuristic errs towards
calling things machine-written: a false "machine" only removes a session from the human task set.
"""
import json, os, re, sys, time
from collections import namedtuple

from . import paths

FileRef = namedtuple("FileRef", "path kind project parent_id agent_id meta_path")

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, source TEXT, session_id TEXT);
CREATE TABLE IF NOT EXISTS sessions(
  id TEXT PRIMARY KEY, source TEXT, path TEXT, kind TEXT, parent_id TEXT, agent_id TEXT, project TEXT, cwd TEXT,
  branch TEXT, entrypoint TEXT, t0 REAL, t1 REAL, first_ts TEXT, last_ts TEXT, models TEXT, user_turns INTEGER,
  first_message TEXT, machine INTEGER, machine_reason TEXT, n_corrections INTEGER, n_interrupts INTEGER,
  n_ask INTEGER, n_question_turns INTEGER, n_completion_claims INTEGER, n_premature_done INTEGER,
  last_claims_done INTEGER, ran_commit INTEGER, tools TEXT, used_verify INTEGER, used_contract INTEGER, meta TEXT);
CREATE INDEX IF NOT EXISTS sessions_path ON sessions(path);
CREATE INDEX IF NOT EXISTS sessions_parent ON sessions(parent_id);
CREATE TABLE IF NOT EXISTS user_msgs(
  session_id TEXT, idx INTEGER, ts TEXT, t REAL, text TEXT, correction INTEGER, after_completion INTEGER,
  pasted_chars INTEGER, PRIMARY KEY(session_id, idx));
CREATE TABLE IF NOT EXISTS groundtruth(
  session_id TEXT PRIMARY KEY, repo_root TEXT, repo_how TEXT, vcs TEXT, start_commit TEXT, start_kind TEXT,
  start_note TEXT, commits TEXT, n_commits INTEGER, files TEXT, test_cmd TEXT, test_how TEXT,
  overlap_any INTEGER, overlap_writers INTEGER, siblings TEXT, t1 REAL, computed_at REAL);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, kind TEXT, session_id TEXT, parent_id TEXT, grade TEXT, reasons TEXT, split TEXT,
  repo_root TEXT, start_commit TEXT, start_kind TEXT, test_cmd TEXT, request TEXT, ledger_id TEXT,
  ledger_outcome TEXT, match_confidence TEXT, match_note TEXT, created_at REAL, updated_at REAL);
"""


def db_path():
    return paths.state_file("harvest.db")


def connect(path=None):
    path = path or db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    import sqlite3  # lazy: the end-of-turn gate imports this module for typed_text and must stay fast
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------- small helpers

_day_cache = {}


def epoch(ts):
    """ISO 8601 'YYYY-MM-DDTHH:MM:SS[.fff]Z' (UTC) to epoch seconds; None when unparseable."""
    try:
        day = ts[:10]
        base = _day_cache.get(day)
        if base is None:
            import datetime
            base = (datetime.date(int(day[:4]), int(day[5:7]), int(day[8:10])).toordinal() - 719163) * 86400
            _day_cache[day] = base
        t = base + int(ts[11:13]) * 3600 + int(ts[14:16]) * 60 + int(ts[17:19])
        if len(ts) > 20 and ts[19] == ".":
            frac = re.match(r"\.(\d+)", ts[19:])
            if frac:
                t += float("0." + frac.group(1))
        return float(t)
    except (TypeError, ValueError, IndexError):
        return None


COMMIT_RE = re.compile(r"(?:^|[\s;&|(])(?:git(?:\s+-C\s+\S+)?\s+commit\b|jj\s+(?:commit|describe|squash)\b)")
SISI_VERIFY_RE = re.compile(r"(?:^|[\s/;&|(])sisi\s+verify\b")
SISI_CONTRACT_RE = re.compile(r"(?:^|[\s/;&|(])sisi\s+contract\b")

_WRAP_BLOCKS = [re.compile(r"<pasted_content\b[^>]*>.*?</pasted_content>", re.S),
                re.compile(r"<t3_context\b[^>]*>.*?</t3_context>", re.S),
                re.compile(r"<assistant_citations>.*?</assistant_citations>", re.S)]
_PLACEHOLDERS = [re.compile(r"\[Image[^\]]*\]"), re.compile(r"\[File:[^\]]*\]"), re.compile(r"\[Terminal:[^\]]*\]"),
                 re.compile(r"\[Assistant quote\]\([^)]*\)"), re.compile(r"\[assistant-quote-\d+\]")]
_NOT_HUMAN_PREFIX = ("<task-notification", "<local-command-", "<system-reminder", "<artifact-content-authored-by-others",
                     "This session is being continued", "Caveat:", "[Usage limit reached", "[Earlier usage",
                     "<agent-message", "<bash-input", "<bash-stdout", "<user-prompt-submit-hook")
_CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def typed_text(d, queued_prompt=None):
    """Apply the typed-by-the-human rule to one user record (or a queued_command prompt).
    Returns (text, pasted_chars, interrupted); text is None when the record is not user evidence."""
    if queued_prompt is None:
        if d.get("type") != "user" or d.get("isMeta") or d.get("isCompactSummary") or "toolUseResult" in d:
            return None, 0, False
        origin = d.get("origin")
        content = (d.get("message") or {}).get("content")
    else:
        origin = d.get("origin")
        content = queued_prompt
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None, 0, False
    has_image = False
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_result":
                return None, 0, False
            if b.get("type") == "image":
                has_image = True
            elif b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
        content = "\n".join(parts)
    if not isinstance(content, str):
        return None, 0, False
    s = content.strip()
    if s.startswith("[Request interrupted by user"):
        return None, 0, True
    if s.startswith(_NOT_HUMAN_PREFIX):
        return None, 0, False
    if s.startswith(("<command-name", "<command-message")):
        m = _CMD_ARGS.search(s)
        s = (m.group(1) if m else "").strip()
        if not s:
            return None, 0, False
    pasted = 0
    for rx in _WRAP_BLOCKS:
        def _cut(m):
            nonlocal pasted
            pasted += len(m.group(0))
            return ""
        s = rx.sub(_cut, s)
    for rx in _PLACEHOLDERS:
        if rx.search(s):
            has_image = has_image or "Image" in rx.pattern
            s = rx.sub("", s)
    s = s.strip()
    if not s and not (has_image or pasted):
        return None, 0, False
    return s, pasted, False


# ---------------------------------------------------------------- heuristics over text

_QUESTION_TAIL = re.compile(r"\?[\s\"'`*_)\]]*$")
_CLAIM_RE = re.compile(r"\b(all (the )?(tests? )?(pass|passing|passed|green)|(is|are|now|it'?s) (all )?(done|complete|completed|working|fixed|ready|green)|"
                       r"(i'?ve |i have |have )?(implemented|completed|finished|fixed|resolved)\b|everything (is|works)|"
                       r"done[.!]|ready (for|to)\b|successfully)", re.I)
_CORRECTION_ANYWHERE = re.compile(r"(doesn'?t work|does not work|not working|still (broken|fails?|failing|wrong|not|happening|see|doesn'?t)|"
                                  r"that'?s (not|wrong|incorrect)|that is (not|wrong|incorrect)|you (missed|forgot|broke|ignored|didn'?t|did not|never)|"
                                  r"not what i|i (said|asked you|told you|didn'?t ask|meant)|revert (that|it|this)|undo (that|it|this)|"
                                  r"why did you|you should have|you shouldn'?t have|this is (still )?(broken|wrong)|it'?s (still )?(broken|wrong))", re.I)
_CORRECTION_START = re.compile(r"^\s*(no[,.!:\s]|no$|nope|wrong|not (quite|what|right)|incorrect|actually[,\s]|wait[,.\s]|stop[,.!\s]|don'?t |please don'?t|"
                               r"that'?s not|this isn'?t|it isn'?t)", re.I)


def is_correction(text):
    if not text or len(text) > 1500:
        return False
    return bool(_CORRECTION_START.search(text) or _CORRECTION_ANYWHERE.search(text))


_MACHINE_OPEN = re.compile(r"^\s*(you are (a|an|the|working|acting|being)\b|act as\b|you'?re (a|an) |you will (act|be|act as)|"
                           r"your (role|task|job) is\b|<role>|# (role|goal|task|mission)\b)", re.I)
_MACHINE_WORDS = re.compile(r"(do not delegate|you are a worker|you are an? (implementer|reviewer|worker)\b|"
                            r"\bdone means\b|# constraints|## constraints|what to send back|act as the [\w -]{0,40}sub-?agent)", re.I)
_TOOL_GENERATED = re.compile(r"^\s*(a process crashed on this|<skill-|base directory for this skill|you generate concise|"
                             r"generate a title that will help)", re.I)


def machine_reason(text, origin_kind=None, entrypoint=None):
    """(is_machine, reason) for the first typed message of a main session. See module docstring."""
    reasons = []
    if text is None:
        return True, "no-typed-user-message"
    if origin_kind not in (None, "human"):
        reasons.append("origin-" + str(origin_kind))
    if entrypoint == "sdk-cli":
        reasons.append("entrypoint-sdk-cli")  # auxiliary SDK calls (thread titles, branch names), never a request
    if _MACHINE_OPEN.search(text):
        reasons.append("role-opening")
    if _MACHINE_WORDS.search(text):
        reasons.append("brief-vocabulary")
    if _TOOL_GENERATED.search(text):
        reasons.append("tool-generated")
    if len(text) > 3500:
        reasons.append("long-%d" % len(text))
    elif len(text) > 1500 and len(re.findall(r"^#{1,4} ", text, re.M)) >= 3:
        reasons.append("structured-headings")
    return bool(reasons), ";".join(reasons)


# ---------------------------------------------------------------- source interface

class Source:
    name = "?"

    def discover(self, home):
        raise NotImplementedError

    def parse(self, ref):
        raise NotImplementedError


def parse_meta(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


class ClaudeCodeSource(Source):
    name = "claude-code"

    def discover(self, home):
        root = os.path.join(home, ".claude", "projects")
        try:
            projects = sorted(os.listdir(root))
        except OSError:
            return
        for proj in projects:
            pdir = os.path.join(root, proj)
            try:
                entries = sorted(os.listdir(pdir))
            except OSError:
                continue
            for e in entries:
                p = os.path.join(pdir, e)
                if e.endswith(".jsonl") and os.path.isfile(p):
                    yield FileRef(p, "main", proj, None, None, None)
                elif os.path.isdir(p):
                    sub = os.path.join(p, "subagents")
                    for dirpath, dirs, names in os.walk(sub):  # workflow subagents nest under subagents/workflows/wf_*/
                        dirs.sort()
                        for n in sorted(names):
                            if n.startswith("agent-") and n.endswith(".jsonl"):
                                yield FileRef(os.path.join(dirpath, n), "subagent", proj, e, n[6:-6],
                                              os.path.join(dirpath, n[:-6] + ".meta.json"))

    def parse(self, ref):
        return parse_transcript(ref)


SOURCES = {"claude-code": ClaudeCodeSource()}


# ---------------------------------------------------------------- the transcript parser

def _sub_id(ref):
    """Subagent session id: agent id qualified by parent (and workflow dir), since agent ids can recur."""
    parts = os.path.dirname(ref.path).split(os.sep)
    wf = parts[-1] if "workflows" in parts else ""
    return ".".join(x for x in ((ref.parent_id or "")[:8], wf[3:11] if wf else "", ref.agent_id) if x)


def parse_transcript(ref):
    """Stream one Claude Code transcript. Never raises on malformed lines. Returns (session, messages)."""
    main = ref.kind == "main"
    S = dict(source="claude-code", path=ref.path, kind=ref.kind, parent_id=ref.parent_id, agent_id=ref.agent_id,
             project=ref.project, cwd=None, branch=None, entrypoint=None, t0=None, t1=None, first_ts=None, last_ts=None,
             models={}, user_turns=0, first_message=None, machine=0, machine_reason="", n_corrections=0,
             n_interrupts=0, n_ask=0, n_question_turns=0, n_completion_claims=0, n_premature_done=0,
             last_claims_done=0, ran_commit=0, tools={}, used_verify=0, used_contract=0, meta={})
    S["id"] = os.path.basename(ref.path)[:-6] if main else _sub_id(ref)
    msgs = []
    first_origin = None
    first_user_seen = False
    last_asst = None          # (has_tool, last_text) of the latest assistant record with content
    prev_claim = False
    recent = []               # (text, t) of recent typed messages, for queued_command de-duplication
    sid_from_records = None

    def close_segment():
        """The assistant turn before a typed message ended; classify it."""
        nonlocal prev_claim
        has_tool, text = last_asst if last_asst else (True, "")
        claim = False
        if not has_tool and text:
            if _QUESTION_TAIL.search(text.rstrip()):
                S["n_question_turns"] += 1
            elif _CLAIM_RE.search(text[-700:]):
                claim = True
                S["n_completion_claims"] += 1
        prev_claim = claim

    def note_ts(d, line):
        ts = d.get("timestamp") if d else None
        if isinstance(ts, str):
            t = epoch(ts)
            if t is not None:
                if S["t0"] is None or t < S["t0"]:
                    S["t0"], S["first_ts"] = t, ts
                if S["t1"] is None or t > S["t1"]:
                    S["t1"], S["last_ts"] = t, ts

    def add_message(text, pasted, ts, origin_kind, entrypoint, queued=False):
        nonlocal last_asst, first_origin
        t = epoch(ts) if isinstance(ts, str) else None
        for (rt, rtt) in recent[-4:]:
            if rt == text and t is not None and rtt is not None and abs(rtt - t) < 30:
                return
        recent.append((text, t))
        del recent[:-6]
        idx = S["user_turns"]
        close_segment()
        corr = 0
        if idx > 0 and is_correction(text):
            corr = 1
            S["n_corrections"] += 1
            if prev_claim:
                S["n_premature_done"] += 1
        msgs.append(dict(idx=idx, ts=ts, t=t, text=text if idx == 0 else text[:20000], correction=corr,
                         after_completion=1 if prev_claim else 0, pasted_chars=pasted))
        S["user_turns"] += 1
        if idx == 0:
            S["first_message"] = text
            first_origin = origin_kind
        last_asst = None

    try:
        f = open(ref.path, "rb")
    except OSError:
        S["meta"] = {"error": "unreadable"}
        return S, msgs
    with f:
        for raw in f:
            try:
                if not raw.startswith(b'{"parentUuid"'):
                    # queue-operation, api-request(-blob), last-prompt, ai-title ... carry nothing we use
                    continue
                is_att = b'"type":"attachment"' in raw
                if is_att and b'"queued_command"' not in raw:
                    continue
                if b'"toolUseResult"' in raw and not is_att:
                    i = raw.find(b'"timestamp":"')
                    if i >= 0:
                        note_ts({"timestamp": raw[i + 13:i + 37].split(b'"')[0].decode("ascii", "replace")}, None)
                    continue
                d = json.loads(raw)
                if not isinstance(d, dict):
                    continue
                note_ts(d, raw)
                if S["cwd"] is None and isinstance(d.get("cwd"), str):
                    S["cwd"] = d["cwd"]
                if S["branch"] is None and isinstance(d.get("gitBranch"), str):
                    S["branch"] = d["gitBranch"]
                if S["entrypoint"] is None and isinstance(d.get("entrypoint"), str):
                    S["entrypoint"] = d["entrypoint"]
                if main and sid_from_records is None and isinstance(d.get("sessionId"), str):
                    sid_from_records = d["sessionId"]
                typ = d.get("type")
                if typ == "assistant":
                    m = d.get("message") or {}
                    model = m.get("model")
                    if isinstance(model, str) and not model.startswith("<"):
                        S["models"][model] = S["models"].get(model, 0) + 1
                    content = m.get("content")
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    has_tool, text = False, None
                    for b in content if isinstance(content, list) else ():
                        if not isinstance(b, dict):
                            continue
                        bt = b.get("type")
                        if bt == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                            text = b["text"]
                        elif bt == "tool_use":
                            has_tool = True
                            name = b.get("name") or "?"
                            S["tools"][name] = S["tools"].get(name, 0) + 1
                            if name == "AskUserQuestion":
                                S["n_ask"] += 1
                            inp = b.get("input")
                            cmd = inp.get("command") if isinstance(inp, dict) else None
                            if name == "Bash" and isinstance(cmd, str):
                                if COMMIT_RE.search(cmd):
                                    S["ran_commit"] = 1
                                if SISI_VERIFY_RE.search(cmd):
                                    S["used_verify"] = 1
                                if SISI_CONTRACT_RE.search(cmd):
                                    S["used_contract"] = 1
                    if has_tool or text is not None:
                        last_asst = (has_tool, text or "")
                elif typ == "user":
                    if not main:
                        if not first_user_seen and not d.get("isMeta"):
                            first_user_seen = True
                            c = (d.get("message") or {}).get("content")
                            if isinstance(c, list):
                                c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                            S["first_message"] = c if isinstance(c, str) else None
                        continue
                    text, pasted, interrupted = typed_text(d)
                    if interrupted:
                        S["n_interrupts"] += 1
                    elif text is not None:
                        o = d.get("origin")
                        add_message(text, pasted, d.get("timestamp"), o.get("kind") if isinstance(o, dict) else None, d.get("entrypoint"))
                elif typ == "attachment" and main:
                    a = d.get("attachment") or {}
                    if a.get("type") == "queued_command" and a.get("commandMode") == "prompt" and not a.get("isMeta"):
                        text, pasted, interrupted = typed_text(a, queued_prompt=a.get("prompt"))
                        if text is not None:
                            o = a.get("origin")
                            add_message(text, pasted, a.get("timestamp") or d.get("timestamp"),
                                        o.get("kind") if isinstance(o, dict) else None, d.get("entrypoint"), queued=True)
            except Exception:  # malformed or surprising line: skip it, never abort the harvest
                continue
    close_segment()
    S["last_claims_done"] = 1 if prev_claim else 0
    if main:
        if sid_from_records and sid_from_records != S["id"]:
            S["meta"]["session_id_in_records"] = sid_from_records
        S["machine"], S["machine_reason"] = (lambda r: (int(r[0]), r[1]))(
            machine_reason(S["first_message"], first_origin, S["entrypoint"]))
    else:
        S["machine"], S["machine_reason"] = 1, "subagent"
        S["meta"] = parse_meta(ref.meta_path) if ref.meta_path else {}
    return S, msgs


# ---------------------------------------------------------------- persistence

def _store(con, S, msgs):
    con.execute("DELETE FROM sessions WHERE path=?", (S["path"],))
    con.execute("DELETE FROM user_msgs WHERE session_id=?", (S["id"],))
    cols = ["id", "source", "path", "kind", "parent_id", "agent_id", "project", "cwd", "branch", "entrypoint", "t0", "t1",
            "first_ts", "last_ts", "models", "user_turns", "first_message", "machine", "machine_reason", "n_corrections",
            "n_interrupts", "n_ask", "n_question_turns", "n_completion_claims", "n_premature_done", "last_claims_done",
            "ran_commit", "tools", "used_verify", "used_contract", "meta"]
    row = [json.dumps(S[c], sort_keys=True) if c in ("models", "tools", "meta") else S[c] for c in cols]
    con.execute("INSERT OR REPLACE INTO sessions(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), row)
    con.executemany("INSERT OR REPLACE INTO user_msgs VALUES(?,?,?,?,?,?,?,?)",
                    [(S["id"], m["idx"], m["ts"], m["t"], m["text"], m["correction"], m["after_completion"], m["pasted_chars"])
                     for m in msgs])


def _work(ref):
    try:
        return ref, parse_transcript(ref), None
    except Exception as e:  # pragma: no cover - parse_transcript is defensive already
        return ref, None, repr(e)


def run(home=None, workers=None, source_names=None, progress=None, con=None):
    """Incremental harvest. Returns stats: files seen, parsed, skipped, errors, sessions stored."""
    home = home or paths.home()
    own = con is None
    con = con or connect()
    known = {r["path"]: (r["size"], r["mtime_ns"]) for r in con.execute("SELECT path,size,mtime_ns FROM files")}
    todo, seen, skipped = [], set(), 0
    for name, src in SOURCES.items():
        if source_names and name not in source_names:
            continue
        for ref in src.discover(home):
            seen.add(ref.path)
            try:
                st = os.stat(ref.path)
            except OSError:
                continue
            if known.get(ref.path) == (st.st_size, st.st_mtime_ns):
                skipped += 1
                continue
            todo.append((ref, st, name))
    stats = {"seen": len(seen), "skipped": skipped, "parsed": 0, "errors": 0, "removed": 0}
    # files that disappeared: drop their rows
    for p in set(known) - seen:
        con.execute("DELETE FROM user_msgs WHERE session_id IN (SELECT id FROM sessions WHERE path=?)", (p,))
        con.execute("DELETE FROM sessions WHERE path=?", (p,))
        con.execute("DELETE FROM files WHERE path=?", (p,))
        stats["removed"] += 1
    todo.sort(key=lambda x: -x[1].st_size)  # big files first keeps pool workers busy
    byref = {t[0].path: t for t in todo}
    workers = workers if workers is not None else min(8, os.cpu_count() or 2)
    if workers > 1 and len(todo) > 8:
        from concurrent.futures import ProcessPoolExecutor
        ex = ProcessPoolExecutor(max_workers=workers)
        results = ex.map(_work, [t[0] for t in todo], chunksize=4)
    else:
        ex = None
        results = map(_work, [t[0] for t in todo])
    try:
        for n, (ref, parsed, err) in enumerate(results, 1):
            _, st, name = byref[ref.path]
            if err or parsed is None:
                stats["errors"] += 1
                continue
            S, msgs = parsed
            _store(con, S, msgs)
            con.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)", (ref.path, st.st_size, st.st_mtime_ns, name, S["id"]))
            stats["parsed"] += 1
            if n % 50 == 0:
                con.commit()
                if progress:
                    progress("harvest: %d/%d files" % (n, len(todo)))
    finally:
        if ex:
            ex.shutdown()
    con.commit()
    stats["sessions"] = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    if own:
        con.close()
    return stats
