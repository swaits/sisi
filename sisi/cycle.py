"""The consolidation cycle and its measurements: `sisi cycle`, `sisi improve`, enforced lessons.

There is no scheduler. Whether a cycle is due is a counter check run during normal use: at session
start (tick), at the end of a turn (gate), and in the output of `sisi retro`, `sisi verify` and
`sisi done for` -- commands agents run in every tool, hook or no hook. A session is told at most once
until 20 further checks pass or the counter grows again.

A cycle file (what the agent writes, what `sisi cycle apply` checks) is one JSON object:
  {"version": 1, "base": "<base version printed by the brief>", "summary": "one line",
   "rules": [{"id": "rule-id", "title": "Title", "body": "text with a Why: line", "action": "add|replace"}],
   "disable_rules": ["rule-id"],
   "notes": [{"lesson": 3, "action": "merge|fold-into-rule|fold-into-entry|retire|withdraw|keep",
              "into": "rule or entry id", "merged_into": 4,
              "when": "csv, tsv, spreadsheet, tabular data, import, parse (optional; sets the lesson's when-terms)"}],
   "enforced": [{"lesson": 3, "type": "command", "cmd": "...", "expect": {"exit": 0}, "timeout_s": 30},
                {"lesson": 4, "type": "contract-requirement", "when": "parser",
                 "require_kind": "parsing", "max_rung": 2}]}
Every part is optional except version and base. Apply is one commit in the personal repository under
the personal-data lock; a stale base (another cycle or lesson landed since the brief) refuses cleanly.
Each applied cycle records the exact bytes it changed, so revert restores them byte for byte.
"""
import base64, difflib, hashlib, json, os, re, shlex, shutil, time

from . import overlay, paths, pdata, retro, store


class CycleError(Exception):
    pass


ACTIONS = ("merge", "fold-into-rule", "fold-into-entry", "retire", "withdraw", "keep",
           "set-when", "create-entry", "keep-as-draft")
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
        since = con.execute("SELECT count(*) FROM lessons WHERE created>?", (last,)).fetchone()[0]
        pending = con.execute(
            "SELECT count(*) FROM lessons WHERE status IN ('open','applied') AND "
            "(COALESCE(needs_cycle,0)=1 OR (COALESCE(strength,1)>=3 AND check_json IS NULL))").fetchone()[0]
        notes_chars = retro.notes_chars(con)
        loose = [dict(r) for r in con.execute(
            "SELECT * FROM lessons WHERE status IN ('open','applied') AND folded_into IS NULL ORDER BY id")]
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
             "folded_into", "effect", "when_terms", "check_json", "needs_cycle")


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
    return {"lessons": lessons, "files": files, "rules": rules, "enforced": enf,
            "last_cycle_ts": retro.get_meta(con, "last_cycle_ts") or "", "cycles": cyc}


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
   "notes": [{"lesson": 3, "action": "merge|fold-into-rule|fold-into-entry|retire|withdraw|keep|set-when|create-entry|keep-as-draft",
              "into": "id or [ids] (folds; entry folds append a field note)", "merged_into": 4,
              "note": "text to append instead of the lesson change (for splitting one lesson)",
              "when": "at least 5 terms (sets when-terms; alone with action set-when)",
              "entry_kind": "recipe|verifier", "entry_text": "full file text (create-entry)",
              "reason": "why it stays a draft (keep-as-draft)"}],
   "enforced": [{"lesson": 3, "type": "command", "cmd": "...", "expect": {"exit": 0}, "timeout_s": 30},
                {"lesson": 4, "type": "contract-requirement", "when": "parser", "require_kind": "parsing", "max_rung": 2}]}"""

HELP_TEXT = """sisi cycle help: the full cycle file format (the brief is the short form)

File: write ONE JSON file at the scratch path the brief prints, then:
  sisi cycle check FILE     validate and print exactly what would change, changing nothing
                            (also: sisi cycle --dry-run FILE)
  sisi cycle apply FILE     apply it (one commit in the personal repository)
  sisi cycle revert [ID]    undo the newest applied cycle exactly
  sisi cycle status         past cycles and what happened since

