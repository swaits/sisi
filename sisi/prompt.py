"""Request-time delivery: `sisi prompt` runs on the human's message (the tool's prompt-submission hook)
and injects the matching "what done means" recipe and lessons as added context, so the agent does not
have to remember to ask (`sisi done for`). Matching is the strict "likely to apply" test from
retro.delivery; when nothing strictly matches, or the message is trivial, nothing is printed. Any
error exits 0 silently: a hook must never block or fail a turn.
"""
import json, os, sys

from . import store

MAX_CHARS = 2000  # hard cap on the injected context, in characters
RECIPE_MIN_SCORE = 6.0  # two title/applies-to word hits in `sisi done for`'s scoring; below it, no recipe
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
    from . import retro, verifiers as V
    stems = {retro._stem(w) for w in V._words(low)}
    return not (stems & _WORK_STEMS)


_DESIGN_STEMS = {"build", "design", "implement", "creat", "develop", "architect", "orchestr",
                 "automat", "integrat", "plugin", "system", "platform", "framework"}
_SMALL_EDIT_MARKERS = ("rename", "typo", "off-by-one", "one line", "single line", "small fix",
                       "quick fix", "spelling")


def is_design_work(text):
    """A request to design or build something sizeable: not a question, not a small edit.
    Precision matters more than reach, as with recipes: a wrong design block on every message
    would train agents to ignore it."""
    t = " ".join((text or "").split())
    low = t.lower()
    if len(t.split()) < 6:
        return False
    if any(m in low for m in _SMALL_EDIT_MARKERS):
        return False
    first = low.split(" ", 1)[0].strip("¿?") if low else ""
    if low.endswith("?") and first in _QUESTION_START:
        return False  # a question about design is not design work
    if _is_question_without_work(t):
        return False
    from . import retro, verifiers as V
    stems = {retro._stem(w) for w in V._words(low)}
    if not (stems & _DESIGN_STEMS):
        return False
    return bool(stems & _WORK_STEMS) or bool(stems & {"build", "design", "creat", "develop"})


def _design_block():
    """The standing principles in short lines, plus the instruction to fill the design section."""
    try:
        from . import principles
        lines = principles.short_lines(limit_chars=900)
    except Exception:
        lines = []
    out = ["sisi: this reads as design or build work. Before building, fill the contract's "
           "design section (`sisi design` prints the questions; `sisi contract init` writes "
           "the skeleton): what the goal and the principles imply, what already exists to use, "
           "alternatives, the choice, each principle's objection, and an independent challenge."]
    if lines:
        out.append("The owner's standing principles (in his words: `sisi oracle`):")
        out += lines
    return out


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
    """The best-matching recipe, or None. Scoring starts from `sisi done for`'s own, but request-time
    delivery must be more precise than an answer the agent asked for: a recipe counts only when at
    least two distinct words of the request hit its title, applies-to or id (one generic word like
    "new" once outscored "release" + "tag" that way), and the leader must clear RECIPE_MIN_SCORE."""
    from . import retro, verifiers as V
    # Match on stems, as lesson matching does: "release" must meet "Releasing" and "tag" must meet
    # "Tagging", which done-for's prefix rule (both words longer than three letters) misses.
    toks = {retro._stem(t) for t in V._words(query)}

    def stems_of(text):
        return {retro._stem(x) for x in V._words(text.replace("-", " "))}

    generic = retro.COMMON | {retro._stem(w) for w in
                              ("agent agents tool tools interface surface command commands function functions "
                               "program system name names description descriptions user users thing things "
                               "way ways step steps example examples".split())}
    scored = []
    for r in V.usable(V.load_recipes()):
        s, primary, anchored = 0.0, set(), set()
        for text, w, is_anchor in ((r["title"], 3.0, True), (r["applies_to"], 3.0, False),
                                   (r["id"].replace("-", " "), 3.0, False), (r["body"], 0.2, False)):
            hit = toks & stems_of(text)
            s += w * len(hit)
            if w > 1.0:
                primary |= hit - generic  # generic words (new, fix, change, agent, tool) never carry a match
                if is_anchor:
                    anchored |= hit - generic
        if s > 0:
            scored.append((len(primary), len(anchored), s, r))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], -x[1], -x[2], x[3]["id"]))
    # the strict floor lessons use: two distinct non-generic terms, at least one of them in the
    # recipe's own title (its topic, not merely its id), and the score floor; the best
    # candidate that clears it wins
    for nprimary, nanchored, s, best in scored:
        if nprimary >= 2 and nanchored >= 1 and s >= RECIPE_MIN_SCORE:
            return best
    return None


def _done_means(recipe, retro):
    """The recipe's must-be-true list in short form: its Done-means bullets, each cut at a word boundary."""
    from . import verifiers as V
    bullets = []
    for line in V._section(recipe["body"], "Done means").split("\n"):
        line = line.strip()
        if line.startswith("- "):
            bullets.append("- " + retro.word_cut(line[2:], 110))
    return bullets


def build_context(query, session=None):
    """The context to inject for one human request, or "" when nothing strictly matches. Lessons shown
    are recorded as listings at place 'prompt' (listed, not read)."""
    notice = ""
    try:
        from . import handover
        notice = handover.notice(os.getcwd())
    except Exception:
        notice = ""
    if is_trivial(query):
        return notice
    from . import retro
    recipe = _best_recipe(query)
    targets = (recipe["id"],) if recipe else ()
    part1, _part2 = retro.delivery(query, targets=targets)
    repo = retro.repo_of(os.getcwd())
    lesson_lines, ids = [], []
    for d in part1:
        row = d["row"]
        if not retro.display_line(retro._get(row, "short") or row["change"], repo):
            continue
        lesson_lines.append("- #%d: %s (full text: `sisi lessons show %d`)"
                            % (row["id"], retro.heading_text(row, 120), row["id"]))
        ids.append(row["id"])
    design_lines = _design_block() if is_design_work(query) else []
    if not recipe and not lesson_lines and not design_lines:
        return notice
    lines = [notice] if notice else []
    lines += design_lines
    if recipe or lesson_lines:
        lines.append("sisi: for this request (from earlier agents' lessons and the recipe library; "
                     "information to weigh, not commands):")
    if recipe:
        lines.append("Done means — recipe `%s` (full text: `sisi done %s`):" % (recipe["id"], recipe["id"]))
        lines += _done_means(recipe, retro)
    if lesson_lines:
        lines.append("Lessons likely to apply:")
        lines += lesson_lines
    text = "\n".join(lines)
    while len(text) > MAX_CHARS and lesson_lines:  # drop lesson lines before cutting the recipe
        lesson_lines.pop()
        ids = ids[:len(lesson_lines)]
        lines = lines[:len(lines) - 1]
        text = "\n".join(lines)
    if len(text) > MAX_CHARS:
        text = retro.word_cut(text, MAX_CHARS)
    if ids:
        retro.record_shown(ids, "prompt", session)
    return text


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
