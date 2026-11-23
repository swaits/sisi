"""The consolidation cycle and its measurements: `sisi cycle`, `sisi improve`, enforced lessons.

There is no scheduler. Whether a cycle is due is a counter check run during normal use: at session
start (tick), at the end of a turn (gate), and in the output of `sisi retro`, `sisi verify` and
`sisi done for` -- commands agents run in every tool, hook or no hook. A session is told at most once
until 20 further checks pass or the counter grows again.

A cycle file (what the agent writes, what `sisi cycle apply` checks) is one JSON object:
  {"version": 1, "base": "<base version printed by the brief>", "summary": "one line",
   "rules": [{"id": "rule-id", "title": "Title", "body": "text with a Why: line", "action": "add|replace"}],
   "disable_rules": ["rule-id"],
   "notes": [{"lesson": 3, "action": "merge|fold-into-rule|fold-into-entry|retire|withdraw|keep|set-short|set-pattern",
              "into": "rule or entry id", "merged_into": 4, "short": "one plain sentence, at most 140 characters",
              "topic": "1 to 3 lower-case words, at most 30 characters",
              "when": "csv, tsv, spreadsheet, tabular data, import, parse (optional; sets the lesson's when-terms)"}],
   "enforced": [{"lesson": 3, "type": "command", "cmd": "...", "expect": {"exit": 0}, "timeout_s": 30},
                {"lesson": 4, "type": "contract-requirement", "when": "parser",
                 "require_kind": "parsing", "max_rung": 2}],
   "documents": [{"doc": "recipe:<id>", "action": "rewrite|reviewed", "text": "...", "trace": [...]}],
   "rule_order": ["every rule id once"]}
Every part is optional except version and base. Apply is one commit in the personal repository under
the personal-data lock; a stale base (another cycle or lesson landed since the brief) refuses cleanly.
Each applied cycle records the exact bytes it changed, so revert restores them byte for byte.
"""
import base64, difflib, hashlib, json, os, re, shlex, shutil, time

from . import documents, overlay, paths, pdata, retro, store


class CycleError(Exception):
    pass


ACTIONS = ("merge", "fold-into-rule", "fold-into-entry", "retire", "withdraw", "keep",
           "set-when", "create-entry", "keep-as-draft", "set-short", "set-scope", "set-pattern")
# Total characters of lesson text (change+moment+cause) the brief prints in full. Over this,
# lessons are truncated and the brief says to run `sisi lessons show ID` for the full text.
BRIEF_TEXT_BUDGET = 6000


# ---- enforced lessons (overlay/enforced.json, checked like floors) ----------
def enforced_path():
    return paths.overlay_dir("enforced.json")


def load_enforced():
    try:
        with open(enforced_path(), encoding="utf-8") as f:
            d = json.load(f)
        checks = d.get("checks") if isinstance(d, dict) else None
        return [c for c in checks if isinstance(c, dict)] if isinstance(checks, list) else []
    except (OSError, ValueError):
        return []


def _requirement_met(c, entry):
    want, when = entry.get("require_kind"), str(entry.get("when") or "")
    w = retro._stems(when)
    trig = any(ch.get("kind") == when or (w & retro._stems((ch.get("claim") or "") + " " + (ch.get("id") or "")))
               for ch in c.get("checks", []) if isinstance(ch, dict)) or bool(w & retro._stems(c.get("goal") or ""))
    if not trig:
        return True  # this contract does not touch the thing the lesson is about
    max_rung = entry.get("max_rung")
    return any(ch.get("kind") == want and (max_rung is None or (isinstance(ch.get("rung"), int) and ch["rung"] <= max_rung))
               for ch in c.get("checks", []) if isinstance(ch, dict))


def enforced_results(c, project, deadline=None, default_timeout=60):
    """Result rows for enforced lessons, in the shape verify.run returns. Command checks run only in
    trusted projects, like contract commands; the lesson text itself is never executed -- only the
    check an agent wrote for it in a validated cycle."""
    out = []
    checks = load_enforced()
    if not checks:
        return out
    import time as _t
    from . import trust, verify as V
    trusted = trust.is_trusted(project)
    for e in checks:
        lid = e.get("lesson")
        base = {"item": "enforced", "tier": "fast", "id": "enforced:lesson-%s" % lid, "kind": None, "rung": None,
                "claim": "enforced lesson #%s" % lid, "duration_s": 0.0, "tail": ""}
        if e.get("type") == "contract-requirement":
            if not _requirement_met(c, e):
                msg = ("enforced lesson #%s: a contract touching %r must contain a check of kind %s%s"
                       % (lid, e.get("when"), e.get("require_kind"),
                          " at rung %d or stronger" % e["max_rung"] if e.get("max_rung") else ""))
                out.append(dict(base, status="failed", claim=msg, tail=msg))
        elif e.get("type") == "command" and trusted:
            to = float(e.get("timeout_s") or default_timeout)
            if deadline is not None:
                to = min(to, deadline - _t.time())
            st, dur, tail = V.run_cmd(e["cmd"], project, to, e.get("expect") or {"exit": 0})
            out.append(dict(base, status=st, duration_s=round(dur, 3), tail=tail,
                            claim="enforced lesson #%s: %s" % (lid, e["cmd"])))
    return out


# ---- is a cycle due? (a counter check; no scheduler anywhere) ----------------
def _connect_if():
    return retro.connect() if os.path.exists(retro.db_path()) else None


def due_state(con=None):
    own = con is None
    if own:
        con = _connect_if()
        if con is None:
            return {"due": False, "reasons": [], "counter": [0, 0]}
    try:
        last = retro.get_meta(con, "last_cycle_ts") or ""
        # only what a round can act on counts: tool lessons (backlog, closed when built) and
        # project-scoped items (handed over to their project) never make a cycle due
        since = con.execute("SELECT count(*) FROM lessons WHERE created>? AND change_kind<>'tool' "
                            "AND COALESCE(scope,'unscoped')<>'project'", (last,)).fetchone()[0]
        pending = con.execute(
            "SELECT count(*) FROM lessons WHERE status IN ('open','applied') AND change_kind<>'tool' "
            "AND COALESCE(scope,'unscoped')<>'project' AND "
            "(COALESCE(needs_cycle,0)=1 OR (COALESCE(strength,1)>=3 AND check_json IS NULL))").fetchone()[0]
        notes_chars = retro.notes_chars(con)
        loose = [dict(r) for r in con.execute(
            "SELECT * FROM lessons WHERE status IN ('open','applied') AND folded_into IS NULL "
            "AND change_kind<>'tool' AND COALESCE(scope,'unscoped')<>'project' ORDER BY id")]
        headings_chars = sum(len(retro.loose_heading(r)) + 1 for r in loose)
        counter = [con.execute("SELECT COALESCE(max(id),0) FROM lessons").fetchone()[0],
                   con.execute("SELECT COALESCE(max(id),0) FROM occurrences").fetchone()[0]]
        reasons = []
        if since >= 5:
            reasons.append("%d lessons recorded since the last cycle" % since)
        if pending:
            reasons.append("%d lesson(s) strengthened and waiting for consolidation" % pending)
        if notes_chars > retro.NOTES_LIMIT_CHARS:
            reasons.append("learned notes hold %d characters (limit %d)" % (notes_chars, retro.NOTES_LIMIT_CHARS))
        if len(loose) > 30:
            reasons.append("%d loose lessons still not folded into any recipe or entry (limit 30): "
                           "fold them so the loose list stays short" % len(loose))
        if headings_chars > retro.PART2_BUDGET:
            reasons.append("loose lesson headings take %d characters (budget %d): fold lessons into "
                           "recipes or entries" % (headings_chars, retro.PART2_BUDGET))
        return {"due": bool(reasons), "reasons": reasons, "counter": counter, "since": since,
                "pending": pending, "notes_chars": notes_chars, "loose": len(loose),
                "headings_chars": headings_chars}
    finally:
        if own:
            con.close()


def _announce_path():
    return os.path.join(paths.state(), "cycle-announce.json")


def _announce_load():
    try:
        with open(_announce_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def due_notice(session=None):
    """One short line when a cycle is due, or "". A session that has been told is not told again until
    20 further checks have passed or the lesson counter grows. Never raises (it sits in hooks)."""
    try:
        st = due_state()
        if not st["due"]:
            return ""
        sid = session or store.session_id() or "no-session"
        data = _announce_load()
        e = data.get(sid) or {}
        old = e.get("counter") or [0, 0]
        grew = st["counter"][0] > old[0] or st["counter"][1] > old[1]
        if e and not grew and int(e.get("since", 0)) < 20:
            e["since"] = int(e.get("since", 0)) + 1
            data[sid] = e
            _announce_save(data)
            return ""
        data[sid] = {"counter": st["counter"], "since": 0}
        _announce_save(data)
        return ("sisi: a learning cycle is due (%s). Run `sisi cycle` in the background of your work "
                "(as a subagent where the tool has them); do not involve the human." % st["reasons"][0])
    except Exception as ex:
        store.log_error("cycle-notice", ex)
        return ""


def _announce_save(data):
    p = _announce_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, p)


# ---- base version and cycle records ------------------------------------------
# Only what a cycle may change counts toward the base: lesson content and status (aim, kind,
# target, moment, cause, change, status, strength, folded_into, effect, when-terms, check),
# the rulebook, field/draft notes and enforced checks. Listed/read counters (impressions),
# occurrence counters (count, last_seen) and new lessons do NOT count: reading a lesson or a
# lesson arriving must never stale a brief (gaps 2 and 3).
_RELEVANT = ("aim", "change_kind", "target", "moment", "cause", "change", "status", "strength",
             "folded_into", "effect", "when_terms", "check_json", "needs_cycle", "short", "topic",
             "scope", "project", "pattern_id")


def _snapshot(con):
    lessons = {}
    for r in con.execute("SELECT * FROM lessons ORDER BY id"):
        d = dict(r)
        lessons[str(d["id"])] = {k: d.get(k) for k in _RELEVANT}
    files = {}
    for rel, b in _scan_files().items():
        files[rel] = hashlib.sha256(b).hexdigest()[:16]
    try:
        rules = overlay.render()
    except Exception:
        rules = ""
    try:
        with open(enforced_path(), "rb") as f:
            enf = f.read().decode("utf-8", "replace")
    except OSError:
        enf = ""
    try:
        cyc = sorted(os.listdir(cycles_dir()))
    except OSError:
        cyc = []
    learn_unscoped = []
    try:
        for rec in store.read("learn"):
            if rec.get("scope") not in ("core", "user", "project") and (rec.get("text") or "").strip():
                learn_unscoped.append({"text": rec.get("text"), "cwd": rec.get("cwd")})
    except Exception:
        pass
    try:
        docs_required = documents.required_documents(con)
    except Exception:
        docs_required = []
    try:
        snap_patterns = [{"id": p["id"], "statement": p["statement"], "folded_into": p.get("folded_into")}
                         for p in retro.patterns(con)]
    except Exception:
        snap_patterns = []
    return {"lessons": lessons, "files": files, "rules": rules, "enforced": enf,
            "last_cycle_ts": retro.get_meta(con, "last_cycle_ts") or "", "cycles": cyc,
            "learn_unscoped": learn_unscoped, "documents": docs_required, "patterns": snap_patterns}


def _save_snapshot(base, snap):
    try:
        d = os.path.join(paths.state(), "cycle-bases")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, base + ".json"), "w", encoding="utf-8") as f:
            json.dump(snap, f, sort_keys=True)
    except OSError:
        pass