Top level: {"version": 1 (required), "base": "<from the brief, required>", "summary": "one line",
  "rules": [...], "disable_rules": [...], "notes": [...], "enforced": [...]} - all else optional.
The file covers only the lessons listed in its brief. Lessons recorded since the brief are left
for the next cycle and do not make the apply fail. Reading (`sisi lessons show ID`, `sisi done`,
`sisi verifiers show`) never stales the base: it covers only lesson content/status, rules, notes
and enforced checks, not listed/read counters. A stale refusal names exactly what changed.

Rules - format: {"id", "title", "body", "action": "add|replace", "shortens": "..."}.
  Body: prose paragraphs wrapped at 100 characters (apply re-wraps for you), ending with a
  paragraph starting "Why:". Keep the id and the Why when replacing. Title is the heading text.
  Budget: at most 120 lines AND at most 7200 characters, and a cycle must not increase the
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
                  <count> times; lesson <id>)", and marks the lesson applied / field-note /
                  folded_into=<id>. To split a compound lesson, use two notes objects with the
                  same lesson, different `into` and different `note` text each.
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
  keep            {"lesson": A, "action": "keep"} - leave it; clears its waiting flag.
  retire          leave the active notes. Only when fully folded and quiet: folded into a rule,
                  entry or enforced check, listed/read at least 20 times, and 0 recurrences after
                  first being listed. Folding in this cycle does not make it quiet: fold now,
                  keep it, and retire it in a later cycle once it is quiet. (sisi also retires
                  such lessons itself at 20 showings.)
  withdraw        it made things worse or keeps recurring at strength 3; same wording is not
                  re-learned. Tool lessons: cannot be done in a cycle (they are changes to sisi
                  itself) - leave them in `sisi backlog` untouched, except merging a duplicate.

Enforced checks - write none for lessons below strength 3. One per strength-3 NEEDS A CHECK:
  command: {"lesson": 3, "type": "command", "cmd": "program + args that exist here",
    "expect": {"exit": 0} (integer exit code required; runs only in trusted projects),
    "timeout_s": 30 (seconds, optional)}
  contract-requirement: {"lesson": 4, "type": "contract-requirement",
    "when": "word in the contract goal/claims that triggers it",
    "require_kind": "general|concurrency|parsing|money|state-machine|migration|ui",
    "max_rung": 2 (optional, 1-6: the required check must be at this rung or stronger)}
  Complete examples are the two objects above.

