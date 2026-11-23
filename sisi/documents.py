"""Whole-document edits: the things agents read are documents, and a learning round ends by
rewriting them as documents -- not by appending one more dated bullet.

Documents: the rulebook (doc `rulebook`), each recipe (`recipe:<id>`) and each technique entry
(`verifier:<id>`). A folded lesson ends up as part of the document's own text, in the section
where it belongs. The personal version of a recipe or technique lives in the overlay and
shadows the product's; the overlay records the product text's hash it was derived from
(`overlay.bases()`), and when the product later changes the next brief lists the document as
needing a re-merge -- never silently keeping a stale copy, never silently dropping additions.

Nothing may be lost: a rewrite in a cycle file gives, for every lesson folded into the
document, the exact fragment of the new text that carries it (or that it moved, merged, or was
retired under the usual retirement rule). The trace map lives beside the document in
`overlay/traces/`, never in the text agents load. `sisi lessons show ID`, `sisi rule N` and
`sisi done ID --trace` print where a lesson lives.

Structure is checked mechanically (see `structure_problems`): budgets, headings and Why,
the library lint, the house width after wrapping, run-on bullets, and dated journal bullets.
"""
import json, os, re, tempfile, textwrap

from . import overlay, paths

EDITORIAL_STANDARD = [
    "one instruction per bullet or sentence;",
    "most important and most often violated first;",
    "related instructions grouped under one heading;",
    "no duplicates or near-duplicates;",
    "imperative, concrete, plain words;",
    "each rule keeps its reason (its Why);",
    "exceptions next to the instruction they qualify;",
    "nothing that is history or narrative (that lives in the lesson's own record).",
]

DEFAULT_REVIEW_ROUNDS = 10   # a document with no whole-document review for this many rounds is listed
DEFAULT_MAX_BULLET_CHARS = 650
DATED_BULLET = re.compile(r"^\s*[-*]\s+\d{4}-\d{2}-\d{2}\s*:")
MORE_LINE = re.compile(r"^More: `sisi rule \d+`.*$")


def _cfg(key, default):
    try:
        v = (paths.personal_config().get("cycle") or {}).get(key)
        return int(v) if v is not None else default
    except Exception:
        return default


def review_every_rounds():
    return _cfg("review_every_rounds", DEFAULT_REVIEW_ROUNDS)


def max_bullet_chars():
    return _cfg("max_bullet_chars", DEFAULT_MAX_BULLET_CHARS)


def doc_key(kind, id):
    if kind == "rulebook":
        return "rulebook"
    if kind == "oracle":
        return "oracle"
    return "%s:%s" % (kind, id)


def parse_doc_key(key):
    if key == "rulebook":
        return "rulebook", "rulebook"
    if key in ("oracle", "oracle:oracle"):
        return "oracle", "oracle"
    if isinstance(key, str) and ":" in key:
        kind, _, id = key.partition(":")
        if kind in ("recipe", "verifier") and id:
            return kind, id
    return None, None


# ---- trace maps and review bookkeeping (overlay/traces/) --------------------
def _trace_rel(kind, id):
    return "traces/%s.json" % doc_key(kind, id).replace(":", "-")