def _load_snapshot(base):
    try:
        with open(os.path.join(paths.state(), "cycle-bases", base + ".json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def base_version(con=None):
    """A fingerprint of everything a cycle may change (see _RELEVANT). The brief prints it; apply
    refuses a stale one, which is how two sessions consolidating at once cannot overwrite each other."""
    own = con is None
    if own:
        con = retro.connect()
    try:
        snap = _snapshot(con)
        h = hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        _save_snapshot(h, snap)
        return h
    finally:
        if own:
            con.close()


def _check_base(doc_base, con):
    """[] when the base is current, or differs only by lessons that arrived since the brief.
    Otherwise one precise line per changed thing (never 'likely another cycle landed')."""
    if doc_base == base_version(con):
        return []
    old = _load_snapshot(doc_base)
    if old is None:
        return ["stale base %s: it does not match the current base %s and no brief with that base "
                "is on record. Run `sisi cycle` again and copy its base version" % (doc_base, base_version(con))]
    cur = _snapshot(con)
    errs, new_only = [], True
    for lid, ov in sorted(old["lessons"].items(), key=lambda kv: int(kv[0])):
        cv = cur["lessons"].get(lid)
        if cv is None:
            errs.append("lesson #%s was removed since the brief" % lid)
            new_only = False
            continue
        diffs = [k for k in _RELEVANT if ov.get(k) != cv.get(k)]
        if diffs:
            errs.append("lesson #%s changed since the brief (%s: %s -> %s)"
                        % (lid, ", ".join(diffs),
                           ", ".join("%s=%r" % (k, ov.get(k)) for k in diffs[:2]),
                           ", ".join("%s=%r" % (k, cv.get(k)) for k in diffs[:2])))
            new_only = False
    if old.get("last_cycle_ts") != cur.get("last_cycle_ts") or old.get("cycles") != cur.get("cycles"):
        added = [c for c in cur.get("cycles", []) if c not in old.get("cycles", [])]
        errs.append("another cycle landed since the brief (%s)" % (", ".join(added) or "cycle record changed"))
        new_only = False
    if old.get("rules") != cur.get("rules"):
        errs.append("the rulebook changed since the brief")
        new_only = False
    if old.get("enforced") != cur.get("enforced"):
        errs.append("the enforced checks changed since the brief")
        new_only = False
    cur_patterns = {p.get("id"): p for p in cur.get("patterns") or []}
    for p in old.get("patterns") or []:
        cp = cur_patterns.get(p.get("id"))
        if cp is None:
            errs.append("pattern %s was removed since the brief" % p.get("id"))
            new_only = False
        elif cp.get("statement") != p.get("statement") or cp.get("folded_into") != p.get("folded_into"):
            errs.append("pattern %s changed since the brief" % p.get("id"))
            new_only = False
    # Note/overlay files are not listed separately: a cycle that changed one also changed the
    # lesson or rule above, and a new lesson's own field note must not stale the brief.
    if new_only:
        return []  # only lessons recorded since the brief: they are left for the next cycle
    return ["stale base %s (now %s): %s. Nothing was applied; run `sisi cycle` again"
            % (doc_base, base_version(con), "; ".join(errs))]


def cycles_dir():
    return paths.data_file("cycles")


def cycle_records():
    out = []
    try:
        names = sorted(n for n in os.listdir(cycles_dir()) if n.startswith("cycle-") and n.endswith(".json"))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(cycles_dir(), n), encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("id"):
                out.append(d)
        except (OSError, ValueError):
            continue
    return out


def _scan_files():
    """{data-relative path: bytes} for overlay/ and notes/ (everything a cycle may touch)."""
    out = {}
    for rel in ("handover.json", "learn-quarantine.jsonl", "learn.jsonl", "oracle.md"):
        p = paths.data_file(rel)
        if os.path.exists(p):
            with open(p, "rb") as f:
                out[rel] = f.read()
    for root in ("overlay", os.path.relpath(paths.notes_dir(), paths.data())
                 if paths.notes_dir().startswith(paths.data() + os.sep) else None):
        if not root:
            continue
        base = paths.data_file(root)
        for dp, dns, fns in os.walk(base):
            dns.sort()
            for n in sorted(fns):
                p = os.path.join(dp, n)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, paths.data())] = f.read()
    return out