Learned-notes limit: counts length(change) of active strength-1 loose learned notes only
(limit 4000 characters). Folded, strengthened, retired, withdrawn and tool-backlog lessons do
not count. fold-into-entry, fold-into-rule, merge, retire, withdraw and writing an enforced
check all reduce it; keep and set-when do not.
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
    out += ["Do this, in order:",
            "1. Fold each loose lesson into the recipe/entry whose applies-to (above) fits its kind of "
            "work, or lift several into one general rule. fold-into-entry appends a field note (see help). "
            "For a lesson naming a recipe/entry that does not exist, use create-entry with a lint-clean "
            "file, or keep-as-draft with a reason if that is too large for this cycle - never fold into a poor match.",
            "2. Merge only lessons requesting the same change (not just the same topic), into the older "
            "or more general one; the survivor keeps its text and occurrence count. Superseded, retired "
            "and withdrawn lessons need no action.",
            "3. Tool lessons (kind tool) cannot be done in a cycle: leave them in `sisi backlog` untouched, except merging a duplicate.",
            "4. Rules: keep id and Why, format per help; name in `shortens` which existing rule text gets shorter or is replaced whenever a rule is added or the book would grow in characters.",
            "5. For each NEEDS A CHECK lesson write one enforced check (help has fields and examples); none below strength 3.",
            "6. Retire only what is fully folded and quiet (folded, at least 20 listed/read, 0 recurrences "
            "after first listed) - folding now does not make it quiet, so fold and keep, retire next cycle. "
            "Withdraw what made things worse. set-when only sets when-terms. Keep the rest.",
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
    return ids


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
    try:
        kinds = {r[0]: r[1] for r in con.execute("SELECT id, change_kind FROM lessons")}
    except Exception:
        pass
    for e in doc.get("notes") or []:
        if not isinstance(e, dict) or e.get("action") not in ACTIONS:
            errs.append("each note needs an action in %s: %r" % (", ".join(ACTIONS), e))
            continue
        lid = e.get("lesson")
        if kinds.get(lid) == "tool" and e["action"] not in ("merge", "keep", "keep-as-draft", "set-when"):
            errs.append("lesson %s: tool lessons cannot be done in a cycle (they change sisi itself); "
                        "leave them in `sisi backlog` untouched, except merging a duplicate" % lid)
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
    return sorted(touched)


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
            before_m = measures(con)
            before_lines = before_m["rulebook_lines"]
            before_chars = before_m.get("rulebook_chars")
            prev_last = retro.get_meta(con, "last_cycle_ts")
            try:
                touched = _apply_writes(doc, con)
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
                has_replace = any(e.get("action") == "replace" for e in doc.get("rules") or [])
                has_shortens = any(e.get("shortens") for e in doc.get("rules") or []) or bool(doc.get("disable_rules"))
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
                       "touched": touched, "before": before_m, "after": measures(con),
                       "lessons_before": [before_rows[i] for i in touched if i in before_rows],
                       "changed_files": changed, "prev_last_cycle_ts": prev_last, "reverted": None}
                os.makedirs(cycles_dir(), exist_ok=True)
                pdata.write_text(os.path.join("cycles", cid + ".json"), json.dumps(rec, indent=1, sort_keys=True) + "\n")
                retro.set_meta(con, "last_cycle_ts", ts)
                con.commit()
                retro.export_jsonl()
                specs = ["overlay", "lessons.jsonl", "cycles"]
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
                    cols = [c for c in retro.LESSON_COLS if c != "id"]
                    con.execute("UPDATE lessons SET %s WHERE id=?" % ",".join(c + "=?" for c in cols),
                                [row.get(c) for c in cols] + [row["id"]])
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
                cols = [c for c in retro.LESSON_COLS if c != "id" and c in row]
                con.execute("UPDATE lessons SET %s WHERE id=?" % ",".join(c + "=?" for c in cols),
                            [row.get(c) for c in cols] + [row["id"]])
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
            specs = ["overlay", "lessons.jsonl", "cycles"]
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
    lines = ["Is it getting better?", "",
             "lessons: %d recorded, %d taking effect now, %d strengthened (rule or enforced), "
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
            out.append("  lesson %s: %s%s" % (e.get("lesson"), e.get("action"), extra))
        for e in doc.get("enforced") or []:
            out.append("  lesson %s: enforced %s %s" % (e.get("lesson"), e.get("type"),
                         e.get("cmd") or ("when=%s require_kind=%s" % (e.get("when"), e.get("require_kind")))))
        # predicted rulebook size with the rules applied in memory
        try:
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
                    parts.append("## %d. %s {#%s}\n\n%s" % (n, by_id[rid]["title"], rid, by_id[rid]["body"]))
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
        if sub in ("brief",):
            print(brief_text(), end="")
            return 0
        if sub == "apply":
            if len(args) != 2:
                print("usage: sisi cycle apply FILE")
                return 2
            rec = apply_file(args[1])
            print("applied %s: %s (rulebook %s lines; committed to the personal repository)"
                  % (rec["id"], rec["summary"] or "consolidation", rec["after"]["rulebook_lines"]))
            return 0
        if sub == "revert":
            rec = revert_cycle(args[1] if len(args) > 1 else None)
            print("reverted %s exactly; rulebook rebuilt" % rec["id"])
            return 0
        if sub == "status":
            for line in status_lines():
                print(line)
            return 0
        print("usage: sisi cycle [due|apply FILE|check FILE|--dry-run FILE|revert [ID]|status|help]  (no argument prints the brief)")
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
