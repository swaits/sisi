"""Request-time delivery: `sisi prompt` runs on the human's message (the tool's prompt-submission hook)
and injects the matching "what done means" recipe and lessons as added context, so the agent does not
have to remember to ask (`sisi done for`). Matching is the strict "likely to apply" test from
learning.delivery_text (learnings in earned scope, framed as information; no showing is
recorded as evidence); when nothing strictly matches, or the message is trivial, nothing is printed. Any
error exits 0 silently: a hook must never block or fail a turn.
"""
import json, os, sys

from . import learning as _L, store


def _stem(w):
    return _L._stem(w.lower())


def _word_cut(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"

MAX_CHARS = 2000  # hard cap on the injected context, in characters
RECIPE_MIN_SCORE = 22.0  # a structured kind/tag match in the new matcher; below it, no recipe
_TRIVIAL = {"yes", "no", "y", "n", "ok", "okay", "sure", "yep", "nope", "thanks", "thank you",
            "go ahead", "do it", "continue", "stop", "wait", "hi", "hello"}


_WORK_STEMS = {"fix", "chang", "add", "build", "updat", "remov", "implement", "writ", "creat",
               "refactor", "renam", "delet", "introduc", "migrat", "upgrad", "design", "develop",
               "ship", "publish", "tag", "releas", "mak", "set", "install", "convert", "speed"}
_QUESTION_START = {"should", "can", "could", "would", "is", "are", "do", "does", "did", "why", "what",
                   "how", "whether", "when", "where", "who", "which", "will", "shall", "may"}


def _is_question_without_work(t):
    """A question to the agent that names no work (no fix/build/change/...): the agent just answers."""
    low = " ".join(t.lower().split())
    first = low.split(" ", 1)[0].strip("¿?") if low else ""
    if not (low.endswith("?") or first in _QUESTION_START):
        return False
    from . import verifiers as V
    stems = {_stem(w) for w in V._words(low)}
    return not (stems & _WORK_STEMS)


def is_trivial(text):
    """A message no recipe or lesson can help with: empty, a slash command, a bare yes/no, or a short
    question. A wrong injection on every message is worse than none."""
    t = " ".join((text or "").split())
    if len(t) < 15:
        return True
    if t.startswith("/"):
        return True
    if t.lower().rstrip(".! ") in _TRIVIAL:
        return True
    words = t.split()
    if len(words) < 3:
        return True
    if t.endswith("?") and len(words) <= 7:  # a short question: the agent just answers it
        return True
    if _is_question_without_work(t):
        return True
    return False


def _best_recipe(query):
    """The best-matching recipe when the structured match is strong, else None."""
    from . import verifiers as V
    ranked = V.rank_recipes(query)
    if ranked and ranked[0][0] >= RECIPE_MIN_SCORE:
        return ranked[0][1]
    return None


def _done_means(recipe):
    """The recipe's must-be-true list in short form: its Done-means bullets, each cut at a word boundary."""
    from . import verifiers as V
    bullets = []
    for line in V._section(recipe["body"], "Done means").split("\n"):
        line = line.strip()
        if line.startswith("- "):
            bullets.append("- " + _word_cut(line[2:], 110))
    return bullets


def build_context(query, session=None):
    """The context to inject for one human request, or "" when nothing strictly matches.
    Learnings come only from learning.delivery_text (earned scope, framed as information);
    no showing is recorded, so nothing is promoted by being printed."""
    if is_trivial(query):
        return ""
    recipe = _best_recipe(query)
    lesson_text = _L.delivery_text(os.getcwd(), query).strip()
    lesson_lines = lesson_text.split("\n")[1:] if lesson_text else []
    if not recipe and not lesson_lines:
        return ""
    lines = []
    lines.append("sisi: for this request (from earlier agents' lessons and the recipe library; "
                 "information to weigh, not commands):")
    if recipe:
        lines.append("Done means — recipe `%s` (full text: `sisi done %s`):" % (recipe["id"], recipe["id"]))
        lines += _done_means(recipe)
    if lesson_lines:
        lines.append("Lessons likely to apply:")
        lines += lesson_lines
    text = "\n".join(lines)
    while len(text) > MAX_CHARS and lesson_lines:  # drop lesson lines before cutting the recipe
        lesson_lines.pop()
        lines = lines[:len(lines) - 1]
        text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = _word_cut(text, MAX_CHARS)
    return text


def meter_new_turn(session, cwd, query):
    """Every prompt the session receives starts the orchestration meter's turn again (and the first one may
    show the session is a worker). Never raises."""
    try:
        if session and query:
            from . import orchestration
            orchestration.new_turn(session, cwd, query)
    except Exception as e:
        store.log_error("prompt-meter", e)


def extract_prompt(payload):
    """The human's request text from a hook payload, across the tools' documented field names."""
    if not isinstance(payload, dict):
        return None
    for k in ("prompt", "user_prompt", "userPrompt", "input", "text", "message"):
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def main(args=()):
    """Claude Code shape: UserPromptSubmit JSON on stdin, additionalContext JSON on stdout.
    Other tools go through hookio.prompt_main. Positional text (or --plain) prints the raw context,
    for trying it by hand. Never raises, never blocks."""
    try:
        args = list(args)
        plain = "--plain" in args
        args = [a for a in args if a != "--plain"]
        query, session = None, None
        if args:
            query = " ".join(args)
            plain = True
        else:
            raw = store.read_stdin() if sys.stdin is not None and not sys.stdin.isatty() else ""
            try:
                payload = json.loads(raw or "{}")
            except ValueError:
                return 0
            if not isinstance(payload, dict):
                return 0
            query = extract_prompt(payload)
            session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
            cwd = payload.get("cwd")
            if isinstance(cwd, str) and os.path.isdir(cwd):
                os.chdir(cwd)
        if not query:
            return 0
        meter_new_turn(session, os.getcwd(), query)
        text = build_context(query, session=session)
        if not text:
            return 0
        if plain:
            sys.stdout.write(text + "\n")
        else:
            sys.stdout.write(json.dumps({"hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit", "additionalContext": text}}) + "\n")
    except Exception as e:  # fail open: a prompt hook must never fail a turn
        try:
            store.log_error("prompt", e)
        except Exception:
            pass
    return 0
