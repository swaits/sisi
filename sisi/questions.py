"""Rule 5 at the end of a turn: a reply that ends by asking the human a question must have asked it
through the tool's question dialog. Sent back at most once per final message, never a subagent."""
import hashlib, json, os, re

from . import store


def _session_key(payload, cwd):
    sid = payload.get("session_id")
    return sid if isinstance(sid, str) and sid else "cwd-" + hashlib.sha1(cwd.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- rule 1 (own the outcome): ask through the dialog
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


def sendback(payload):
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
                     "(The rule in full: `sisi rule own-the-outcome`.)" % dialogs[0])