def load_trace(kind, id):
    try:
        with open(paths.overlay_dir(_trace_rel(kind, id)), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def trace_entries(kind, id):
    e = load_trace(kind, id).get("entries")
    return e if isinstance(e, dict) else {}


def all_traces():
    """{doc_key: entries} for every trace map on disk."""
    out = {}
    d = paths.overlay_dir("traces")
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json") or n == "reviews.json":
            continue
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                rec = json.load(f)
            if isinstance(rec, dict) and rec.get("doc"):
                out[rec["doc"]] = rec.get("entries") or {}
        except (OSError, ValueError):
            continue
    return out


def traces_for_lesson(lesson_id):
    """[(doc_key, entry)] -- every trace map that says where this lesson lives."""
    out = []
    for key, entries in sorted(all_traces().items()):
        e = entries.get(str(lesson_id))
        if isinstance(e, dict):
            out.append((key, e))
    return out


def load_reviews():
    try:
        with open(paths.overlay_dir("traces", "reviews.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_reviews(reviews):
    overlay._write("traces/reviews.json", json.dumps(reviews, indent=1, sort_keys=True) + "\n")


def next_round_number():
    from . import cycle
    return len(cycle.cycle_records()) + 1


# ---- what a document currently says, and which lessons are folded into it ----
def effective_text(kind, id):
    if kind == "rulebook":
        return overlay.render()
    if kind == "oracle":
        from . import principles
        return principles.oracle_text()
    from . import verifiers as V
    entries = V.load_recipes() if kind == "recipe" else V.load_verifiers()
    for e in entries:
        if e["id"] == id:
            try:
                with open(e["path"], encoding="utf-8") as f:
                    return f.read()
            except OSError:
                return ""
    return ""


def _notes_lesson_ids(entry_id):
    from . import retro
    ids = []
    try:
        with open(os.path.join(paths.notes_dir(), entry_id + ".md"), encoding="utf-8") as f:
            for line in f:
                p = retro._parse_bullet(line)
                if p:
                    ids.append(p[2])
    except OSError:
        pass
    return ids


def folded_lesson_ids(con, kind, id):
    """Lessons folded into this document: by the lessons table, by its field-note bullets,
    and by an existing trace map. Superseded lessons are history and do not count."""
    ids = set()
    try:
        for r in con.execute("SELECT id, folded_into, status FROM lessons"):
            if r[2] == "superseded":
                continue
            targets = [t.strip() for t in str(r[1] or "").split(",") if t.strip()]
            if kind == "rulebook":
                hit = any(t.startswith("rule:") or t == "rulebook" for t in targets)
            else:
                hit = id in targets
            if hit:
                ids.add(r[0])
    except Exception:
        pass
    if kind != "rulebook":
        ids.update(_notes_lesson_ids(id))
    for k in trace_entries(kind, id):
        try:
            ids.add(int(k))
        except ValueError:
            pass
    key = doc_key(kind, id)
    for _src, entries in all_traces().items():
        for lid_s, t in entries.items():
            if isinstance(t, dict) and t.get("disposition") == "moved" and t.get("to") == key:
                try:
                    ids.add(int(lid_s))
                except ValueError:
                    pass
    return sorted(ids)


def _personal_exists(kind, id):
    return bool(overlay._overlay_entry_paths(kind, id))


def _stale_reason(kind, id):
    if kind == "rulebook" or not _personal_exists(kind, id):
        return None
    cur = overlay.base_hash(kind, id)
    if cur is None:
        return None  # a personal addition: there is no product text to drift from
    recorded = overlay.bases().get("%s:%s" % (kind, id))
    if recorded != cur:
        return ("the product text changed since the personal copy was made: needs a re-merge "
                "(keep the personal additions, take in the product's changes)")
    return None


def required_documents(con):
    """Documents the next round must rewrite or mark reviewed: field notes not yet integrated,
    a stale personal copy, or no whole-document review for the configured number of rounds.
    Returns [{doc, kind, id, reasons, lessons}] -- lessons are the unintegrated ones."""
    from . import cycle, verifiers as V
    reviews = load_reviews()
    rounds = len(cycle.cycle_records())
    every = review_every_rounds()
    cands = [("rulebook", "rulebook"), ("oracle", "oracle")]
    cands += [("recipe", e["id"]) for e in V.load_recipes() if e["header"]]
    cands += [("verifier", e["id"]) for e in V.load_verifiers() if e["header"]]
    out = []
    for kind, id in cands:
        key = doc_key(kind, id)
        if kind == "oracle":
            from . import principles as _pr
            recs = _pr.statements()
            if not recs:
                continue
            file_text = _pr._oracle_file_text() or ""
            entries = trace_entries(kind, id)
            traced_texts = {e.get("statement") for e in entries.values() if isinstance(e, dict)}
            missing = [r for r in recs if r["text"] not in traced_texts or r["text"] not in file_text]
            reasons = []
            if missing:
                reasons.append("standing principles not yet integrated and traced into the "
                               "oracle document (they are in force; this round owns the document)")
            last = int((reviews.get(key) or {}).get("round") or 0)
            if rounds >= every and rounds - last >= every:
                reasons.append("no whole-document review for %d rounds" % (rounds - last))
            if reasons:
                out.append({"doc": key, "kind": kind, "id": id, "reasons": reasons,
                            "lessons": [], "statements": [r["text"] for r in missing]})
            continue
        folded = folded_lesson_ids(con, kind, id)
        traced = {int(k) for k in trace_entries(kind, id) if str(k).isdigit()}
        covered = set((reviews.get(key) or {}).get("covered") or [])
        unintegrated = [i for i in folded if i not in traced and i not in covered]
        reasons = []
        if unintegrated:
            reasons.append("appended field notes not yet integrated into the document's own text"
                           if kind != "rulebook" else
                           "lessons folded into rules are not yet traced to the text that carries them")
        stale = _stale_reason(kind, id)
        if stale:
            reasons.append(stale)
        eligible = kind == "rulebook" or bool(folded) or bool(traced) or _personal_exists(kind, id)
        last = int((reviews.get(key) or {}).get("round") or 0)
        if eligible and rounds >= every and rounds - last >= every:
            reasons.append("no whole-document review for %d rounds" % (rounds - last))
        if reasons:
            out.append({"doc": key, "kind": kind, "id": id, "reasons": reasons,
                        "lessons": unintegrated})
    return out


# ---- structure checks ---------------------------------------------------------
def _bullets(text):
    """Joined bullet texts (a bullet plus its indented continuation lines)."""
    out, cur = [], None
    for line in text.split("\n"):
        if re.match(r"^\s*[-*]\s+", line):
            if cur is not None:
                out.append(cur)
            cur = line.strip()
        elif cur is not None and line.startswith("  ") and line.strip():
            cur += " " + line.strip()
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        out.append(cur)
    return out


def _sentence_count(text):
    t = re.sub(r"`[^`]*`", " ", text)                     # code spans are not prose
    t = re.sub(r"https?://\S+", " ", t)
    return len(re.findall(r"[.!?]+(?=\s+[A-Z0-9\"']|\s*$)", t))


def wrap_text(text, width=overlay.HOUSE_WIDTH):
    """Wrap prose paragraphs and bullets to the house width. Front matter, code fences,
    indented code, tables and headings are left alone."""
    lines = text.split("\n")
    out, i, fence, front = [], 0, False, bool(lines and lines[0].strip() == "---")
    while i < len(lines):
        line = lines[i]
        if front:
            out.append(line)
            if i > 0 and line.strip() == "---":
                front = False
            i += 1
            continue
        if line.strip().startswith("```"):
            fence = not fence
            out.append(line); i += 1; continue
        if fence or not line.strip() or line.startswith(("    ", "\t", "|", "#")):
            out.append(line); i += 1; continue
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m:
            indent, marker, rest = m.groups()
            parts = [rest]
            i += 1
            while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() \
                    and not re.match(r"^\s*[-*]\s+", lines[i]):
                parts.append(lines[i].strip()); i += 1
            joined = " ".join(parts)
            sub = indent + " " * (len(marker) + 1)
            wrapped = textwrap.wrap(joined, width=width, initial_indent="%s%s " % (indent, marker),
                                    subsequent_indent=sub, break_long_words=False,
                                    break_on_hyphens=False)
            out.extend(wrapped or ["%s%s " % (indent, marker)])
            continue
        parts = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("    ", "\t", "|", "#")) \
                and not re.match(r"^\s*([-*]|\d+\.)\s+", lines[i]) \
                and not lines[i].strip().startswith("```"):
            parts.append(lines[i].strip()); i += 1
        out.extend(textwrap.wrap(" ".join(parts), width=width, break_long_words=False,
                                 break_on_hyphens=False) or [""])
    return "\n".join(out)


def _long_line_problems(text):
    wrapped = wrap_text(text)
    out, fence, front = [], False, wrapped.startswith("---")
    for n, line in enumerate(wrapped.split("\n"), 1):
        if front:
            if n > 1 and line.strip() == "---":
                front = False
            continue
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence or line.startswith(("    ", "\t", "|")):
            continue
        if len(line) > overlay.HOUSE_WIDTH:
            out.append("line %d is %d characters after wrapping (house width %d)"
                       % (n, len(line), overlay.HOUSE_WIDTH))
    return out


def _entry_lint_problems(kind, text, doc_id):
    """The library lint for one candidate entry, mirroring `verifiers.lint()`."""
    from . import contract as C, verifiers as V
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", prefix=(doc_id or "entry") + "-",
                                      delete=False, encoding="utf-8")
    try:
        tmp.write(text); tmp.close()
        # parse under the entry's own file name so the id-equals-stem check means something
        named = os.path.join(os.path.dirname(tmp.name), (doc_id or "entry") + ".md")
        os.replace(tmp.name, named)
        e = V.parse(named)
    finally:
        for p in (tmp.name, os.path.join(os.path.dirname(tmp.name), (doc_id or "entry") + ".md")):
            try:
                os.unlink(p)
            except OSError:
                pass
    out = list(e["problems"])
    h = e["header"]
    if not h:
        return out or ["no header block"]
    keys, heads = (V.V_KEYS, V.V_HEADINGS) if kind == "verifier" else (V.D_KEYS, V.D_HEADINGS)
    for k in keys:
        if k not in h or (not h[k] and k != "detect"):
            out.append("missing or empty %r" % k)
    if doc_id and h.get("id") and h["id"] != doc_id:
        out.append("header id %r must equal the document id %r" % (h["id"], doc_id))
    for m in V._missing_headings(e["body"], heads):
        out.append("body lacks the heading %r" % m)
    if kind == "verifier":
        if not re.fullmatch(r"[1-6]", h.get("rung", "")):
            out.append("rung must be an integer 1-6")
        if h.get("section") and h["section"] not in V.SECTIONS:
            out.append("unknown section %r" % h["section"])
        if h.get("cost") and h["cost"] not in V.COSTS:
            out.append("cost must be one of %s" % ", ".join(V.COSTS))
        if h.get("ran_here") and h["ran_here"] not in ("yes", "no"):
            out.append("ran_here must be yes or no")
        for k in V._list(h.get("kinds")):
            if k != "any" and k not in C.KINDS:
                out.append("unknown kind %r" % k)
    else:
        known = {x["id"] for x in V.load_verifiers()} | set(overlay.disabled("verifier"))
        fake = dict(e, body=e["body"])
        for i in dict.fromkeys(V.cited_ids(fake)):
            if i not in known:
                out.append("Checks cites unknown verifier id %r" % i)
    return out


def rulebook_problems(text):
    out = []
    pre, rules = overlay.parse_rules(text)
    headings = [l for l in text.split("\n") if l.startswith("## ")]
    if len(headings) != len(rules):
        out.append("the rulebook text does not parse into rules")
    seen = set()
    for line, r in zip(headings, rules):
        if not overlay.ID_TAIL.search(line):
            out.append("rule heading %r lacks its {#id}" % line[:60])
        if r["id"] in seen:
            out.append("duplicate rule id %r" % r["id"])
        seen.add(r["id"])
        if not any(p.lstrip().startswith("Why:") for p in r["body"].split("\n\n")):
            out.append("rule %s lacks its Why paragraph" % r["id"])
    cand = candidate_render(pre, rules)
    lines, chars = overlay.size(cand)
    if lines > overlay.MAX_LINES or chars > overlay.MAX_CHARS:
        out.append("the rulebook would be %d lines and %d characters; the budgets are %d lines "
                   "and %d characters" % (lines, chars, overlay.MAX_LINES, overlay.MAX_CHARS))
    for n in range(1, len(rules) + 1):
        if overlay.more_line(n) not in cand:
            out.append("rule %d lacks its generated `More: sisi rule %d` line" % (n, n))
    return out


def candidate_render(pre, rules):
    try:
        head = overlay.render().splitlines()[0]
    except Exception:
        head = "<!-- candidate rulebook -->"
    parts = [head]
    if (pre or "").strip():
        parts.append(pre)
    for n, r in enumerate(rules, 1):
        body = "\n".join(l for l in r["body"].split("\n") if not MORE_LINE.match(l.strip()))
        parts.append("## %d. %s {#%s}\n\n%s\n%s" % (n, r["title"], r["id"], body.strip("\n"),
                                                    overlay.more_line(n)))
    return "\n\n".join(parts) + "\n"


def structure_problems(kind, text, doc_id=None):
    """Mechanical refusals for a rewritten document. Empty means the structure is acceptable.
    The bullet test is deliberately simple: one bullet, once it passes the configured length
    (default %d characters), may not end more than one sentence.""" % DEFAULT_MAX_BULLET_CHARS
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        if DATED_BULLET.match(line):
            out.append("line %d is a dated journal-style bullet; integrate it into the "
                       "document's own text instead" % n)
    limit = max_bullet_chars()
    for b in _bullets(text):
        if len(b) > limit and _sentence_count(b) > 1:
            out.append("a bullet of %d characters holds %d sentences; one instruction per "
                       "bullet (limit %d characters): %r" % (len(b), _sentence_count(b), limit, b[:60]))
    out.extend(_long_line_problems(text))
    if kind == "oracle" and not (text or "").lstrip().startswith("# "):
        out.append("the oracle document must start with a `# title` heading")
    if kind == "rulebook":
        out.extend(rulebook_problems(text))
    elif kind in ("recipe", "verifier"):
        out.extend(_entry_lint_problems(kind, text, doc_id))
    return out


def _norm(s):
    return " ".join(str(s or "").split())


def _fragment_in(fragment, text):
    return bool(fragment) and _norm(fragment) in _norm(text)


# ---- validation of a cycle file's documents part ------------------------------
def _retirement_ok(con, lid):
    from . import retro
    r = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
    if not r:
        return "no such lesson"
    if not r["folded_into"]:
        return "it is not folded anywhere yet"
    if retro.shown_count(con, lid) < retro.RETIRE_SHOWS:
        return "it has been shown %d times (retirement needs %d quiet showings)" % (
            retro.shown_count(con, lid), retro.RETIRE_SHOWS)
    if retro.recurrences_after_shown(con, r):
        return "it still recurs after being shown"
    return None


def validate_documents(doc, con, required=None):
    errs = []
    entries = doc.get("documents") or []
    if not isinstance(entries, list):
        return ["documents must be a list"]
    by_doc = {}
    for e in entries:
        if not isinstance(e, dict) or not e.get("doc"):
            errs.append("each documents entry needs a doc (\"rulebook\", \"oracle\", \"recipe:<id>\" or \"verifier:<id>\"): %r" % (e,))
            continue
        kind, id = parse_doc_key(e["doc"])
        if kind is None:
            errs.append("documents entry %r: doc must be \"rulebook\", \"oracle\", \"recipe:<id>\" or \"verifier:<id>\"" % e["doc"])
            continue
        if kind != "rulebook" and not effective_text(kind, id):
            errs.append("document %s: no such %s" % (e["doc"], kind))
            continue
        by_doc[e["doc"]] = e
    if required is None:
        required = required_documents(con)
    # an oracle whose only unintegrated statements this same file scopes to their project
    # needs no rewrite: they leave the global store in this round
    _to_project = {e.get("text") for e in doc.get("learn") or []
                   if isinstance(e, dict) and e.get("scope") == "project"}
    if _to_project:
        required = [r for r in required
                    if not (r.get("doc") == "oracle" and r.get("statements")
                            and all(t in _to_project for t in r["statements"]))]
    for req in required:
        if req["doc"] not in by_doc:
            errs.append("document %s: missing whole-document entry - the brief listed it (%s); add a "
                        "documents entry {\"doc\": %r, \"action\": \"rewrite\", \"text\": ..., \"trace\": [...]} "
                        "or {\"doc\": %r, \"action\": \"reviewed\", \"reason\": \"...\"}"
                        % (req["doc"], "; ".join(req["reasons"]), req["doc"], req["doc"]))
    # lessons this same file folds into a document also need a trace entry in its rewrite
    extra_folded = {}
    for e in doc.get("notes") or []:
        if not isinstance(e, dict) or not isinstance(e.get("lesson"), int):
            continue
        intos = e.get("into")
        intos = intos if isinstance(intos, list) else ([intos] if intos else [])
        if e.get("action") == "fold-into-entry":
            from . import verifiers as V
            rids = {x["id"] for x in V.load_recipes() if x["header"]}
            for into in intos:
                key = doc_key("recipe" if into in rids else "verifier", into)
                extra_folded.setdefault(key, set()).add(e["lesson"])
        elif e.get("action") == "fold-into-rule":
            extra_folded.setdefault("rulebook", set()).add(e["lesson"])
    new_texts = {k: e.get("text") or "" for k, e in by_doc.items() if e.get("action") == "rewrite"}
    for key, e in sorted(by_doc.items()):
        kind, id = parse_doc_key(key)
        act = e.get("action")
        if act not in ("rewrite", "reviewed"):
            errs.append("document %s: action must be rewrite or reviewed" % key)
            continue
        if act == "reviewed":
            if not str(e.get("reason") or "").strip():
                errs.append("document %s: reviewed needs a one-line reason why its structure is already right" % key)
            continue
        text = e.get("text")
        if not str(text or "").strip():
            errs.append("document %s: rewrite needs text (the full new document)" % key)
            continue
        for p in structure_problems(kind, text, None if kind == "rulebook" else id):
            errs.append("document %s: %s" % (key, p))
        needed = set(folded_lesson_ids(con, kind, id)) | extra_folded.get(key, set())
        trace = e.get("trace") or []
        if not isinstance(trace, list):
            errs.append("document %s: trace must be a list" % key)
            trace = []
        seen = {}
        for t in trace:
            if isinstance(t, dict) and isinstance(t.get("lesson"), int):
                seen[t["lesson"]] = t
        for lid in sorted(needed - set(seen)):
            errs.append("lesson #%d: no trace entry in the rewrite of %s - give the exact fragment "
                        "of the new text that carries it, or a moved/merged/retired disposition" % (lid, key))
        for lid, t in sorted(seen.items()):
            disp = t.get("disposition") or "carried"
            frag = t.get("fragment")
            if disp == "carried":
                if not _fragment_in(frag, text):
                    errs.append("lesson #%d: its fragment %r does not occur in the new text of %s"
                                % (lid, str(frag)[:60], key))
            elif disp == "merged":
                other = t.get("merged_with")
                if not isinstance(other, int) or other == lid:
                    errs.append("lesson #%d: merged needs merged_with naming a different lesson" % lid)
                elif not _fragment_in(frag, text):
                    errs.append("lesson #%d: its merged fragment %r does not occur in the new text of %s"
                                % (lid, str(frag)[:60], key))
                elif other in seen and _norm(seen[other].get("fragment")) != _norm(frag):
                    errs.append("lesson #%d: merged with #%d but their fragments differ; both ids must "
                                "point at the same fragment" % (lid, other))
            elif disp == "moved":
                to_kind, to_id = parse_doc_key(t.get("to") or "")
                if to_kind is None:
                    errs.append("lesson #%d: moved needs \"to\" naming the document it moved to" % lid)
                else:
                    target_text = new_texts.get(t["to"]) or effective_text(to_kind, to_id)
                    if not _fragment_in(frag, target_text):
                        errs.append("lesson #%d: its fragment %r does not occur in %s, where it is said to live now"
                                    % (lid, str(frag)[:60], t["to"]))
            elif disp == "retired":
                if not str(t.get("reason") or "").strip():
                    errs.append("lesson #%d: retired needs a reason" % lid)
                else:
                    why_not = _retirement_ok(con, lid)
                    if why_not:
                        errs.append("lesson #%d: cannot retire it in a rewrite: %s" % (lid, why_not))
            else:
                errs.append("lesson #%d: disposition must be carried, moved, merged or retired" % lid)
        if kind == "oracle":
            from . import principles as _pr
            stmt_seen = {t["statement"]: t for t in trace
                         if isinstance(t, dict) and isinstance(t.get("statement"), str)}
            for rec in _pr.statements():
                t = stmt_seen.get(rec["text"])
                if t is None:
                    errs.append("principle %r: no trace entry in the rewrite of oracle - give the "
                                "exact fragment of the new text that carries it (every statement "
                                "must be traced)" % rec["text"][:60])
                elif not _fragment_in(t.get("fragment"), text):
                    errs.append("principle %r: its fragment %r does not occur in the new oracle text"
                                % (rec["text"][:60], str(t.get("fragment"))[:60]))
        if kind == "rulebook":
            _pre, new_rules = overlay.parse_rules(text)
            new_ids = [r["id"] for r in new_rules]
            merges = {}
            for m in e.get("rule_merges") or []:
                if isinstance(m, dict) and m.get("from") and m.get("into"):
                    merges[m["from"]] = m["into"]
            _p2, eff = overlay.effective()
            for r in eff:
                if r["id"] not in new_ids and r["id"] not in merges:
                    errs.append("rule %s: every existing rule id must survive a rulebook rewrite or be "
                                "merged into another id (rule_merges)" % r["id"])
            for frm, into in sorted(merges.items()):
                if into not in new_ids:
                    errs.append("rule %s: merged into %s, which is not in the new rulebook" % (frm, into))
    order = doc.get("rule_order")
    if order is not None:
        _pre, eff = overlay.effective()
        want = {r["id"] for r in eff} - set(doc.get("disable_rules") or [])
        want |= {e.get("id") for e in doc.get("rules") or []
                 if isinstance(e, dict) and e.get("action") == "add"}
        rb = by_doc.get("rulebook") or {}
        if rb.get("action") == "rewrite" and rb.get("text"):
            _p3, new_rules = overlay.parse_rules(rb["text"])
            want = {r["id"] for r in new_rules}
        if not isinstance(order, list) or set(order) != want or len(order) != len(set(order)):
            errs.append("rule_order must name every rule id exactly once (missing: %s; unknown: %s)"
                        % (", ".join(sorted(want - set(order if isinstance(order, list) else []))) or "-",
                           ", ".join(sorted(set(order if isinstance(order, list) else []) - want)) or "-"))
    return errs


def candidate_rulebook(doc):
    """The rulebook text a cycle file would produce, or None when it does not touch the
    rulebook as a document or its order (the older per-rule prediction then applies)."""
    entries = {e.get("doc"): e for e in doc.get("documents") or [] if isinstance(e, dict)}
    rb = entries.get("rulebook") or {}
    if rb.get("action") == "rewrite" and rb.get("text"):
        pre, rules = overlay.parse_rules(rb["text"])
        if isinstance(doc.get("rule_order"), list):
            rank = {id: i for i, id in enumerate(doc["rule_order"])}
            rules = sorted(rules, key=lambda r: rank.get(r["id"], len(rank)))
        return candidate_render(pre, rules)
    if isinstance(doc.get("rule_order"), list):
        pre, eff = overlay.effective()
        by_id = {r["id"]: r for r in eff}
        for rid in doc.get("disable_rules") or []:
            by_id.pop(rid, None)
        for e in doc.get("rules") or []:
            if isinstance(e, dict) and e.get("id"):
                by_id[e["id"]] = {"id": e["id"], "title": e.get("title") or e["id"],
                                  "body": overlay.wrap_rule_body(e.get("body") or "")}
        rules = [by_id[i] for i in doc["rule_order"] if i in by_id]
        rules += [r for i, r in by_id.items() if i not in doc["rule_order"]]
        return candidate_render(pre, rules)
    return None


# ---- applying a validated cycle file's documents part -------------------------
def _drop_note_bullets(entry_id, lesson_ids):
    from . import retro
    p = os.path.join(paths.notes_dir(), entry_id + ".md")
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.read().splitlines(True)
    except OSError:
        return
    keep = []
    for line in lines:
        parsed = retro._parse_bullet(line)
        if parsed and parsed[2] in lesson_ids:
            continue
        keep.append(line)
    if not any(retro._parse_bullet(l) for l in keep):
        try:
            os.unlink(p)
        except OSError:
            pass
    elif keep != lines:
        tmp = p + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("".join(keep))
        os.replace(tmp, p)


def _record_review(reviews, key, con, kind, id, action):
    reviews[key] = {"round": next_round_number(), "action": action,
                    "covered": folded_lesson_ids(con, kind, id)}


def apply_documents(doc, con, touched):
    """Write rewrites, trace maps, reviews and rule order. Caller holds the personal-data
    lock and has already validated. Returns {doc_key: [lesson ids]} for rewritten documents."""
    from . import store
    reviews = load_reviews()
    changed = {}
    for e in doc.get("documents") or []:
        if not isinstance(e, dict):
            continue
        kind, id = parse_doc_key(e.get("doc") or "")
        if kind is None:
            continue
        key = e["doc"]
        if e.get("action") == "reviewed":
            _record_review(reviews, key, con, kind, id, "reviewed")
            continue
        if e.get("action") != "rewrite":
            continue
        text = e["text"] if e["text"].endswith("\n") else e["text"] + "\n"
        trace = {t["lesson"]: t for t in e.get("trace") or []
                 if isinstance(t, dict) and isinstance(t.get("lesson"), int)}
        if kind == "rulebook":
            _apply_rulebook(e, text, con, touched)
        elif kind == "oracle":
            from . import principles as _pr
            p = _pr.oracle_path()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + ".tmp%d" % os.getpid()
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, p)
            for t in e.get("trace") or []:
                if isinstance(t, dict) and isinstance(t.get("statement"), str):
                    entries = trace_entries(kind, id)
                    entries[t["statement"]] = {"statement": t["statement"],
                                                "fragment": t.get("fragment"),
                                                "disposition": t.get("disposition") or "carried"}
                    rec = {"doc": key, "kind": kind, "id": id, "base_hash": None, "entries": entries}
                    overlay._write(_trace_rel(kind, id), json.dumps(rec, indent=1, sort_keys=True) + "\n")
            _record_review(reviews, key, con, kind, id, "rewrite")
            changed[key] = []
            continue
        else:
            _id, rel, mine = overlay._put_entry(kind, text, id, True)
            for p in mine:
                overlay._remove(p)
            overlay._write(rel, text)
            overlay._set_base(kind, id, overlay.base_hash(kind, id))
            if trace:
                _drop_note_bullets(id, set(trace))
        entries = trace_entries(kind, id)
        for lid, t in trace.items():
            touched.add(lid)
            disp = t.get("disposition") or "carried"
            entries[str(lid)] = {"fragment": t.get("fragment"), "disposition": disp,
                                 "to": t.get("to"), "merged_with": t.get("merged_with"),
                                 "reason": t.get("reason")}
            if disp == "moved":
                to_kind, to_id = parse_doc_key(t.get("to") or "")
                folded = "rule:%s" % to_id if to_kind == "rulebook" else to_id
                if to_kind == "rulebook":
                    # the fragment lives in one rule; keep the lesson pointing at the rulebook
                    folded = "rulebook"
                con.execute("UPDATE lessons SET folded_into=? WHERE id=?", (folded, lid))
            elif disp == "retired":
                con.execute("UPDATE lessons SET status='retired', needs_cycle=0 WHERE id=?", (lid,))
        rec = {"doc": key, "kind": kind, "id": id,
               "base_hash": overlay.base_hash(kind, id) if kind != "rulebook" else None,
               "entries": entries}
        if kind == "rulebook" and e.get("rule_merges"):
            rec["rule_merges"] = {m["from"]: m["into"] for m in e["rule_merges"]
                                  if isinstance(m, dict) and m.get("from")}
        overlay._write(_trace_rel(kind, id), json.dumps(rec, indent=1, sort_keys=True) + "\n")
        _record_review(reviews, key, con, kind, id, "rewrite")
        changed[key] = sorted(trace)
    if isinstance(doc.get("rule_order"), list):
        overlay._set_lines("rules/full-order.txt", list(doc["rule_order"]))
    if reviews != load_reviews() or changed:
        _save_reviews(reviews)
    return changed