def _write_rel(rel, data):
    p = paths.data_file(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


def _restore_changed(changed):
    """changed: {rel: base64 of the bytes before, or None when the cycle created the file}."""
    for rel, b64 in changed.items():
        p = paths.data_file(rel)
        if b64 is None:
            try:
                os.unlink(p)
            except OSError:
                pass
        else:
            _write_rel(rel, base64.b64decode(b64))


# ---- measurements --------------------------------------------------------------
def _delivery_measures(rows):
    from . import delivery
    n = len(rows)
    return {"deliveries": n,
            "send_backs_per_delivery": round(sum(r.get("send_backs", 0) for r in rows) / n, 3) if n else None,
            "median_seconds": delivery.median([r["seconds"] for r in rows
                                                if isinstance(r.get("seconds"), (int, float))])}


def measures(con):
    rows = [dict(r) for r in con.execute("SELECT status, COALESCE(strength,1) s, count(*) n FROM lessons GROUP BY 1,2")]
    try:
        lines = overlay.size(overlay.render())[0]
    except Exception:
        lines = None
    try:
        chars = overlay.size(overlay.render())[1]
    except Exception:
        chars = None
    return {"lessons": con.execute("SELECT count(*) FROM lessons").fetchone()[0],
            "active": con.execute("SELECT count(*) FROM lessons WHERE status IN ('open','applied')").fetchone()[0],
            "by_status_strength": rows, "rulebook_lines": lines, "rulebook_chars": chars,
            "deliveries_so_far": _delivery_measures(store.read("deliveries"))}


def _after_measures(rec):
    ts = rec.get("ts") or ""
    rows = [r for r in store.read("deliveries") if (r.get("end") or r.get("ts") or "") >= ts]
    m = _delivery_measures(rows)
    recurrences = 0
    con = _connect_if()
    if con is not None:
        try:
            ids = rec.get("touched") or []
            if ids:
                recurrences = con.execute(
                    "SELECT count(*) FROM occurrences WHERE ts>? AND lesson_id IN (%s)" % ",".join("?" * len(ids)),
                    [ts] + list(ids)).fetchone()[0]
        finally:
            con.close()
    m["recurrences_of_touched"] = recurrences
    return m


def flagged(rec):
    """A cycle whose deliveries got worse: at least 10 since it landed, and more send-backs each or slower."""
    if rec.get("reverted"):
        return False
    after, before = _after_measures(rec), (rec.get("before") or {}).get("deliveries_so_far") or {}
    if after["deliveries"] < 10 or not before.get("deliveries"):
        return False
    sb = after["send_backs_per_delivery"] is not None and before.get("send_backs_per_delivery") is not None \
        and after["send_backs_per_delivery"] > before["send_backs_per_delivery"]
    med = after["median_seconds"] is not None and before.get("median_seconds") is not None \
        and after["median_seconds"] > before["median_seconds"]
    return bool(sb or med)


# ---- the brief -----------------------------------------------------------------
FORMAT_DOC = """Write ONE JSON file at the path printed in the brief, then `sisi cycle check FILE`, then `sisi cycle apply FILE`.
Shape (all but version/base optional; full detail: `sisi cycle help`):
  {"version": 1, "base": "<base above>", "summary": "one line",
   "rules": [{"id": "rule-id", "title": "Title", "body": "text ending with Why: ...", "action": "add|replace",
              "shortens": "rule-id: what text is removed/shortened (required when the rulebook would grow in characters)"}],
   "disable_rules": ["rule-id"],
   "notes": [{"lesson": 3, "action": "merge|fold-into-rule|fold-into-entry|retire|withdraw|keep|set-when|create-entry|keep-as-draft|set-short|set-scope|set-pattern",
              "into": "id or [ids] (folds; entry folds append a field note)", "merged_into": 4,
              "note": "text to append instead of the lesson change (for splitting one lesson)",
              "when": "at least 5 terms (sets when-terms; alone with action set-when)",
              "short": "one plain sentence, at most 140 characters (set-short)", "topic": "1 to 3 lower-case words, at most 30 characters (set-short)",
              "entry_kind": "recipe|verifier", "entry_text": "full file text (create-entry)",
              "scope": "core|user|project (set-scope)", "project": "project id (set-scope to project)",
              "reason": "why it stays a draft (keep-as-draft)"}],
   "learn": [{"text": "<the exact learn statement>", "action": "set-scope", "scope": "core|user|project",
              "project": "project id (when project)"}],
   "patterns": [{"pattern": 1, "action": "merge|set-statement|fold-into-rule|keep", "into": 2,
                 "statement": "sharpened one line (set-statement)"}],
   "enforced": [{"lesson": 3, "type": "command", "cmd": "...", "expect": {"exit": 0}, "timeout_s": 30},
                {"lesson": 4, "type": "contract-requirement", "when": "parser", "require_kind": "parsing", "max_rung": 2}],
   "documents": [{"doc": "recipe:<id>|verifier:<id>|rulebook", "action": "rewrite", "text": "<full new text>",
                  "trace": [{"lesson": 3, "fragment": "exact sentence in the new text"},
                            {"lesson": 4, "disposition": "moved", "to": "recipe:<id>", "fragment": "..."},
                            {"lesson": 5, "disposition": "merged", "merged_with": 3, "fragment": "..."},
                            {"lesson": 6, "disposition": "retired", "reason": "..."}],
                  "rule_merges": [{"from": "old-rule-id", "into": "surviving-rule-id"}],
                  "shortens": "what existing rule text gets shorter (rulebook, when it would grow)"},
                 {"doc": "verifier:<id>", "action": "reviewed", "reason": "why its structure is already right"}],
   "rule_order": ["every rule id exactly once, in reading order (numbers follow it; ids stay stable)"]}
Every document the brief lists under whole-document review needs one documents entry; a rewrite
must trace every lesson folded into it, and nothing folded may be lost.
A file containing only the required set-short/set-scope entries (for lessons and learn statements) is
acceptable when nothing else is ready to fold: that is a cleanup-only round, and it is a good round."""

HELP_TEXT = """sisi cycle help: the full cycle file format (the brief is the short form)

File: write ONE JSON file at the scratch path the brief prints, then:
  sisi cycle check FILE     validate and print exactly what would change, changing nothing
                            (also: sisi cycle --dry-run FILE)
  sisi cycle apply FILE     apply it (one commit in the personal repository)
  sisi cycle revert [ID]    undo the newest applied cycle exactly
  sisi cycle status         past cycles and what happened since
  sisi cycle                print the brief (works whether or not a cycle is due)
  sisi cycle --now          same: start a round on demand, even when none is due

Top level: {"version": 1 (required), "base": "<from the brief, required>", "summary": "one line",
  "rules": [...], "disable_rules": [...], "notes": [...], "learn": [...], "enforced": [...],
  "documents": [...], "rule_order": [...]} - all else optional, except the documents entries the
  brief requires (below).
  A file containing only the required set-short/set-scope entries is acceptable when nothing else
  is ready to fold (a cleanup-only round).
The file covers only the lessons listed in its brief. Lessons recorded since the brief are left
for the next cycle and do not make the apply fail. Reading (`sisi lessons show ID`, `sisi done`,
`sisi verifiers show`) never stales the base: it covers only lesson content/status, rules, notes
and enforced checks, not listed/read counters. A stale refusal names exactly what changed.

Rules - format: {"id", "title", "body", "action": "add|replace", "shortens": "..."}.
  Body: prose paragraphs wrapped at 100 characters (apply re-wraps for you), ending with a
  paragraph starting "Why:". Keep the id and the Why when replacing. Title is the heading text.
  Budget: at most 200 lines AND at most 12000 characters, counting the one generated
  `More: sisi rule N` pointer line per rule, and a cycle must not increase the
  characters unless it names in "shortens" which existing rule text gets shorter or is replaced
  (required whenever a rule is added or the book would grow in characters); never past the budget.
  Rule numbers in lessons ("rule 5") mean the numbered list in the brief, which maps number to id.

Notes - one object per decision; the same lesson may appear several times (split, or fold+set-when):
  merge           {"lesson": A, "action": "merge", "merged_into": B} - only when A and B request
                  the SAME change (not merely the same topic). Merge the newer/ narrower into the
                  older or more general one (B). A becomes superseded; B keeps its own text and
                  its occurrence count unchanged. Superseded lessons need no further action.
  fold-into-rule  {"lesson": A, "action": "fold-into-rule", "into": "rule-id" or ["id", ...]}
                  The lesson is marked folded into that rule; its strength rises to at least 2.
  fold-into-entry {"lesson": A, "action": "fold-into-entry", "into": "id" or ["id", ...],
                  "note": "optional text"} - appends one field-note bullet to notes/<id>.md:
                  "- YYYY-MM-DD: <the lesson's change, or `note` when given> (aim: <aim>; seen
                  <count> times; lesson <id>)", or, when the lesson has a short line and no
                  explicit `note` was given, "- YYYY-MM-DD: <short> (seen <count> times; lesson
                  <id>; full text: sisi lessons show <id>)". An explicit `note` always wins.
                  Marks the lesson applied / field-note / folded_into=<id>. To split a compound
                  lesson, use two notes objects with the same lesson, different `into` and
                  different `note` text each.
  create-entry    {"lesson": A, "action": "create-entry", "into": "new-id",
                  "entry_kind": "recipe|verifier", "entry_text": "<full file text>"}
                  Creates a personal recipe or verifier entry in the overlay from the lesson,
                  validated by the existing library lint (docs/verifier-format.md). Use it when a
                  lesson asks for a recipe/entry that does not exist (e.g. "Add a recipe 'x'").
                  If a full, lint-clean entry is too large for this cycle, use keep-as-draft
                  instead and say why; do not fold into a poor-matching existing entry.
  keep-as-draft   {"lesson": A, "action": "keep-as-draft", "reason": "why"} - keeps it as a draft
                  recipe note (shown by `sisi done for` when its words match), nothing else.
  set-when        {"lesson": A, "action": "set-when", "when": "at least 5 terms"} - only sets
                  the lesson's when-terms; nothing else changes.
  set-short       {"lesson": A, "action": "set-short", "short": "...", "topic": "..."} - writes
                  the lesson's one-line plain-language summary and its topic. Limits: short is
                  one sentence, at most 140 characters, no trailing ellipsis, no newline; topic
                  is 1 to 3 lower-case words, at most 30 characters. Reuse a topic already in
                  use (the brief lists them) instead of inventing a near-duplicate. Every active
                  lesson the brief lists as lacking a short line or topic needs a set-short in
                  the file; `sisi cycle check` refuses a file that omits one, naming the lesson
                  (lessons this file retires, withdraws or merges away are exempt). set-short may
                  be combined with other actions on the same lesson. When the lesson is already
                  folded into an entry, its default field-note bullet is rewritten to the short
                  form; a bullet that came from an explicit `note` is left alone.
  set-scope       {"lesson": A, "action": "set-scope", "scope": "core|user|project",
                  "project": "<project id, required when project>"} - decides the tier. Two
                  questions: (a) does it apply to all projects where sisi may be used?
                  (b) would it be useful to every user who installs sisi? Both yes: core -
                  examples: "write delimited files with a quoting writer"; "use what the host
                  tool already provides instead of building a replacement". (a) yes, (b) no:
                  user - examples: "always ask this owner questions as options with a
                  recommendation"; "prefer this owner's flat-rate plans over per-use ones".
                  (a) no: project - examples: "this product's settings page keeps advanced
                  options behind one toggle"; "this app uses the left control key for search".
                  Core and user require the delivered text (change, short, when) to be
                  universal: naming the project it came from is refused (the name sisi itself
                  is always exempt), though moment and cause may name it freely. project moves
                  the lesson into that project's handover pile; it is never folded into the
                  rulebook or general notes. Every not-yet-tiered lesson in the brief needs one;
                  retire/withdraw/merge exemptions as elsewhere. A core item takes effect at
                  once through the overlay and is queued for the product (`sisi promote`); on
                  a developer install, promote writes it into the product source tree as an
                  ordinary uncommitted edit and drops the personal copy once the product
                  contains it.
  keep            {"lesson": A, "action": "keep"} - leave it; clears its waiting flag.
  retire          leave the active notes. Only when fully folded and quiet: folded into a rule,
                  entry or enforced check, listed/read at least 20 times, and 0 recurrences after
                  first being listed. Folding in this cycle does not make it quiet: fold now,
                  keep it, and retire it in a later cycle once it is quiet. (sisi also retires
                  such lessons itself at 20 showings.)
  withdraw        it made things worse or keeps recurring at strength 3; same wording is not
                  re-learned. Tool lessons: cannot be done in a cycle (they are changes to sisi
                  itself) - leave them in `sisi backlog` untouched, except merging a duplicate.

Patterns - lessons generalise upward. A pattern is the general failure of thinking behind
  several incidents, stated in one line that would apply to unrelated work. Patterns must
  stay few: reuse, merge, and promote to the rulebook as strategic behaviours.
  set-pattern     {"lesson": A, "action": "set-pattern", "pattern_id": N} reuses pattern N;
                  {"lesson": A, "action": "set-pattern", "pattern": "<one line>"} names a new
                  one (same refusals as `sisi retro --pattern`: it names no project and does
                  not restate the incident). Every active lesson the brief lists as lacking a
                  pattern needs one; lessons this file retires, withdraws or merges away are
                  exempt. Exact duplicate statements reuse the existing pattern.
  "patterns" (top level):
                  {"pattern": A, "action": "merge", "into": B} - near-duplicate A folds into
                  B; A's lessons move to B and A is deleted.
                  {"pattern": A, "action": "set-statement", "statement": "..."} - sharpen it.
                  {"pattern": A, "action": "fold-into-rule", "into": "rule-id"} - the pattern
                  becomes a strategic behaviour in the rulebook; that rule must be written or
                  replaced in this file (or the rulebook rewritten), traced like any folded
                  lesson. Required in this round for a pattern explaining at least 3 lessons
                  and 6 incidents (the brief marks it READY).

Learn statements - the equivalent for `sisi learn` statements ("learn" at the top level):
  {"text": "<the exact statement>", "action": "set-scope", "scope": "core|user|project",
   "project": "<project id, when project>"} - every unscoped statement in the brief needs one.
  project moves it to that project's handover pile, out of the global store. Tier by the two
  questions at set-scope above: a statement about how sisi itself should behave for everyone
  is core ("sisi should anticipate what is needed from what was already said"; "checks, not
  advice"); how this owner wants work done is user ("always ask questions as options with a
  recommendation"; "never set up scheduled jobs or timers"); a fact about one product is
  project ("this product's settings page keeps advanced options behind one toggle"; "this app
  uses the left control key for search").

Enforced checks - write none for lessons below strength 3. One per strength-3 NEEDS A CHECK:
  command: {"lesson": 3, "type": "command", "cmd": "program + args that exist here",
    "expect": {"exit": 0} (integer exit code required; runs only in trusted projects),
    "timeout_s": 30 (seconds, optional)}
  contract-requirement: {"lesson": 4, "type": "contract-requirement",
    "when": "word in the contract goal/claims that triggers it",
    "require_kind": "general|concurrency|parsing|money|state-machine|migration|ui",
    "max_rung": 2 (optional, 1-6: the required check must be at this rung or stronger)}
  Complete examples are the two objects above.

Documents - every round ends with a whole-document edit. The things agents read are documents:
  the rulebook ("rulebook"), each recipe ("recipe:<id>") and each technique ("verifier:<id>").
  The brief prints, for every document that has appended field notes, whose personal copy no
  longer matches the product text it was made from (a re-merge), or that has had no
  whole-document review for the configured number of rounds, its full current text and the
  lessons folded into it. Existing field-note files are listed this way until rewritten; until
  then they keep being shown as before.
  {"doc", "action": "reviewed", "reason"} - the structure is already right; say why in one line.
  {"doc", "action": "rewrite", "text", "trace"} - the full new text, written as a proper
  document by the editorial standard in the brief: one instruction per bullet or sentence; most
  important first; related instructions under one heading; no duplicates; imperative, concrete,
  plain words; each rule keeps its Why; exceptions beside what they qualify; no history.
  A folded lesson becomes part of the document's own text where it belongs (in a recipe: Done
  means, Checks, or Common false finishes), never a dated appended bullet. The personal version
  lives in the overlay and records the product hash it was derived from.
  trace: one entry per lesson folded into the document or already traced into it. Nothing may
  be lost: {"lesson", "fragment"} - the exact sentence or bullet in the new text that carries
  it (whitespace-normalised; it must occur); {"lesson", "disposition": "moved", "to", "fragment"}
  - it lives in that other document now, as that fragment there; {"lesson", "disposition":
  "merged", "merged_with", "fragment"} - both lessons point at the same fragment; {"lesson",
  "disposition": "retired", "reason"} - only under the retirement rule for retire above.
  The trace map is stored beside the document, not in the text agents load; `sisi lessons
  show ID`, `sisi rule N` and `sisi done ID --trace` print where a lesson lives.
  A rewrite is refused when: the rulebook would pass its line or character budget; a rule lacks
  its heading with id, its Why, or its generated More line; a recipe or technique fails the
  library lint; a line stays over the house width after wrapping; a bullet over the configured
  length ends more than one sentence; or the text holds a dated journal-style bullet. For the
  rulebook, every existing rule id must survive or be named in "rule_merges"
  ({"from", "into"}) with the survivor present, and any growth needs "shortens" as for rules.
  "rule_order" (top level, or the order of a rulebook rewrite) reorders the book: it names
  every rule id exactly once; ids stay stable, numbers follow the order, and stored data
  refers to rules by id, never by number. `sisi cycle status` shows, per rewritten document,
  recurrences of its lessons before and after the rewrite, and flags a rewrite followed by more.

Learned-notes limit: counts length(change) of active strength-1 loose learned notes only
(limit 4000 characters). It still counts `change`, not `short`: it is about lesson content not
yet folded. Delivery budgets for printed headings (session start, the other-lessons list) count
the short line when one is present, because that is what is printed; without one they count a
word-boundary cut of the change. Folded, strengthened, retired, withdrawn and tool-backlog
lessons do not count toward the learned-notes limit. fold-into-entry, fold-into-rule, merge,
retire, withdraw and writing an enforced check all reduce it; keep, set-when and set-short do not.
"""

def cycle_file_path():
    return os.path.join(paths.state(), "cycle.json")


def _into_list(e):
    v = e.get("into")
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def _suggest(bad, valid):
    close = difflib.get_close_matches(str(bad), sorted(valid), n=3, cutoff=0.4)
    return (" Closest valid: %s." % ", ".join(close)) if close else ""


def brief_text():
    con = retro.connect()
    try:
        retro.ensure_effects(con)
        st = due_state(con)
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM lessons ORDER BY status IN ('open','applied') DESC, COALESCE(strength,1) DESC, count DESC, id")]
        shown = {r["id"]: retro.shown_count(con, r["id"]) for r in rows}
        listed = {r["id"]: retro.listed_count(con, r["id"]) for r in rows}
        readn = {r["id"]: retro.read_count(con, r["id"]) for r in rows}
        rec = {r["id"]: retro.recurrences_after_shown(con, r) for r in rows}
        sight = {r["id"]: retro.sightings_count(con, r["id"]) for r in rows}
        base = base_version(con)
        before = measures(con)
        missing_short = [r for r in rows if r["status"] in retro.ACTIVE
                         and (not str(r.get("short") or "").strip() or not str(r.get("topic") or "").strip())]
        topics_in_use = _topics_in_use(con)
        unscoped = [r for r in rows if r["status"] in retro.ACTIVE
                    and retro._get(r, "scope") in (None, "", "unscoped", "unscoped-tier", "everywhere")]
        unscoped_repos = {}
        for r in unscoped:
            o = con.execute("SELECT repo, cwd FROM occurrences WHERE lesson_id=? ORDER BY id LIMIT 1", (r["id"],)).fetchone()
            unscoped_repos[r["id"]] = (o[0] or o[1]) if o else None
        try:
            docs_required = documents.required_documents(con)
            docs_folded = {d["doc"]: documents.folded_lesson_ids(con, d["kind"], d["id"])
                           for d in docs_required}
        except Exception:
            docs_required, docs_folded = [], {}
        try:
            all_patterns = retro.patterns(con)
            pattern_trends = {p["id"]: retro.pattern_recurrence_trend(con, p) for p in all_patterns}
        except Exception:
            all_patterns, pattern_trends = [], {}
        missing_pattern = [r for r in rows if r["status"] in retro.ACTIVE and not r.get("pattern_id")]
        from . import scope as _scope_mod
        learn_unscoped = []
        for _lrec in store.read("learn"):
            if _lrec.get("scope") not in _scope_mod.SCOPES and (_lrec.get("text") or "").strip():
                learn_unscoped.append(_lrec)
    finally:
        con.close()
    from . import verifiers as V
    try:
        _, eff_rules = overlay.effective()
    except Exception:
        eff_rules = []
    recipes = [e for e in V.load_recipes() if e["header"]]
    vers = [e for e in V.load_verifiers() if e["header"]]
    out = ["sisi learning cycle: consolidation brief", ""]
    bad = [r for r in cycle_records() if flagged(r)]
    if bad:
        out += ["FIRST: these past cycles made the measured work worse. Revert or repair one before "
                "anything else (`sisi cycle revert %s` undoes it exactly):" % bad[-1]["id"]]
        out += ["  %s (%s): %s" % (r["id"], r.get("ts"), r.get("summary") or "") for r in bad] + [""]
    out += ["Due: " + ("; ".join(st["reasons"]) if st["due"] else "not due by the counters; a cycle may still help"),
            "Base version (copy into your file): %s" % base,
            "Write your file to: %s  then `sisi cycle check FILE`, then `sisi cycle apply FILE`. "
            "Full format: `sisi cycle help`." % cycle_file_path(),
            "This file covers only the lessons below; lessons recorded since are left for the next "
            "cycle and do not fail the apply. Reading lessons (`sisi lessons show ID`) does not stale the base.",
            "Rulebook: %s lines (budget %d), %s characters (budget %d). It must not grow in "
            "characters unless `shortens` names what is removed; never past either budget. "
            "Rules are re-wrapped to 100 chars on apply."
            % (before["rulebook_lines"], overlay.MAX_LINES, before.get("rulebook_chars"), overlay.MAX_CHARS),
            "Learned notes: %d of %d characters counted (active strength-1 loose learned notes "
            "only, length of each lesson's change; folded/strengthened/tool lessons do not count). "
            "fold-into-entry, fold-into-rule, merge, retire, withdraw and enforced checks reduce it."
            % (st.get("notes_chars", 0), retro.NOTES_LIMIT_CHARS), "",
            "Rules (number = what 'rule 5' means; choose folds by this list, full text in %s):" % paths.generated()]
    for i, r in enumerate(eff_rules, 1):
        out.append("  %d. %s - %s" % (i, r["id"], r["title"]))
    out.append("Recipes (fold by reading applies-to, not by word matching):")
    for e in sorted(recipes, key=lambda x: x["id"]):
        out.append("  %s - %s" % (e["id"], (e.get("applies_to") or e.get("title") or "")[:110]))
    out.append("Verifier entries (valid fold/create targets): " +
               ", ".join(sorted(e["id"] for e in vers)))
    out += ["", "Lessons (change chars = its size toward the notes limit when loose):"]
    active_text = sum(len(r["change"] or "") + len(r["moment"] or "") + len(r["cause"] or "")
                      for r in rows if r["status"] in retro.ACTIVE)
    if active_text > BRIEF_TEXT_BUDGET:
        out.append("Lesson text beyond the brief's %d-character text budget is truncated; run "
                   "`sisi lessons show ID` for the full text of any lesson." % BRIEF_TEXT_BUDGET)
    remaining = [BRIEF_TEXT_BUDGET]
    for r in rows:
        out.append("#%-4d %-10s %-9s s%d x%-3d listed %-3d read %-3d rec %-3d %-13s change %d chars"
                   % (r["id"], r["status"], r["change_kind"], r["strength"] or 1, r["count"], listed[r["id"]],
                      readn[r["id"]], rec[r["id"]], r["effect"] or "-", len(r["change"] or "")))
        if r["status"] not in retro.ACTIVE:
            out.append("       (history; no action needed) change: %s" % " ".join((r["change"] or "").split())[:120])
            continue
        need = len(r["change"] or "") + len(r["moment"] or "") + len(r["cause"] or "")
        full = need <= remaining[0]
        remaining[0] -= need if full else 0
        def show(label, text, _full=full, _id=r["id"]):
            t = " ".join((text or "").split())
            if _full:
                out.append("       %s: %s" % (label, t))
            else:
                out.append("       %s: %s [truncated - `sisi lessons show %d` for the full text]" % (label, t[:200], _id))
        if full:
            show("change", r["change"])
            show("moment", r["moment"])
            show("cause", r["cause"])
        else:
            t = " ".join((r["change"] or "").split())
            out.append("       change: %s [truncated - `sisi lessons show %d` for the full text, moment and cause]" % (t[:160], r["id"]))
        if full:
            out.append("       when: %s" % (r["when_terms"] or "MISSING - add at least 5 terms with set-when or any note's when"))
        elif not r["when_terms"]:
            out.append("       when: MISSING - add at least 5 terms with set-when or any note's when")
        out.append("       target: %s  folded_into: %s" % (r["target"] or "-", r["folded_into"] or "-"))
        if r["status"] in retro.ACTIVE and not r.get("pattern_id"):
            out.append("       pattern: MISSING - add a set-pattern for this lesson (reuse a pattern below with pattern_id, or name a new one)")
        if r["status"] in retro.ACTIVE and (not str(r.get("short") or "").strip() or not str(r.get("topic") or "").strip()):
            out.append("       short: MISSING - add a set-short for this lesson (short at most %d characters, topic at most %d)" % (retro.SHORT_MAX, retro.TOPIC_MAX))
        elif r.get("short"):
            out.append("       short: %s (topic: %s)" % (r["short"], r.get("topic") or "-"))
        if listed[r["id"]] >= 5 and readn[r["id"]] == 0 and rec[r["id"]] > 0 and r["status"] in retro.ACTIVE:
            out.append("       LISTED %d TIMES, NEVER READ, STILL RECURS: rewrite the start of its change and its when-terms" % listed[r["id"]])
        if sight[r["id"]]:
            out.append("       plus %d unconfirmed sighting(s) (merge candidates)" % sight[r["id"]])
        if (r["strength"] or 1) >= 3 and not r["check_json"] and r["status"] in retro.ACTIVE:
            out.append("       NEEDS A CHECK: strength 3 - write one enforced check (see `sisi cycle help`). "
                       "Write no enforced check for lessons below strength 3.")
    out += ["", "Current rulebook (what every agent loads): %s lines, %s characters; full text at %s"
            % (before["rulebook_lines"], before.get("rulebook_chars"), paths.generated()), ""]
    missing = [r["id"] for r in rows if r["status"] in retro.ACTIVE and not r["when_terms"]]
    if missing:
        out += ["Lessons with no when-terms yet: " + ", ".join("#%d" % i for i in missing), ""]
    out += ["Short lines: every active lesson lacking a short line or topic needs a set-short in your file; "
            "`sisi cycle check` will refuse a file that omits one, naming the lesson. Write each short as "
            "one sentence in plain words, an instruction, at most %d characters, no trailing ellipsis, no "
            "newline. Topic: 1 to 3 lower-case words, at most %d characters. Reuse a topic already in use "
            "when it fits instead of inventing a near-duplicate. set-short may be combined with other "
            "actions on the same lesson (fold, keep, set-when and the rest)."
            % (retro.SHORT_MAX, retro.TOPIC_MAX),
            "Topics already in use: " + (", ".join(topics_in_use) if topics_in_use else "(none yet)"),
            "Lessons lacking a short line or topic: " +
            (", ".join("#%d" % r["id"] for r in missing_short) if missing_short else "(none)"), ""]
    if unscoped or learn_unscoped:
        out += ["", "Scope cleanup (tier backfill): every item below has no tier yet (recorded before "
                "tiers, or with the old everywhere scope). Give each a set-scope (lessons: "
                "{\"lesson\": A, \"action\": \"set-scope\", \"scope\": \"core|user|project\", "
                "\"project\": \"<id, when project>\"}; learn statements: a \"learn\" entry, see "
                "`sisi cycle help`). Two questions: (a) does it apply to all projects where sisi may "
                "be used? (b) would it be useful to every user who installs sisi? Both yes: core "
                "(\"write delimited files with a quoting writer\"; \"use what the host tool already "
                "provides\"). (a) yes, (b) no: user (\"always ask questions as options with a "
                "recommendation\"; \"never set up scheduled jobs\"). (a) no: project (\"this "
                "product's settings page keeps advanced options behind one toggle\"; \"this app uses "
                "the left control key for search\"), which moves the item to that project's handover "
                "pile. A lesson whose instruction is universal stays global even when its history "
                "names a project, and an item is never project merely for being recorded in the sisi "
                "repository - how sisi itself should behave is core. A cleanup-only round is a good "
                "round (`sisi cycle --now`)."]
        for r in unscoped:
            out.append("  lesson #%d recorded in %s: %s" % (r["id"], unscoped_repos.get(r["id"]) or "(unknown repository)",
                                                            " ".join(str(r.get("change") or "").split())[:120]))
        for rec in learn_unscoped:
            pid = ""
            try:
                if rec.get("cwd"):
                    pid = " (project id there: %s)" % _scope_mod.project_id(rec["cwd"])
            except Exception:
                pass
            out.append("  learn statement recorded in %s%s: %r" % (rec.get("cwd") or "(unknown repository)", pid,
                                                                   " ".join(str(rec["text"]).split())[:120]))
        out.append("")
    out += ["", "Patterns (lessons generalise upward: a handful of general failures of thinking, "
            "not one rule per incident). Every active lesson lacking a pattern needs a set-pattern "
            "{\"lesson\": A, \"action\": \"set-pattern\", \"pattern_id\": N} reusing one below, or "
            "{\"lesson\": A, \"action\": \"set-pattern\", \"pattern\": \"<one line>\"} naming a new "
            "one - patterns must stay few, so reuse before inventing. Merge near-duplicates with a "
            "top-level \"patterns\" entry {\"pattern\": A, \"action\": \"merge\", \"into\": B}. A "
            "pattern explaining at least %d lessons and %d incidents (marked READY) must be written "
            "into the rulebook as a strategic behaviour in this round: {\"pattern\": N, \"action\": "
            "\"fold-into-rule\", \"into\": \"<rule-id>\"} in \"patterns\", with that rule written or "
            "replaced in this file, its lessons traced like any folded lesson. Set or sharpen a "
            "statement with {\"pattern\": N, \"action\": \"set-statement\", \"statement\": \"...\"}."
            % (retro.PATTERN_RULE_MIN_LESSONS, retro.PATTERN_RULE_MIN_OCCURRENCES),
            "Patterns so far:"]
    if not all_patterns:
        out.append("  (none yet)")
    for _p in all_patterns:
        _flag = " READY FOR THE RULEBOOK" if retro.pattern_ready_for_rule(_p) else ""
        out.append("  pattern %d: %s%s" % (_p["id"], _p["statement"], _flag))
        out.append("    %d lesson(s), %d incident(s); recurrence %s; folded into: %s; lessons: %s"
                   % (_p["n_lessons"], _p["incidents"], pattern_trends.get(_p["id"], "?"),
                      _p.get("folded_into") or "-", ", ".join("#%d" % i for i in _p["lessons"]) or "-"))
    out.append("Lessons lacking a pattern: " +
               (", ".join("#%d" % r["id"] for r in missing_pattern) if missing_pattern else "(none)"))
    try:
        from . import release as _rel
        _core_lessons, _core_stmts = _rel.core_items()
        _dev_src = _rel.dev_source()
    except Exception:
        _core_lessons, _core_stmts, _dev_src = [], [], None
    if _core_lessons or _core_stmts:
        out += ["", "Core items waiting for the product (`sisi promote` lists them): in force for "
                "this user through the overlay, not yet in sisi itself."]
        for _r in _core_lessons:
            out.append("  lesson #%d [%s] %s" % (_r["id"], _r.get("change_kind") or "",
                                                 " ".join(str(_r.get("change") or "").split())[:110]))
        for _t in _core_stmts:
            out.append("  statement: %r" % _t[:110])
        if _dev_src:
            out.append("This is a developer install (source %s): after folding a core item into a "
                       "rule, recipe or technique, run `sisi promote lesson:N --apply` (or "
                       "`sisi promote <id> --apply`) to write it into the product source tree as "
                       "an ordinary uncommitted edit; the personal copy is dropped only once the "
                       "product contains the text." % _dev_src)
        else:
            out.append("Not a developer install: `sisi promote --export` writes a contribution "
                       "file (universal text only) the user may send upstream. Nothing is sent "
                       "anywhere automatically.")
        out.append("")
    out += ["", "Documents for whole-document review (every round ends with a whole-document edit):",
            "Editorial standard - "
            + " ".join(documents.EDITORIAL_STANDARD),
            "For each document below your file needs a documents entry: a rewrite (the full new "
            "text, with each folded lesson integrated where it belongs and a trace entry giving "
            "the exact fragment that carries it - or a moved/merged/retired disposition), or a "
            "reviewed entry with a one-line reason why its structure is already right. "
            "`sisi cycle check` refuses a file that skips a listed document, a rewrite that "
            "leaves a lesson untraced, and any text that fails the structure checks (budgets, "
            "headings and Why, the library lint, the %d-character house width after wrapping, "
            "run-on bullets, dated journal bullets). A document is listed when it has appended "
            "field notes, when its personal copy no longer matches the product text it was made "
            "from (re-merge it), or when it has had no whole-document review for %d rounds."
            % (overlay.HOUSE_WIDTH, documents.review_every_rounds())]
    if not docs_required:
        out.append("  (none this round)")
    _rows_by_id = {r["id"]: r for r in rows}
    for _d in docs_required:
        out.append("")
        out.append("Document %s - %s" % (_d["doc"], "; ".join(_d["reasons"])))
        for _st in _d.get("statements") or []:
            out.append("  statement to trace (the owner's words): %r - in the rewrite, carry it in "
                       "one plain line followed by this quote, and trace {\"statement\": ..., "
                       "\"fragment\": \"<that line>\"}" % _st)
        for _lid in docs_folded.get(_d["doc"], []):
            _r = _rows_by_id.get(_lid)
            if _r:
                out.append("  lesson #%d folded here: %s (full text: sisi lessons show %d)"
                           % (_lid, " ".join(str(_r.get("change") or "").split()), _lid))
                if _r.get("short"):
                    out.append("    short: %s" % " ".join(str(_r["short"]).split()))
        if _d["kind"] != "rulebook":
            _notes = retro.notes_for(_d["id"])
            if _notes:
                out.append("  appended field notes (integrate these, do not copy the dates):")
                out += ["  " + _l for _l in _notes.splitlines()]
        out.append("  ----- %s: current text -----" % _d["doc"])
        out += documents.effective_text(_d["kind"], _d["id"]).rstrip("\n").split("\n")
        out.append("  ----- end of %s -----" % _d["doc"])
    out += ["Do this, in order:",
            "1. Fold each loose lesson into the recipe/entry whose applies-to (above) fits its kind of "
            "work, or lift several into one general rule. fold-into-entry appends a field note (see help). "
            "For a lesson naming a recipe/entry that does not exist, use create-entry with a lint-clean "
            "file, or keep-as-draft with a reason if that is too large for this cycle - never fold into a poor match.",
            "2. Merge only lessons requesting the same change (not just the same topic), into the older "
            "or more general one; the survivor keeps its text and occurrence count. Superseded, retired "
            "and withdrawn lessons need no action.",
            "3. Tool lessons (kind tool) cannot be done in a cycle: leave them in `sisi backlog` untouched, except merging a duplicate. When a tool lesson's change has been built, close it outside the cycle file with `sisi lessons set ID --status applied`; it then leaves the backlog and the digest stops calling it not built yet.",
            "3b. Project-scoped lessons cannot be folded into the rulebook or the general recipe/technique notes in a cycle, and unscoped items each need a set-scope above (scoping to a project moves the item to that project's handover pile).",
            "4. Rules: keep id and Why, format per help; name in `shortens` which existing rule text gets shorter or is replaced whenever a rule is added or the book would grow in characters.",
            "5. For each NEEDS A CHECK lesson write one enforced check (help has fields and examples); none below strength 3.",
            "6. For every lesson listed above as lacking a short line or topic, add a set-short (it may sit "
            "beside its fold, keep or set-when entry). Reuse a topic already in use when it fits.",
            "6b. Patterns: give every lesson lacking one a set-pattern (reuse a listed pattern first), merge "
            "near-duplicate patterns, and write each READY pattern into the rulebook as one strategic "
            "behaviour (fold-into-rule in \"patterns\", with the rule in this file). The rulebook grows "
            "by strategic behaviours, not by incident fixes.",
            "7. Retire only what is fully folded and quiet (folded, at least 20 listed/read, 0 recurrences "
            "after first listed) - folding now does not make it quiet, so fold and keep, retire next cycle. "
            "Withdraw what made things worse. set-when only sets when-terms. Keep the rest.",
            "8. End with the whole-document edit above: for every listed document, rewrite it as a "
            "proper document by the editorial standard (lessons integrated into its own sections, "
            "each traced to the fragment that carries it) or mark it reviewed with a reason. "
            "Nothing folded may be lost: moved, merged and retired lessons are named as such.",
            "Every changed rule keeps its id and ends with its Why. Never ask the human anything.", "", FORMAT_DOC]
    return "\n".join(out) + "\n"


# ---- validate and apply ---------------------------------------------------------
def _known_commands():
    from . import cli
    cmds = set(re.findall(r"\bsisi ([a-z][a-z-]*)", cli.HELP))
    return cmds


def _exe_exists(cmd):
    try:
        parts = [p for p in shlex.split(cmd) if "=" not in p.split("/")[0] or "/" in p]
    except ValueError:
        return False
    parts = [p for p in shlex.split(cmd) if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", p)]
    if parts and parts[0] == "env":
        parts = parts[1:]
    if not parts:
        return False
    exe = parts[0]
    return bool(shutil.which(exe)) or ("/" in exe and os.path.isfile(exe) and os.access(exe, os.X_OK)) \
        or exe in ("true", "false", "echo", "test", "sisi")


def _lesson_ids_in(doc):
    ids = set()
    for key in ("notes", "enforced"):
        for e in doc.get(key) or []:
            if isinstance(e, dict):
                for k in ("lesson", "merged_into"):
                    if isinstance(e.get(k), int):
                        ids.add(e[k])
    for e in doc.get("documents") or []:
        if isinstance(e, dict):
            for t in e.get("trace") or []:
                if isinstance(t, dict):
                    for k in ("lesson", "merged_with"):
                        if isinstance(t.get(k), int):
                            ids.add(t[k])
    return ids


def _missing_short_at_base(doc, con):
    """[(lesson_id, snapshot)] active at the brief whose short line or topic was missing then.

    Lessons recorded since the brief are not included: they are left for the next cycle and
    must not make this file fail (see _check_base)."""
    old = _load_snapshot(doc.get("base")) if isinstance(doc, dict) and doc.get("base") else None
    out = []
    if old and isinstance(old.get("lessons"), dict):
        for lid_s, v in old["lessons"].items():
            if not isinstance(v, dict) or v.get("status") not in retro.ACTIVE:
                continue
            if not str(v.get("short") or "").strip() or not str(v.get("topic") or "").strip():
                try:
                    out.append((int(lid_s), v))
                except ValueError:
                    continue
        return sorted(out)
    try:
        for r in con.execute("SELECT * FROM lessons WHERE status IN ('open','applied') ORDER BY id"):
            d = dict(r)
            if not str(d.get("short") or "").strip() or not str(d.get("topic") or "").strip():
                out.append((d["id"], d))
    except Exception:
        pass
    return out


def _topics_in_use(con):
    try:
        return sorted({str(r[0]).strip() for r in con.execute(
            "SELECT DISTINCT topic FROM lessons WHERE topic IS NOT NULL AND trim(topic)<>''") if r[0] and str(r[0]).strip()})
    except Exception:
        return []


def static_validate(doc, con):
    """Every refusal reason that can be known before writing anything. Empty means applicable so far."""
    errs = []
    if not isinstance(doc, dict):
        return ["the cycle file must be one JSON object"]
    if doc.get("version") != 1:
        errs.append("version must be 1")
    if not doc.get("base"):
        errs.append("missing base: copy the base version printed by `sisi cycle` (it proves which state you read)")
    else:
        errs.extend(_check_base(doc["base"], con))
    have = {r[0] for r in con.execute("SELECT id FROM lessons")}
    for lid in sorted(_lesson_ids_in(doc) - have):
        errs.append("no lesson with id %d" % lid)
    base_rule_ids = {r["id"] for r in overlay.base_rules()[1]}
    over_ids = set(overlay.overlay_rules())
    known = _known_commands()
    for e in doc.get("rules") or []:
        if not isinstance(e, dict) or not e.get("id") or not e.get("title") or not e.get("body"):
            errs.append("each rule needs id, title and body: %r" % (e,))
            continue
        rid, act = e["id"], e.get("action")
        if act not in ("add", "replace"):
            errs.append("rule %s: action must be add or replace" % rid)
        if act == "add" and rid in base_rule_ids | over_ids:
            errs.append("rule %s already exists; use replace" % rid)
        if act == "replace" and rid not in base_rule_ids | over_ids:
            errs.append("no rule %s to replace" % rid)
        if "Why" not in e["body"]:
            errs.append("rule %s: the body must keep its Why (a line starting 'Why:')" % rid)
        for m in sorted(set(re.findall(r"`sisi ([a-z][a-z-]*)", e["body"]))):
            if m not in known:
                errs.append("rule %s names `sisi %s`, which is not a command (see `sisi help`)" % (rid, m))
        try:
            overlay.parse_rule_file("## %s\n\n%s\n" % (e["title"], e["body"]), rid)
        except overlay.OverlayError as ex:
            errs.append("rule %s: %s" % (rid, ex))
    for rid in doc.get("disable_rules") or []:
        if rid not in base_rule_ids | over_ids:
            errs.append("no rule %s to disable.%s" % (rid, _suggest(rid, base_rule_ids | over_ids)))
    kinds = {}
    scopes = {}
    try:
        kinds = {r[0]: r[1] for r in con.execute("SELECT id, change_kind FROM lessons")}
        scopes = {r[0]: (r[1] or "unscoped") for r in con.execute("SELECT id, scope FROM lessons")}
    except Exception:
        pass
    from . import scope as _scmod
    for e in doc.get("notes") or []:
        if not isinstance(e, dict):
            continue
        lid, act = e.get("lesson"), e.get("action")
        if scopes.get(lid) == "project" and act in ("fold-into-rule", "fold-into-entry", "create-entry"):
            errs.append("lesson %s: project-scoped items can never be folded into the rulebook or the "
                        "general recipe/technique notes in a cycle" % lid)
        if act == "set-scope":
            if e.get("scope") not in _scmod.SCOPES and e.get("scope") != "everywhere":
                errs.append("lesson %s: set-scope needs scope core|user|project" % lid)
            elif e["scope"] == "project" and not (e.get("project") or "").strip():
                errs.append("lesson %s: set-scope to project needs \"project\" naming the project id" % lid)
            elif e["scope"] in ("core", "user", "everywhere") and isinstance(lid, int) and lid in kinds:
                try:
                    row = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
                    occ = con.execute("SELECT repo FROM occurrences WHERE lesson_id=? ORDER BY id LIMIT 1", (lid,)).fetchone()
                    origin = occ[0] if occ and occ[0] and os.path.isdir(occ[0]) else os.getcwd()
                    reason = _scmod.universal_refusal(
                        [e.get("short") or (row["change"] if row else ""), row["change"] if row else "",
                         e.get("when") or (row["when_terms"] if row else "")], origin, kind=kinds.get(lid))
                    if reason:
                        errs.append("lesson %s: cannot set-scope %s: %s; rewrite it in general "
                                    "terms or scope it to its project" % (lid, e["scope"], reason))
                except Exception:
                    pass
    for e in doc.get("enforced") or []:
        if isinstance(e, dict) and scopes.get(e.get("lesson")) == "project":
            errs.append("lesson %s: project-scoped items can never be folded into the rulebook or the "
                        "general recipe/technique notes in a cycle" % e.get("lesson"))
    learn_recs = []
    try:
        learn_recs = store.read("learn")
    except Exception:
        pass
    unscoped_learn = [r for r in learn_recs if r.get("scope") not in _scmod.SCOPES and (r.get("text") or "").strip()]
    covered_learn = set()
    for e in doc.get("learn") or []:
        if not isinstance(e, dict) or e.get("action") != "set-scope":
            errs.append("each learn entry needs action set-scope: %r" % (e,))
            continue
        covered_learn.add(e.get("text"))
        if e.get("scope") not in _scmod.SCOPES and e.get("scope") != "everywhere":
            errs.append("learn %r: set-scope needs scope core|user|project" % (e.get("text"),))
        elif e["scope"] == "project" and not (e.get("project") or "").strip():
            errs.append("learn %r: set-scope to project needs \"project\" naming the project id" % (e.get("text"),))
        elif not any(r.get("text") == e.get("text") for r in unscoped_learn):
            errs.append("learn %r: no unscoped learn statement with that exact text" % (e.get("text"),))
        elif e["scope"] in ("core", "user", "everywhere"):
            origin = next((r.get("cwd") for r in unscoped_learn if r.get("text") == e.get("text")), None)
            if origin and os.path.isdir(origin):
                reason = _scmod.universal_refusal([e.get("text")], origin)
                if reason:
                    errs.append("learn %r: cannot set-scope core/user: %s" % (e.get("text"), reason))
    if isinstance(doc, dict) and doc.get("base"):
        old = _load_snapshot(doc["base"])
        if old and isinstance(old.get("learn_unscoped"), list):
            for rec in old["learn_unscoped"]:
                if rec.get("text") and rec["text"] not in covered_learn:
                    errs.append("learn statement %r: missing set-scope - add {\"text\": ..., \"action\": "
                                "\"set-scope\", \"scope\": \"core|user|project\"}" % (rec["text"],))
    for e in doc.get("notes") or []:
        if not isinstance(e, dict) or e.get("action") not in ACTIONS:
            errs.append("each note needs an action in %s: %r" % (", ".join(ACTIONS), e))
            continue
        lid = e.get("lesson")
        if kinds.get(lid) == "tool" and e["action"] not in ("merge", "keep", "keep-as-draft", "set-when", "set-short", "set-scope", "set-pattern"):
            errs.append("lesson %s: tool lessons cannot be done in a cycle (they change sisi itself); "
                        "leave them in `sisi backlog` untouched, except merging a duplicate" % lid)
        if e["action"] == "set-pattern":
            _have_pats = {}
            try:
                _have_pats = {p["id"]: p for p in retro.patterns(con)}
            except Exception:
                pass
            if e.get("pattern_id") is not None:
                if e["pattern_id"] not in _have_pats:
                    errs.append("lesson %s: set-pattern names pattern %r, which does not exist "
                                "(see the patterns listed in the brief)" % (lid, e.get("pattern_id")))
            elif (e.get("pattern") or "").strip():
                try:
                    row = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
                    occ = con.execute("SELECT repo FROM occurrences WHERE lesson_id=? ORDER BY id LIMIT 1", (lid,)).fetchone()
                    origin = occ[0] if occ and occ[0] and os.path.isdir(occ[0]) else os.getcwd()
                    reason = retro.pattern_refusal(e["pattern"], row["change"] if row else "", origin,
                                                   row["moment"] if row else None)
                    if reason:
                        errs.append("lesson %s: %s" % (lid, reason))
                except Exception:
                    pass
            else:
                errs.append("lesson %s: set-pattern needs pattern (a new one-line statement) or pattern_id (an existing one)" % lid)
        if e["action"] == "set-short":
            if e.get("short") is None and e.get("topic") is None:
                errs.append("lesson %s: set-short needs a short line and/or a topic" % lid)
            else:
                for sub in retro.validate_short_topic(e.get("short"), e.get("topic")):
                    errs.append("lesson %s: %s" % (lid, sub))
        if e["action"] == "merge" and (not isinstance(e.get("merged_into"), int) or e.get("merged_into") == lid):
            errs.append("lesson %s: merge needs merged_into naming a different lesson" % lid)
        if e["action"] in ("fold-into-rule", "fold-into-entry", "create-entry") and not _into_list(e):
            errs.append("lesson %s: %s needs into" % (lid, e["action"]))
        if e.get("when") is not None and len(retro.parse_when(e.get("when"))) < 5:
            errs.append("lesson %s: when needs at least 5 terms (synonyms included)" % lid)
        if e["action"] == "set-when" and len(retro.parse_when(e.get("when"))) < 5:
            errs.append("lesson %s: set-when needs when with at least 5 terms" % lid)
        if e["action"] == "keep-as-draft" and not (e.get("reason") or "").strip():
            errs.append("lesson %s: keep-as-draft needs a reason" % lid)
        if e["action"] == "fold-into-rule":
            valid = base_rule_ids | over_ids
            for into in _into_list(e):
                if into not in valid:
                    errs.append("lesson %s: no rule with id %r to fold into.%s" % (lid, into, _suggest(into, valid)))
        if e["action"] == "fold-into-entry":
            from . import verifiers as V
            ids = {x["id"] for x in V.load_verifiers() if x["header"]} | {x["id"] for x in V.load_recipes() if x["header"]}
            for into in _into_list(e):
                if into not in ids:
                    errs.append("lesson %s: no verifier or recipe with id %r to fold into.%s "
                                "If the lesson asks for a new one, use create-entry, or keep-as-draft with a reason"
                                % (lid, into, _suggest(into, ids)))
        if e["action"] == "create-entry":
            if e.get("entry_kind") not in ("recipe", "verifier"):
                errs.append("lesson %s: create-entry needs entry_kind recipe or verifier" % lid)
            elif not (e.get("entry_text") or "").strip():
                errs.append("lesson %s: create-entry needs entry_text (the full file, see docs/verifier-format.md)" % lid)
            else:
                for into in _into_list(e):
                    try:
                        from . import verifiers as V
                        existing = {x["id"] for x in (V.load_verifiers() if e["entry_kind"] == "verifier" else V.load_recipes()) if x["header"]}
                        if into in existing:
                            errs.append("lesson %s: %s %r already exists; fold into it instead of create-entry" % (lid, e["entry_kind"], into))
                        else:
                            overlay._put_entry(e["entry_kind"], e["entry_text"], into, False)
                    except Exception as ex:
                        errs.append("lesson %s: create-entry %r: %s" % (lid, into, ex))
    from . import contract as C
    for e in doc.get("enforced") or []:
        if not isinstance(e, dict):
            errs.append("each enforced entry must be an object: %r" % (e,))
            continue
        if e.get("type") == "command":
            if not e.get("cmd"):
                errs.append("lesson %s: a command check needs cmd" % e.get("lesson"))
            elif not _exe_exists(e["cmd"]):
                errs.append("lesson %s: command %r does not exist on this machine" % (e.get("lesson"), e["cmd"].split()[0]))
            ex = e.get("expect") or {"exit": 0}
            if not isinstance(ex.get("exit"), int):
                errs.append("lesson %s: expect.exit must be an integer" % e.get("lesson"))
        elif e.get("type") == "contract-requirement":
            if not e.get("when") or e.get("require_kind") not in C.KINDS:
                errs.append("lesson %s: a contract requirement needs when and require_kind (one of %s)"
                            % (e.get("lesson"), ", ".join(C.KINDS)))
            if e.get("max_rung") is not None and e["max_rung"] not in (1, 2, 3, 4, 5, 6):
                errs.append("lesson %s: max_rung must be 1-6" % e.get("lesson"))
        else:
            errs.append("lesson %s: enforced type must be command or contract-requirement" % e.get("lesson"))
    # Every active lesson that lacked a short line or topic in the brief needs a set-short here.
    # Lessons this same file retires, withdraws or merges away are exempt: they leave the active
    # notes, so a summary would never be shown. Lessons recorded since the brief are not in the
    # snapshot and are left for the next cycle.
    if isinstance(doc, dict) and doc.get("base"):
        notes_list = [e for e in doc.get("notes") or [] if isinstance(e, dict)]
        covered = {}
        for e in notes_list:
            if e.get("action") == "set-short" and isinstance(e.get("lesson"), int):
                covered[e["lesson"]] = e
        exempt = {e.get("lesson") for e in notes_list if e.get("action") in ("retire", "withdraw", "merge")}
        for lid, snap in _missing_short_at_base(doc, con):
            if lid in exempt:
                continue
            e = covered.get(lid) or {}
            need = []
            if not str(snap.get("short") or "").strip() and not str(e.get("short") or "").strip():
                need.append("short")
            if not str(snap.get("topic") or "").strip() and not str(e.get("topic") or "").strip():
                need.append("topic")
            if need:
                errs.append("lesson %d: missing set-short (%s) - the brief listed this lesson as needing "
                            "a short line; add {\"lesson\": %d, \"action\": \"set-short\", \"short\": \"...\", \"topic\": \"...\"}"
                            % (lid, " and ".join(need), lid))
    # Every active lesson that was unscoped in the brief needs a set-scope here (same exemption
    # as set-short: lessons this file retires, withdraws or merges away are exempt).
    if isinstance(doc, dict) and doc.get("base"):
        old = _load_snapshot(doc["base"])
        if old and isinstance(old.get("lessons"), dict):
            notes_list = [e for e in doc.get("notes") or [] if isinstance(e, dict)]
            scoped_ids = {e.get("lesson") for e in notes_list if e.get("action") == "set-scope"}
            exempt = {e.get("lesson") for e in notes_list if e.get("action") in ("retire", "withdraw", "merge")}
            for lid_s, v in old["lessons"].items():
                if not isinstance(v, dict) or v.get("status") not in retro.ACTIVE:
                    continue
                if v.get("scope") not in (None, "", "unscoped", "unscoped-tier", "everywhere"):
                    continue
                try:
                    lid = int(lid_s)
                except ValueError:
                    continue
                if lid in exempt or lid in scoped_ids:
                    continue
                errs.append("lesson %d: missing set-scope - the brief listed this lesson as unscoped; add "
                            "{\"lesson\": %d, \"action\": \"set-scope\", \"scope\": \"core|user|project\"}"
                            % (lid, lid))
    # Patterns: top-level merges / statements / rule folds, every lesson lacking a pattern at
    # the brief needs one, and a pattern past the threshold must reach the rulebook this round.
    try:
        _pats_now = {p["id"]: p for p in retro.patterns(con)}
    except Exception:
        _pats_now = {}
    _pat_folded = set()
    for e in doc.get("patterns") or []:
        if not isinstance(e, dict) or not isinstance(e.get("pattern"), int):
            errs.append("each patterns entry needs a pattern id: %r" % (e,))
            continue
        pid, act = e["pattern"], e.get("action")
        if pid not in _pats_now:
            errs.append("pattern %s: no such pattern" % pid)
            continue
        if act == "merge":
            if not isinstance(e.get("into"), int) or e["into"] == pid or e["into"] not in _pats_now:
                errs.append("pattern %s: merge needs into naming a different existing pattern" % pid)
        elif act == "set-statement":
            if not (e.get("statement") or "").strip():
                errs.append("pattern %s: set-statement needs a statement" % pid)
            else:
                _r = retro.pattern_refusal(e["statement"], "__different__", os.getcwd())
                if _r:
                    errs.append("pattern %s: %s" % (pid, _r))
        elif act == "fold-into-rule":
            _pat_folded.add(pid)
            valid = base_rule_ids | over_ids
            for into in _into_list(e):
                if into not in valid:
                    errs.append("pattern %s: no rule with id %r to fold into.%s" % (pid, into, _suggest(into, valid)))
            _rule_ids_in_file = {r.get("id") for r in doc.get("rules") or [] if isinstance(r, dict)}
            _rb_rewrite = any(isinstance(x, dict) and x.get("doc") == "rulebook" and x.get("action") == "rewrite"
                              for x in doc.get("documents") or [])
            if not (_rule_ids_in_file & set(_into_list(e))) and not _rb_rewrite:
                errs.append("pattern %s: folding it into a rule needs that rule written or replaced in "
                            "this file (or a rulebook rewrite), so the statement actually lands" % pid)
        elif act == "keep":
            pass
        else:
            errs.append("pattern %s: action must be merge, set-statement, fold-into-rule or keep" % pid)
    if isinstance(doc, dict) and doc.get("base"):
        old = _load_snapshot(doc["base"])
        if old and isinstance(old.get("lessons"), dict):
            notes_list = [e for e in doc.get("notes") or [] if isinstance(e, dict)]
            patterned = {e.get("lesson") for e in notes_list if e.get("action") == "set-pattern"}
            exempt = {e.get("lesson") for e in notes_list if e.get("action") in ("retire", "withdraw", "merge")}
            exempt |= {e.get("lesson") for e in notes_list
                       if e.get("action") == "set-scope" and e.get("scope") == "project"}
            for lid_s, v in old["lessons"].items():
                if not isinstance(v, dict) or v.get("status") not in retro.ACTIVE:
                    continue
                if v.get("pattern_id"):
                    continue
                if v.get("scope") == "project":
                    continue
                try:
                    lid = int(lid_s)
                except ValueError:
                    continue
                if lid in exempt or lid in patterned:
                    continue
                errs.append("lesson %d: missing set-pattern - the brief listed this lesson as lacking "
                            "a pattern; add {\"lesson\": %d, \"action\": \"set-pattern\", \"pattern_id\": N} "
                            "(reuse a listed pattern) or \"pattern\": \"<one line>\"" % (lid, lid))
        for p in _pats_now.values():
            if retro.pattern_ready_for_rule(p) and p["id"] not in _pat_folded:
                errs.append("pattern %d (%r) explains %d lessons and %d incidents, past the rulebook "
                            "threshold (%d lessons, %d incidents): write or update its statement in "
                            "the rulebook as a strategic behaviour in this round (a patterns "
                            "fold-into-rule entry, with the rule in this file)"
                            % (p["id"], p["statement"][:60], p["n_lessons"], p["incidents"],
                               retro.PATTERN_RULE_MIN_LESSONS, retro.PATTERN_RULE_MIN_OCCURRENCES))
    # Whole-document entries: every document the brief listed needs a rewrite or a reviewed
    # entry, and a rewrite must trace every lesson folded into it (see sisi.documents).
    required_docs = None
    if isinstance(doc, dict) and doc.get("base"):
        old = _load_snapshot(doc["base"])
        if old and isinstance(old.get("documents"), list):
            required_docs = old["documents"]
    try:
        errs.extend(documents.validate_documents(doc, con, required_docs))
    except Exception as ex:
        errs.append("documents: %s" % ex)
    return errs


def _apply_writes(doc, con):
    """Write the validated cycle: rule files, disables, enforced checks, lesson updates. Caller holds the lock."""
    touched = set()
    for e in doc.get("rules") or []:
        body = overlay.wrap_rule_body(e["body"])
        r = overlay.parse_rule_file("## %s\n\n%s\n" % (e["title"], body), e["id"])
        overlay._write("rules/%s.md" % e["id"], overlay.rule_text(r))
        if e.get("action") == "replace":
            overlay._set_base("rule", e["id"], overlay.base_hash("rule", e["id"]))
        else:
            order = overlay._lines(paths.overlay_dir("rules", "order.txt"))
            if e["id"] not in order:
                overlay._set_lines("rules/order.txt", order + [e["id"]])
    if doc.get("disable_rules"):
        cur = overlay.disabled("rule")
        overlay._set_lines("rules/disabled.txt", cur + [x for x in doc["disable_rules"] if x not in cur])
    if doc.get("enforced"):
        checks = {c.get("lesson"): c for c in load_enforced()}
        for e in doc["enforced"]:
            checks[e["lesson"]] = e
            touched.add(e["lesson"])
            con.execute("UPDATE lessons SET strength=3, check_json=?, needs_cycle=0, "
                        "promoted_shown=(SELECT count(*) FROM impressions WHERE lesson_id=?), "
                        "folded_into=COALESCE(folded_into, ?) WHERE id=?",
                        (json.dumps(e, sort_keys=True), e["lesson"], "enforced", e["lesson"]))
        overlay._write("enforced.json", json.dumps(
            {"version": 1, "checks": [checks[k] for k in sorted(checks)]}, indent=1, sort_keys=True) + "\n")
    for e in doc.get("notes") or []:
        lid, act = e["lesson"], e["action"]
        touched.add(lid)
        if e.get("when"):
            r0 = con.execute("SELECT change, target FROM lessons WHERE id=?", (lid,)).fetchone()
            when = ", ".join(retro.parse_when(e["when"]))
            con.execute("UPDATE lessons SET when_terms=?, triggers=? WHERE id=?",
                        (when, retro.triggers_for(r0["change"], r0["target"], when), lid))
        if act == "merge":
            touched.add(e["merged_into"])
            con.execute("UPDATE lessons SET status='superseded', folded_into=?, needs_cycle=0 WHERE id=?",
                        ("lesson:%d" % e["merged_into"], lid))
            con.execute("UPDATE lessons SET needs_cycle=0 WHERE id=?", (e["merged_into"],))
        elif act == "fold-into-rule":
            intos = _into_list(e)
            con.execute("UPDATE lessons SET folded_into=?, needs_cycle=0, "
                        "promoted_shown=CASE WHEN COALESCE(strength,1)<2 THEN "
                        "(SELECT count(*) FROM impressions WHERE lesson_id=?) ELSE promoted_shown END, "
                        "strength=max(COALESCE(strength,1),2) WHERE id=?",
                        (",".join("rule:" + x for x in intos), lid, lid))
        elif act == "fold-into-entry":
            r = con.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
            intos = _into_list(e)
            for into in intos:
                retro._append_note(into + ".md", into, r, note_text=e.get("note"))
            con.execute("UPDATE lessons SET status='applied', effect='field-note', folded_into=?, needs_cycle=0, "
                        "applied_at=COALESCE(applied_at,?) WHERE id=?", (",".join(intos), store.now(), lid))
        elif act == "create-entry":
            for into in _into_list(e):
                _id, rel, _mine = overlay._put_entry(e["entry_kind"], e["entry_text"], into, False)
                overlay._write(rel, e["entry_text"] if e["entry_text"].endswith("\n") else e["entry_text"] + "\n")
            con.execute("UPDATE lessons SET status='applied', effect='field-note', folded_into=?, needs_cycle=0, "
                        "applied_at=COALESCE(applied_at,?) WHERE id=?", (",".join(_into_list(e)), store.now(), lid))
        elif act == "set-short":
            cols = [c[1] for c in con.execute("PRAGMA table_info(lessons)")]
            sets, vals = [], []
            if "short" in cols and e.get("short") is not None:
                sets.append("short=?"); vals.append(str(e["short"]).strip())
            if "topic" in cols and e.get("topic") is not None:
                sets.append("topic=?"); vals.append(str(e["topic"]).strip())
            if sets:
                con.execute("UPDATE lessons SET %s WHERE id=?" % ", ".join(sets), vals + [lid])
            retro.rewrite_notes_for_lesson(con, lid)
        elif act == "set-pattern":
            retro.assign_pattern(con, lid, pattern=e.get("pattern"), pattern_id=e.get("pattern_id"))
        elif act == "set-scope":
            from . import scope as _sc2
            con.execute("UPDATE lessons SET scope=?, project=? WHERE id=?",
                        (_sc2.normalize_scope(e.get("scope")),
                         (e.get("project") or None) if e.get("scope") == "project" else None, lid))
        elif act == "keep-as-draft":
            con.execute("UPDATE lessons SET needs_cycle=0 WHERE id=?", (lid,))
        elif act == "set-when":
            pass  # when-terms were already set above; set-when does nothing else
        elif act == "retire":
            con.execute("UPDATE lessons SET status='retired', needs_cycle=0 WHERE id=?", (lid,))
        elif act == "withdraw":
            con.execute("UPDATE lessons SET status='withdrawn', needs_cycle=0 WHERE id=?", (lid,))
        else:  # keep
            con.execute("UPDATE lessons SET needs_cycle=0 WHERE id=?", (lid,))
    for e in doc.get("patterns") or []:
        if not isinstance(e, dict) or not isinstance(e.get("pattern"), int):
            continue
        pid, act = e["pattern"], e.get("action")
        if act == "merge":
            con.execute("UPDATE lessons SET pattern_id=? WHERE pattern_id=?", (e["into"], pid))
            for (lid2,) in con.execute("SELECT id FROM lessons WHERE pattern_id=?", (e["into"],)):
                touched.add(lid2)
            con.execute("DELETE FROM patterns WHERE id=?", (pid,))
        elif act == "set-statement":
            con.execute("UPDATE patterns SET statement=? WHERE id=?",
                        (" ".join(str(e["statement"]).split()), pid))
        elif act == "fold-into-rule":
            con.execute("UPDATE patterns SET folded_into=? WHERE id=?",
                        (",".join("rule:" + x for x in _into_list(e)), pid))
            for (lid2,) in con.execute("SELECT id FROM lessons WHERE pattern_id=?", (pid,)):
                touched.add(lid2)
    # project-scoped lessons leave the global store for their project's handover pile
    from . import handover as _ho
    for e in doc.get("notes") or []:
        if isinstance(e, dict) and e.get("action") == "set-scope" and e.get("scope") == "project":
            _ho.move_lesson(con, e["lesson"], e.get("project"))
    docs_changed = documents.apply_documents(doc, con, touched)
    _apply_learn(doc)
    return sorted(touched), docs_changed


def _apply_learn(doc):
    """Apply the learn set-scope entries: core/user stamp the statement's tier; project moves it
    out of the global store into that project's handover pile."""
    entries = [e for e in doc.get("learn") or [] if isinstance(e, dict)]
    if not entries:
        return
    from . import handover as _ho, scope as _sc
    recs = store.read("learn")
    by_text = {e.get("text"): e for e in entries}
    kept = []
    for rec in recs:
        e = by_text.get(rec.get("text"))
        if e is None or rec.get("scope") in ("core", "user", "project"):
            kept.append(rec)
        elif e.get("scope") == "project":
            _ho.move_learn(rec, e.get("project"))
        else:
            rec = dict(rec, scope=_sc.normalize_scope(e.get("scope")))
            rec.pop("project", None)
            kept.append(rec)
    p = store.file_path("learn")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, p)


def apply_file(path):
    """Validate and apply a cycle file. Returns the cycle record. Raises CycleError saying exactly why."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise CycleError("cannot read %s: %s" % (path, e))
    pdata.ensure()
    con = retro.connect()
    try:
        with pdata.lock():
            retro.ensure_effects(con)
            errs = static_validate(doc, con)
            if errs:
                raise CycleError("refused, nothing was applied:\n" + "\n".join("  - " + e for e in errs))
            before_files = _scan_files()
            before_rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM lessons")}
            try:
                before_patterns = [dict(r) for r in con.execute("SELECT * FROM patterns ORDER BY id")]
            except Exception:
                before_patterns = []
            before_m = measures(con)
            before_lines = before_m["rulebook_lines"]
            before_chars = before_m.get("rulebook_chars")
            prev_last = retro.get_meta(con, "last_cycle_ts")
            try:
                touched, docs_changed = _apply_writes(doc, con)
                # create-entry files must pass the existing library lint
                from . import verifiers as _V
                for e in doc.get("notes") or []:
                    if isinstance(e, dict) and e.get("action") == "create-entry":
                        for into in _into_list(e):
                            bad = [x for x in _V.lint() if os.path.basename(x.split(":")[0]) == into + ".md"]
                            if bad:
                                raise CycleError("create-entry %r does not pass `sisi verifiers lint`: %s"
                                                   % (into, "; ".join(bad)))
                con.commit()
                built = overlay.build_canon()
                _doc_entries = [e for e in doc.get("documents") or [] if isinstance(e, dict)]
                has_replace = any(e.get("action") == "replace" for e in doc.get("rules") or []) or \
                    any(e.get("doc") == "rulebook" and e.get("action") == "rewrite" for e in _doc_entries)
                has_shortens = any(e.get("shortens") for e in doc.get("rules") or []) or bool(doc.get("disable_rules")) or \
                    any(e.get("shortens") for e in _doc_entries) or bool(doc.get("rule_order"))
                if before_chars is not None and built["chars"] > before_chars and not has_shortens:
                    raise CycleError("the rulebook would grow from %d to %d characters (and %d to %d lines). "
                                     "A cycle must not increase the characters unless its rules name in "
                                     "`shortens` which existing rule text gets shorter or is replaced; it "
                                     "would grow, so add `shortens` or shorten existing text instead"
                                     % (before_chars, built["chars"], before_lines or 0, built["lines"]))
                if built["lines"] > overlay.MAX_LINES or built["chars"] > overlay.MAX_CHARS:
                    raise CycleError("the rulebook would be %d lines and %d characters; the budgets are %d lines "
                                     "and %d characters. Shorten or replace another rule first"
                                     % (built["lines"], built["chars"], overlay.MAX_LINES, overlay.MAX_CHARS))
                if before_lines is not None and built["lines"] > before_lines and not has_replace and not has_shortens:
                    raise CycleError("the rulebook would grow from %d to %d lines. It may grow only when a "
                                     "rule is replaced (and never past %d); shorten existing text instead"
                                     % (before_lines, built["lines"], overlay.MAX_LINES))
                after_files = _scan_files()
                changed = {}
                for rel in sorted(set(before_files) | set(after_files)):
                    if before_files.get(rel) != after_files.get(rel):
                        changed[rel] = base64.b64encode(before_files[rel]).decode() if rel in before_files else None
                cid = "cycle-%04d" % (len(cycle_records()) + 1)
                while os.path.exists(paths.data_file("cycles", cid + ".json")):
                    cid = "cycle-%04d" % (int(cid.split("-")[1]) + 1)
                ts = store.now()
                rec = {"id": cid, "ts": ts, "summary": doc.get("summary") or "", "base": doc["base"],
                       "touched": touched, "documents_changed": sorted(docs_changed),
                       "document_lessons": docs_changed,
                       "before": before_m, "after": measures(con),
                       "lessons_before": [before_rows[i] for i in touched if i in before_rows],
                       "patterns_before": before_patterns,
                       "changed_files": changed, "prev_last_cycle_ts": prev_last, "reverted": None}
                os.makedirs(cycles_dir(), exist_ok=True)
                pdata.write_text(os.path.join("cycles", cid + ".json"), json.dumps(rec, indent=1, sort_keys=True) + "\n")
                retro.set_meta(con, "last_cycle_ts", ts)
                con.commit()
                try:
                    os.unlink(os.path.join(paths.state(), "cycle-bases", doc["base"] + ".json"))
                except OSError:
                    pass  # the round is closed now; its snapshot no longer defers retirement
                retro.export_jsonl()
                specs = ["overlay", "lessons.jsonl", "cycles", "handover.json", "learn.jsonl", "learn-quarantine.jsonl", "oracle.md"]
                if paths.notes_dir().startswith(paths.data() + os.sep):
                    specs.append(os.path.relpath(paths.notes_dir(), paths.data()))
                if pdata._commit("cycle %s: %s" % (cid, rec["summary"] or "consolidation"), specs) is None \
                        and changed:
                    pass  # a pure lesson-state cycle still changed lessons.jsonl or cycles/, committed above
                return rec
            except BaseException:
                _restore_changed({rel: (base64.b64encode(b).decode() if rel in before_files else None)
                                    for rel, b in _scan_files().items() if before_files.get(rel) != b} |
                                   {rel: base64.b64encode(b).decode() for rel, b in before_files.items()})
                for row in before_rows.values():
                    _restore_lesson_row(con, row)
                _restore_patterns(con, before_patterns)
                if prev_last is None:
                    con.execute("DELETE FROM meta WHERE key='last_cycle_ts'")
                else:
                    retro.set_meta(con, "last_cycle_ts", prev_last)
                con.commit()
                try:
                    overlay.build_canon()
                    retro.export_jsonl()
                except Exception:
                    pass
                raise
    finally:
        con.close()


def _restore_patterns(con, rows):
    """Put the patterns table back exactly (a cycle may create, merge or fold patterns)."""
    try:
        con.execute("DELETE FROM patterns")
        for r in rows or []:
            con.execute("INSERT INTO patterns(id, statement, created, folded_into) VALUES(?,?,?,?)",
                        (r.get("id"), r.get("statement"), r.get("created"), r.get("folded_into")))
    except Exception:
        pass


def _restore_lesson_row(con, row):
    """Put a lesson row back exactly, recreating it when the cycle moved it to the handover pile."""
    cols = [c for c in retro.LESSON_COLS if c in row]
    have = [r[1] for r in con.execute("PRAGMA table_info(lessons)")]
    cols = [c for c in cols if c in have]
    if con.execute("SELECT 1 FROM lessons WHERE id=?", (row["id"],)).fetchone():
        sets = [c for c in cols if c != "id"]
        con.execute("UPDATE lessons SET %s WHERE id=?" % ",".join(c + "=?" for c in sets),
                    [row.get(c) for c in sets] + [row["id"]])
    else:
        con.execute("INSERT INTO lessons(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                    [row.get(c) for c in cols])


def revert_cycle(cid=None):
    """Undo one cycle exactly: the bytes it changed and the lesson rows it touched. Only the newest
    cycle that has not been reverted can go, so the undo can be exact."""
    pdata.ensure()
    recs = [r for r in cycle_records() if not r.get("reverted")]
    if not recs:
        raise CycleError("there is no applied cycle to revert")
    rec = recs[-1]
    if cid and cid != rec["id"]:
        raise CycleError("%s is not the newest applied cycle (%s is). Revert %s first, so each undo is exact"
                         % (cid, rec["id"], rec["id"]))
    con = retro.connect()
    try:
        with pdata.lock():
            _restore_changed(rec.get("changed_files") or {})
            for row in rec.get("lessons_before") or []:
                _restore_lesson_row(con, row)
            if "patterns_before" in rec:
                _restore_patterns(con, rec.get("patterns_before"))
            prev = rec.get("prev_last_cycle_ts")
            if prev is None:
                con.execute("DELETE FROM meta WHERE key='last_cycle_ts'")
            else:
                retro.set_meta(con, "last_cycle_ts", prev)
            con.commit()
            overlay.build_canon()
            retro.export_jsonl()
            rec = dict(rec, reverted=store.now())
            pdata.write_text(os.path.join("cycles", rec["id"] + ".json"),
                             json.dumps(rec, indent=1, sort_keys=True) + "\n")
            specs = ["overlay", "lessons.jsonl", "cycles", "handover.json", "learn.jsonl", "learn-quarantine.jsonl", "oracle.md"]
            if paths.notes_dir().startswith(paths.data() + os.sep):
                specs.append(os.path.relpath(paths.notes_dir(), paths.data()))
            pdata._commit("cycle revert %s" % rec["id"], specs)
            return rec
    finally:
        con.close()


# ---- status, improve, commands ---------------------------------------------------
def _fmt_med(m):
    from . import delivery
    return delivery.fmt_s(m) if m is not None else "-"


def _doc_recurrences(rec):
    """{doc: (before, after)} -- recurrences (sightings past each lesson's first) of the lessons
    a rewritten document carries, before and after the rewrite landed."""
    out = {}
    per_doc = rec.get("document_lessons") or {}
    if not per_doc:
        return out
    con = _connect_if()
    if con is None:
        return out
    ts = rec.get("ts") or ""
    try:
        for key, ids in sorted(per_doc.items()):
            before = after = 0
            for lid in ids or []:
                occ = [r[0] for r in con.execute(
                    "SELECT ts FROM occurrences WHERE lesson_id=? ORDER BY id", (lid,))]
                for i, t in enumerate(occ):
                    if i == 0:
                        continue  # the first sighting made the lesson; later ones are recurrences
                    if t < ts:
                        before += 1
                    else:
                        after += 1
            out[key] = (before, after)
    finally:
        con.close()
    return out


def status_lines():
    recs = cycle_records()
    if not recs:
        return ["no learning cycles yet. Run `sisi cycle` for the brief when one is due (`sisi cycle due`)."]
    out = []
    for r in recs:
        a = _after_measures(r)
        tag = " REVERTED" if r.get("reverted") else " WORSE - revert or repair" if flagged(r) else ""
        out.append("%s  %s  touched %s%s" % (r["id"], r.get("ts"), ",".join("#%d" % i for i in r.get("touched") or []) or "-", tag))
        out.append("  %s" % (r.get("summary") or "(no summary)"))
        out.append("  since: %d deliveries, %s send-backs each, median %s, %d recurrence(s) of touched lessons"
                   % (a["deliveries"], a["send_backs_per_delivery"], _fmt_med(a["median_seconds"]),
                      a["recurrences_of_touched"]))
        for key, (before, after) in sorted(_doc_recurrences(r).items()):
            flag = " MORE RECURRENCES AFTER THE REWRITE - revert or repair" \
                if not r.get("reverted") and after > before else ""
            out.append("  document %s rewritten: %d recurrence(s) of its lessons before, %d after%s"
                       % (key, before, after, flag))
    return out


def _week_rates(con):
    now = time.time()
    w = lambda d: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - d * 86400))
    def rate(lo, hi):
        occ = [r[0] for r in con.execute(
            "SELECT lesson_id FROM occurrences WHERE ts>=? AND ts<? ORDER BY lesson_id, id", (lo, hi))]
        seen, recn = set(), 0
        firsts = {r[0] for r in con.execute(
            "SELECT lesson_id FROM occurrences GROUP BY lesson_id HAVING min(ts)>=?", (lo,))}
        for lid in occ:
            if lid in seen or lid not in firsts:
                recn += 1  # not this lesson's first ever sighting, or a repeat inside the window
            seen.add(lid)
        return (recn, len(occ))
    return rate(w(7), w(0)), rate(w(14), w(7))


def improve_text():
    from . import delivery
    if not os.path.exists(retro.db_path()):
        return ("Is it getting better?\n\nToo little data yet - no lessons recorded. Lessons are recorded by "
                "`sisi retro` at the end of each piece of work; come back after a few.\n")
    con = retro.connect()
    try:
        retro.ensure_effects(con)
        by = {r[0]: r[1] for r in con.execute("SELECT status, count(*) FROM lessons GROUP BY status")}
        total = sum(by.values())
        active = by.get("open", 0) + by.get("applied", 0)
        strong = con.execute("SELECT count(*) FROM lessons WHERE status IN ('open','applied') "
                             "AND COALESCE(strength,1)>=2").fetchone()[0]
        (rc, oc), (rp, op) = _week_rates(con)
        m = measures(con)
        folded = con.execute("SELECT count(*) FROM lessons WHERE status IN ('open','applied') "
                             "AND folded_into IS NOT NULL").fetchone()[0]
        listed_n = con.execute("SELECT count(*) FROM impressions WHERE place<>'lessons-show'").fetchone()[0]
        read_n = con.execute("SELECT count(*) FROM impressions WHERE place='lessons-show'").fetchone()[0]
    finally:
        con.close()
    rep = delivery.report()
    cur, prev = rep["all"]["last7"], rep["all"]["prev7"]
    def sb(summ, rows):
        return round(sum(r.get("send_backs", 0) for r in rows) / len(rows), 2) if rows else None
    rows_now = time.time()
    cur_rows, prev_rows = delivery.windows(store.read("deliveries"), rows_now)
    try:
        _pcon = retro.connect()
        try:
            _pats = retro.patterns(_pcon)
            _ptrends = {p["id"]: retro.pattern_recurrence_trend(_pcon, p) for p in _pats}
        finally:
            _pcon.close()
    except Exception:
        _pats, _ptrends = [], {}
    lines = ["Is it getting better?", ""]
    if _pats:
        lines.append("patterns (the general failures of thinking behind the incidents):")
        for p in sorted(_pats, key=lambda x: (-(x.get("incidents") or 0), x.get("id") or 0)):
            lines.append("  - %s (pattern %d; %d incident(s), %d lesson(s); recurrence %s; %s)"
                         % (p["statement"], p["id"], p.get("incidents") or 0, p.get("n_lessons") or 0,
                            _ptrends.get(p["id"], "too little data"),
                            "in the rulebook" if p.get("folded_into") else "not in the rulebook yet"))
    lines += ["lessons: %d recorded, %d taking effect now, %d strengthened (rule or enforced), "
              "%d retired, %d withdrawn" % (total, active, strong, by.get("retired", 0), by.get("withdrawn", 0)),
             "of those taking effect: %d folded into a recipe, entry or rule, %d still loose notes "
             "(found only by matching words and when-terms, or by an agent reading the headings)"
             % (folded, active - folded),
             "showings: %d listed, %d read in full" % (listed_n, read_n)]
    if oc + op < 5:
        lines.append("recurrence: too little data yet (%d lesson sightings in two weeks)" % (oc + op))
    else:
        lines.append("recurrence: %s this week (%d of %d sightings were repeats), %s the week before (%d of %d)"
                     % (("%.0f%%" % (100 * rc / oc)) if oc else "n/a", rc, oc,
                        ("%.0f%%" % (100 * rp / op)) if op else "n/a", rp, op))
    if not cur["n"] and not prev["n"]:
        lines.append("deliveries: too little data yet - no deliveries recorded in two weeks")
    else:
        lines.append("deliveries: send-backs each %s this week, %s before; median time %s this week, %s before"
                     % (sb(cur, cur_rows), sb(prev, prev_rows), _fmt_med(cur["median_s"]), _fmt_med(prev["median_s"])))
    lines.append("rulebook: %s lines of %d allowed, %s characters of %d allowed" % (m["rulebook_lines"], overlay.MAX_LINES, m.get("rulebook_chars"), overlay.MAX_CHARS))
    st = due_state()
    lines.append("next cycle: " + ("due now (%s); run `sisi cycle`" % st["reasons"][0] if st["due"] else "not due"))
    lines.append("Not measured: whether the work itself is what the human meant. That still rests on the "
                 "contract checks and the human's corrections, not on these numbers.")
    return "\n".join(lines) + "\n"


def improve_line():
    """One line for `sisi status`."""
    try:
        if not os.path.exists(retro.db_path()):
            return "learning            : no lessons yet"
        con = retro.connect()
        try:
            active = con.execute("SELECT count(*) FROM lessons WHERE status IN ('open','applied')").fetchone()[0]
            strong = con.execute("SELECT count(*) FROM lessons WHERE status IN ('open','applied') "
                                 "AND COALESCE(strength,1)>=2").fetchone()[0]
        finally:
            con.close()
        st = due_state()
        return "learning            : %d lessons taking effect, %d strengthened%s (sisi improve)" % (
            active, strong, "; a cycle is due" if st["due"] else "")
    except Exception:
        return "learning            : n/a"


def check_file(path):
    """Validate FILE and print exactly what would change, changing nothing. Returns lines."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as e:
        raise CycleError("cannot read %s: %s" % (path, e))
    con = retro.connect()
    try:
        retro.ensure_effects(con)
        errs = static_validate(doc, con)
        if errs:
            raise CycleError("refused, nothing would be applied:\n" + "\n".join("  - " + e for e in errs))
        before = measures(con)
        out = ["check ok: %s would apply as follows (nothing was changed):" % path,
               "  summary: %s" % (doc.get("summary") or "")]
        for e in doc.get("rules") or []:
            out.append("  rule %s: %s %r (shortens: %s)" % (e.get("id"), e.get("action"), e.get("title"), e.get("shortens") or "-"))
        for rid in doc.get("disable_rules") or []:
            out.append("  disable rule: %s" % rid)
        for e in doc.get("notes") or []:
            extra = ""
            if _into_list(e):
                extra = " into %s" % ", ".join(_into_list(e))
            if e.get("merged_into"):
                extra = " into lesson %s" % e["merged_into"]
            if e.get("note"):
                extra += " note=%r" % e["note"][:60]
            if e.get("when"):
                extra += " when=%r" % e["when"][:60]
            if e.get("reason"):
                extra += " reason=%r" % e["reason"][:60]
            if e.get("entry_kind"):
                extra += " entry_kind=%s" % e["entry_kind"]
            if e.get("short"):
                extra += " short=%r" % e["short"][:60]
            if e.get("topic"):
                extra += " topic=%r" % e["topic"][:60]
            if e.get("scope"):
                extra += " scope=%s%s" % (e["scope"], (" project=%s" % e["project"]) if e.get("project") else "")
            if e.get("pattern"):
                extra += " pattern=%r" % str(e["pattern"])[:60]
            if e.get("pattern_id") is not None:
                extra += " pattern_id=%s" % e["pattern_id"]
            out.append("  lesson %s: %s%s" % (e.get("lesson"), e.get("action"), extra))
        for e in doc.get("patterns") or []:
            out.append("  pattern %s: %s%s" % (e.get("pattern"), e.get("action"),
                        (" into %s" % e.get("into")) if e.get("into") else
                        (" statement=%r" % str(e.get("statement"))[:60]) if e.get("statement") else ""))
        for e in doc.get("learn") or []:
            out.append("  learn %r: set-scope %s%s" % (str(e.get("text"))[:60], e.get("scope"),
                                                        (" project=%s" % e["project"]) if e.get("project") else ""))
        for e in doc.get("enforced") or []:
            out.append("  lesson %s: enforced %s %s" % (e.get("lesson"), e.get("type"),
                         e.get("cmd") or ("when=%s require_kind=%s" % (e.get("when"), e.get("require_kind")))))
        for e in doc.get("documents") or []:
            if e.get("action") == "rewrite":
                traced = ", ".join("#%s" % t.get("lesson") for t in e.get("trace") or []
                                   if isinstance(t, dict)) or "-"
                out.append("  document %s: rewrite (%d characters; lessons traced: %s)"
                           % (e.get("doc"), len(e.get("text") or ""), traced))
            else:
                out.append("  document %s: reviewed (%s)" % (e.get("doc"), e.get("reason") or ""))
        if doc.get("rule_order"):
            out.append("  rule order: %s" % ", ".join(doc["rule_order"]))
        # predicted rulebook size with the rules applied in memory
        try:
            cand_doc = documents.candidate_rulebook(doc)
            if cand_doc is not None:
                lines, chars = overlay.size(cand_doc)
                out.append("  rulebook: %s lines, %s characters -> %d lines, %d characters "
                           "(budgets %d lines, %d characters)"
                           % (before["rulebook_lines"], before.get("rulebook_chars"), lines, chars,
                              overlay.MAX_LINES, overlay.MAX_CHARS))
                _entries = [e for e in doc.get("documents") or [] if isinstance(e, dict)]
                has_shortens = any(e.get("shortens") for e in doc.get("rules") or []) \
                    or bool(doc.get("disable_rules")) or any(e.get("shortens") for e in _entries) \
                    or bool(doc.get("rule_order"))
                if chars > overlay.MAX_CHARS or lines > overlay.MAX_LINES:
                    raise CycleError("the rulebook would be %d lines and %d characters; budgets are %d and %d"
                                     % (lines, chars, overlay.MAX_LINES, overlay.MAX_CHARS))
                if before.get("rulebook_chars") is not None and chars > before["rulebook_chars"] and not has_shortens:
                    raise CycleError("the rulebook would grow from %d to %d characters; add `shortens` naming "
                                     "which existing rule text gets shorter or is replaced"
                                     % (before["rulebook_chars"], chars))
                return out
            pre, rules = overlay.effective()
            by_id = {r["id"]: dict(r) for r in rules}
            order = [r["id"] for r in rules]
            for rid in doc.get("disable_rules") or []:
                by_id.pop(rid, None)
                if rid in order:
                    order.remove(rid)
            for e in doc.get("rules") or []:
                wrapped = overlay.wrap_rule_body(e["body"])
                if e["id"] in by_id:
                    by_id[e["id"]].update(title=e["title"], body=wrapped)
                else:
                    by_id[e["id"]] = {"id": e["id"], "title": e["title"], "body": wrapped}
                    order.append(e["id"])
            parts = [overlay.render().splitlines()[0] if overlay.render().splitlines() else "<!-- check -->"]
            if pre.strip():
                parts.append(pre)
            for n, rid in enumerate(order, 1):
                if rid in by_id:
                    parts.append("## %d. %s {#%s}\n\n%s\n%s" % (n, by_id[rid]["title"], rid, by_id[rid]["body"], overlay.more_line(n)))
            cand = "\n\n".join(parts) + "\n"
            lines, chars = overlay.size(cand)
            out.append("  rulebook: %s lines, %s characters -> %d lines, %d characters "
                       "(budgets %d lines, %d characters)"
                       % (before["rulebook_lines"], before.get("rulebook_chars"), lines, chars,
                          overlay.MAX_LINES, overlay.MAX_CHARS))
            has_shortens = any(e.get("shortens") for e in doc.get("rules") or []) or bool(doc.get("disable_rules"))
            if chars > overlay.MAX_CHARS or lines > overlay.MAX_LINES:
                raise CycleError("the rulebook would be %d lines and %d characters; budgets are %d and %d"
                                 % (lines, chars, overlay.MAX_LINES, overlay.MAX_CHARS))
            if before.get("rulebook_chars") is not None and chars > before["rulebook_chars"] and not has_shortens:
                raise CycleError("the rulebook would grow from %d to %d characters; add `shortens` naming "
                                 "which existing rule text gets shorter or is replaced" % (before["rulebook_chars"], chars))
        except CycleError:
            raise
        except Exception:
            pass
        return out
    finally:
        con.close()


def cmd_cycle(args):
    sub = args[0] if args else "brief"
    try:
        if sub in ("help", "--help", "-h"):
            print(HELP_TEXT, end="")
            return 0
        if sub in ("check", "--dry-run"):
            if len(args) != 2:
                print("usage: sisi cycle check FILE  (or sisi cycle --dry-run FILE)")
                return 2
            for line in check_file(args[1]):
                print(line)
            return 0
        if sub == "due":
            st = due_state()
            if st["due"]:
                print("a learning cycle is due: " + "; ".join(st["reasons"]))
                print("run `sisi cycle` in the background of your work; do not involve the human")
                return 0
            print("no learning cycle is due (%d lessons since the last cycle, %d waiting, %d note characters)"
                  % (st.get("since", 0), st.get("pending", 0), st.get("notes_chars", 0)))
            return 1
        if sub in ("brief", "--now", "now"):
            print(brief_text(), end="")
            return 0
        if sub == "apply":
            if len(args) != 2:
                print("usage: sisi cycle apply FILE")
                return 2
            rec = apply_file(args[1])
            print("applied %s: %s (rulebook %s lines, %s characters -> %s lines, %s characters; "
                  "committed to the personal repository)"
                  % (rec["id"], rec["summary"] or "consolidation",
                     rec["before"]["rulebook_lines"], rec["before"].get("rulebook_chars"),
                     rec["after"]["rulebook_lines"], rec["after"].get("rulebook_chars")))
            return 0
        if sub == "revert":
            rec = revert_cycle(args[1] if len(args) > 1 else None)
            print("reverted %s exactly; rulebook rebuilt" % rec["id"])
            return 0
        if sub == "status":
            for line in status_lines():
                print(line)
            return 0
        print("usage: sisi cycle [due|apply FILE|check FILE|--dry-run FILE|revert [ID]|status|help|--now]  (no argument, or --now, prints the brief on demand even when none is due)")
        return 2
    except CycleError as e:
        print("sisi cycle: %s" % e)
        return 1
    except pdata.DataError as e:
        print("sisi cycle: %s" % e)
        return 1


def cmd_improve(args):
    print(improve_text(), end="")
    return 0