def _apply_rulebook(e, text, con, touched):
    pre, rules = overlay.parse_rules(text)
    base = {r["id"]: r for r in overlay.base_rules()[1]}
    merges = {m["from"]: m["into"] for m in e.get("rule_merges") or []
              if isinstance(m, dict) and m.get("from") and m.get("into")}
    for r in rules:
        body = overlay.wrap_rule_body("\n".join(
            l for l in r["body"].split("\n") if not MORE_LINE.match(l.strip())))
        cand = {"id": r["id"], "title": r["title"], "body": body}
        b = base.get(r["id"])
        rel = "rules/%s.md" % r["id"]
        if b and b["title"] == cand["title"] and overlay.wrap_rule_body(b["body"]) == body:
            overlay._remove(paths.overlay_dir(rel))  # back to the product text: no personal copy
            overlay._set_base("rule", r["id"], None)
        else:
            overlay._write(rel, overlay.rule_text(cand))
            if b:
                overlay._set_base("rule", r["id"], overlay.base_hash("rule", r["id"]))
    if merges:
        off = overlay.disabled("rule")
        overlay._set_lines("rules/disabled.txt", off + [x for x in merges if x not in off])
        for frm, into in merges.items():
            overlay._remove(paths.overlay_dir("rules/%s.md" % frm))
            for row in con.execute("SELECT id, folded_into FROM lessons WHERE folded_into LIKE ?",
                                   ("%" + "rule:" + frm + "%",)):
                touched.add(row[0])
                new = ",".join("rule:" + into if t.strip() == "rule:" + frm else t.strip()
                               for t in str(row[1]).split(","))
                con.execute("UPDATE lessons SET folded_into=? WHERE id=?", (new, row[0]))
    overlay._set_lines("rules/full-order.txt", [r["id"] for r in rules])


def trace_lines(kind, id):
    """Plain lines for `sisi done ID --trace` and friends: where each lesson lives."""
    entries = trace_entries(kind, id)
    if not entries:
        return ["no whole-document rewrite has traced lessons into %s yet" % doc_key(kind, id)]
    out = ["where each lesson lives in %s (trace map, not part of the text agents load):"
           % doc_key(kind, id)]
    for lid_s in sorted(entries, key=lambda s: int(s) if str(s).isdigit() else 0):
        t = entries[lid_s]
        disp = t.get("disposition") or "carried"
        if disp == "moved":
            out.append("  #%s moved to %s as %r" % (lid_s, t.get("to"), t.get("fragment")))
        elif disp == "merged":
            out.append("  #%s merged with #%s as %r" % (lid_s, t.get("merged_with"), t.get("fragment")))
        elif disp == "retired":
            out.append("  #%s retired: %s" % (lid_s, t.get("reason")))
        else:
            out.append("  #%s lives as %r" % (lid_s, t.get("fragment")))
    return out
