"""Moving personal data around: migrate (old layout to new), update (the product), export and import.
Nothing here writes inside the product. Every step that moves or replaces data first copies it into
<personal>/backups/<timestamp>-<reason>/."""
import io, json, os, shutil, sqlite3, subprocess, sys, tarfile, time

from . import overlay, paths, pdata, store


# ---- helpers ------------------------------------------------------------------------
def _read(p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _lines(p):
    t = _read(p)
    return t.splitlines() if t else []


def _union_lines(src, dst):
    """Append to dst the lines of src it lacks (dst first, order kept). Returns the number appended."""
    have = _lines(dst)
    seen = set(have)
    add = [l for l in _lines(src) if l not in seen and not seen.add(l)]
    if add:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "a", encoding="utf-8") as f:
            if have and not (_read(dst) or "").endswith("\n"):
                f.write("\n")
            f.write("\n".join(add) + "\n")
    return len(add)


def _copy_into(src, bdir, rel):
    dst = os.path.join(bdir, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, dirs_exist_ok=True)
    elif src.endswith(".db"):
        _sqlite_copy(src, dst)
    else:
        shutil.copy2(src, dst)


def _sqlite_copy(src, dst):
    """A consistent copy of a database that other processes may be writing."""
    a = sqlite3.connect(src, timeout=30)
    try:
        b = sqlite3.connect(dst)
        try:
            a.backup(b)
        finally:
            b.close()
    finally:
        a.close()


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


# ---- migrate ----------------------------------------------------------------------------
def _legacy_notes():
    if os.environ.get("SISI_NOTES"):
        return None
    d = paths.legacy_notes_dir()
    return d if os.path.isdir(d) and any(n.endswith(".md") for n in os.listdir(d)) else None


def _notes_pending(src_dir):
    dst = paths.notes_dir()
    for n in os.listdir(src_dir):
        if n.endswith(".md"):
            have = set(_lines(os.path.join(dst, n)))
            if any(l not in have for l in _lines(os.path.join(src_dir, n))):
                return True
    return False


def _merge_manifest(src, dst):
    a = json.loads(_read(src) or "{}")
    b = json.loads(_read(dst) or "{}")
    files = dict(a.get("files", {}))
    files.update(b.get("files", {}))
    dirs = list(dict.fromkeys(b.get("dirs", []) + a.get("dirs", [])))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(json.dumps({"dirs": dirs, "files": files}, indent=1, sort_keys=True) + "\n")


def _merge_retro_db(src, dst):
    """Both databases exist: bring the lessons of src that dst lacks into dst. Never drops or duplicates one."""
    a = sqlite3.connect(src, timeout=30)
    a.row_factory = sqlite3.Row
    b = sqlite3.connect(dst, timeout=30)
    b.row_factory = sqlite3.Row
    added = 0
    try:
        key = lambda r: (r["aim"], r["change_kind"], r["target"], r["change"])
        have = {key(r): r["id"] for r in b.execute("SELECT * FROM lessons")}
        for r in a.execute("SELECT * FROM lessons ORDER BY id"):
            if key(r) in have:
                lid = have[key(r)]
            else:
                bcols = [x[1] for x in b.execute("PRAGMA table_info(lessons)")]
                cols = [c for c in bcols if c != "id"]  # legacy schema, read from the db itself
                cur = b.execute("INSERT INTO lessons(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                                [r[c] if c in r.keys() else None for c in cols])
                lid = cur.lastrowid
                have[key(r)] = lid
                added += 1
            for o in a.execute("SELECT * FROM occurrences WHERE lesson_id=? ORDER BY id", (r["id"],)):
                if b.execute("SELECT 1 FROM occurrences WHERE lesson_id=? AND ts=? AND session IS ? AND moment=?",
                             (lid, o["ts"], o["session"], o["moment"])).fetchone():
                    continue
                ocols = [x[1] for x in b.execute("PRAGMA table_info(occurrences)")]
                cols = [c for c in ocols if c not in ("id", "lesson_id")]
                b.execute("INSERT INTO occurrences(lesson_id,%s) VALUES(?,%s)" % (",".join(cols), ",".join("?" * len(cols))),
                          [lid] + [o[c] if c in o.keys() else None for c in cols])
        b.commit()
    finally:
        a.close()
        b.close()
    return added


def _move_retro_db(src, dst, notes):
    if not os.path.exists(dst):
        hold = sqlite3.connect(src, timeout=30)
        try:
            hold.execute("BEGIN IMMEDIATE")  # other writers wait while the copy is made; readers still read
            tmp = dst + ".tmp%d" % os.getpid()
            _sqlite_copy(src, tmp)
            os.replace(tmp, dst)
            notes.append("retro.db moved to the personal data folder")
        finally:
            hold.rollback()
            hold.close()
    else:
        n = _merge_retro_db(src, dst)
        notes.append("retro.db: both old and new existed; merged %d lesson(s) that the new one lacked" % n)
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.unlink(src + suffix)
        except OSError:
            pass


STATE_JSONL = ("learn.jsonl", "learn-quarantine.jsonl", "notes.jsonl", "proposals.jsonl")


def pending():
    """What migrate would move, as a list of short names."""
    out, st = [], paths.state()
    if _same(st, paths.data()):
        return out
    o = paths.canon("oracle.md")
    if os.path.isfile(o) and not os.path.exists(paths.data_file("oracle.md")):
        out.append("oracle.md")
    n = _legacy_notes()
    if n and _notes_pending(n):
        out.append("notes/")
    for name in ("trusted.json", "config.json", "retro.db", "manifest.json", "backups") + STATE_JSONL:
        if os.path.exists(os.path.join(st, name)):
            out.append(name)
    return out


def run():
    """Move an old-layout installation into the new layout. Idempotent. Returns a list of notes."""
    todo = pending()
    pdata.ensure()
    notes = []
    if todo:
        with pdata.lock():
            bdir = pdata.backup_dir("migrate")
            st, data = paths.state(), paths.data()
            # 1. back up everything that will be moved
            for name in todo:
                if name == "oracle.md":
                    _copy_into(paths.canon("oracle.md"), bdir, "product/canon/oracle.md")
                elif name == "notes/":
                    _copy_into(_legacy_notes(), bdir, "product/notes")
                else:
                    _copy_into(os.path.join(st, name), bdir, "state/" + name)
            notes.append("backed up what will move to %s" % bdir)
            # 2. move
            for name in todo:
                src = os.path.join(st, name)
                if name == "oracle.md":
                    pdata.write_text("oracle.md", _read(paths.canon("oracle.md")))
                    notes.append("oracle.md copied to the personal data folder (the product's copy is left alone; delete it from the clone)")
                elif name == "notes/":
                    d = paths.notes_dir()
                    os.makedirs(d, exist_ok=True)
                    nn = _legacy_notes()
                    for f in sorted(os.listdir(nn)):
                        if f.endswith(".md"):
                            if os.path.exists(os.path.join(d, f)):
                                _union_lines(os.path.join(nn, f), os.path.join(d, f))
                            else:
                                shutil.copy2(os.path.join(nn, f), os.path.join(d, f))
                    notes.append("field notes copied to %s (the product's notes/ is left alone; delete it from the clone)" % d)
                elif name == "trusted.json":
                    cur = []
                    for p in (paths.data_file("trusted.json"), src):
                        try:
                            cur += [x for x in json.loads(_read(p) or "[]") if isinstance(x, str)]
                        except ValueError:
                            pass
                    pdata.write_text("trusted.json", json.dumps(sorted(set(cur)), indent=1))
                    os.unlink(src)
                    notes.append("trusted.json moved")
                elif name == "config.json":
                    if os.path.exists(paths.data_file("config.json")):
                        notes.append("config.json: a personal one already exists; the old one stays only in the backup")
                        os.unlink(src)
                    else:
                        shutil.move(src, paths.data_file("config.json"))
                        notes.append("config.json moved")
                elif name == "retro.db":
                    _move_retro_db(src, paths.data_file("retro.db"), notes)
                elif name == "manifest.json":
                    _merge_manifest(src, paths.data_file("install", "manifest.json"))
                    os.unlink(src)
                    notes.append("install manifest moved")
                elif name == "backups":
                    d = paths.data_file("install", "backups")
                    os.makedirs(d, exist_ok=True)
                    for f in os.listdir(src):
                        if not os.path.exists(os.path.join(d, f)):
                            shutil.copy2(os.path.join(src, f), os.path.join(d, f))
                    shutil.rmtree(src)
                    notes.append("install backups moved")
                else:
                    _union_lines(src, paths.data_file(name))
                    os.unlink(src)
                    notes.append("%s moved" % name)
        pdata.commit("migrate: move personal data out of the product and the state folder", strict=True)
    notes += pdata.upgrade()
    notes += migrate_learnings()
    return notes


def _jsonl_rows(path):
    """(rows, malformed line count) of a jsonl file that may not exist."""
    rows, bad = [], 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(d, dict):
                    rows.append(d)
                else:
                    bad += 1
    except OSError:
        pass
    return rows, bad


def migrate_learnings():
    """Old lesson store -> learning records. Whenever the old store exists and the `migrated`
    marker does not; a backup first; merged by legacy id (a lesson already carried over is not
    carried twice, so running `sisi learn` before the first migration loses nothing).

    lessons.jsonl and the sqlite store hold lesson rows, occurrence rows, impression rows (sisi's
    own showings, dropped: never evidence) and pattern rows (not carried; the backup keeps them).
    Lessons become learning records with honest statuses (folded into prose is `implemented`,
    always unvalidated; nothing becomes `validated`); occurrences become provenance, with the old
    repo values normalised to the project key new code uses; a learning is earned wider only under
    the same two-units-two-projects rule as a new one. learn.jsonl owner statements become
    owner-statement records, keeping their scope. Malformed lines are counted, not hidden. Returns
    notes with the counts.
    """
    from . import learning as L
    marker = paths.data_file("learnings-migrated.json")
    if os.path.exists(marker):
        return []
    src = paths.data_file("lessons.jsonl")
    learn_src = paths.data_file("learn.jsonl")
    db = paths.data_file("retro.db")
    if not (os.path.exists(src) or os.path.exists(learn_src) or os.path.exists(db)):
        return []
    bdir = snapshot("learning-migration")
    lessons, occs = {}, {}
    dropped = {"impression": 0, "sighting": 0, "pattern": 0}
    malformed = {"lessons.jsonl": 0, "learn.jsonl": 0}
    jrows, malformed["lessons.jsonl"] = _jsonl_rows(src)
    for r in jrows:
        t = r.get("t")
        if t == "lesson":
            lessons[r.get("id")] = r
        elif t == "occurrence":
            occs[r.get("id")] = r
        elif t in dropped:
            dropped[t] += 1
    if os.path.exists(db):
        con = sqlite3.connect(db, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            for r in con.execute("SELECT * FROM lessons ORDER BY id"):
                lessons.setdefault(r["id"], dict(r))
            for r in con.execute("SELECT * FROM occurrences ORDER BY id"):
                occs.setdefault(r["id"], dict(r))
        except sqlite3.Error:
            pass
        finally:
            con.close()
    rows = L.load_learnings()
    have_legacy = {r.get("legacy_id") for r in rows if r.get("legacy_id") is not None}
    have_text = {" ".join(str((r.get("proposed") or {}).get("description") or "").lower().split())
                 for r in rows if r.get("owner_statement")}
    by_lesson = {}
    for o in occs.values():
        by_lesson.setdefault(o.get("lesson_id"), []).append(o)
    added, already, attached, touched = 0, 0, 0, []
    for lid in sorted(lessons, key=lambda x: (x is None, x)):
        if lid in have_legacy:
            already += 1
            continue
        old = lessons[lid]
        prov = []
        for o in sorted(by_lesson.get(lid, []), key=lambda x: x.get("id") or 0):
            proj = L.normalize_project(o.get("repo") or o.get("cwd") or old.get("project"))
            unit = ("session:%s" % o["session"]) if o.get("session") else "legacy:%s:%s" % (lid, proj)
            prov.append({"unit": unit, "project": proj, "ts": o.get("ts") or "", "kind": "occurrence"})
        attached += len(prov)
        origin = L.normalize_project(old.get("project")) or (prov[0]["project"] if prov else "")
        if not prov:
            prov = [{"unit": "legacy:%s" % lid, "project": origin, "ts": old.get("created") or "", "kind": "origin"}]
        status = {"applied": "implemented", "retired": "reverted"}.get(old.get("status"), "observed")
        kind = old.get("change_kind")
        target = str(old.get("target") or "")
        rec = {
            "id": L.next_id(rows), "legacy_id": lid,
            "title": L.derive_title(old.get("short") or old.get("change") or old.get("moment") or ""),
            "source_unit": prov[0]["unit"], "origin_project": origin,
            "observation": {"evidence": L.scrub_secrets(old.get("moment") or ""), "impact": "correctness"},
            "root_cause": L.scrub_secrets(old.get("cause") or ""),
            "proposed": {"description": L.scrub_secrets(old.get("change") or ""),
                         "mechanism": "tool" if kind == "tool" else ("verification" if kind in ("check", "test") else "policy"),
                         "scope": "project", "scope_asked": None,
                         "target": target[5:] if target.startswith("rule:") else (target or None)},
            "expected_effect": "", "limits": "", "why_not": "",
            "validation": {"method": "", "benchmark": None, "result": "unvalidated",
                           "detail": "migrated from the old lesson store; never replay-validated"},
            "status": status, "version": 1, "confidence": "low", "provenance": prov,
            "terms": L.derive_terms(old.get("moment") or "", old.get("cause") or "", old.get("change") or ""),
            "owner_statement": False, "candidate": False,
            "recurrences_after_promotion": 0, "flagged_not_working": False,
            "promoted_at": None, "mechanism_ref": old.get("folded_into"),
            "replay": None, "created": old.get("created") or L.now()}
        rows.append(rec)
        touched.append(rec)
        added += 1
    orphans = sum(len(v) for k, v in by_lesson.items() if k not in lessons)
    srows, malformed["learn.jsonl"] = _jsonl_rows(learn_src)
    statements, dup = 0, 0
    for r in srows:
        text = r.get("text") or r.get("statement") or ""
        if not text:
            continue
        key = " ".join(text.lower().split())
        if key in have_text:
            dup += 1
            continue
        have_text.add(key)
        statements += 1
        scope = r.get("scope") if r.get("scope") in ("user", "project", "organization") else "user"
        proj = L.normalize_project(r.get("cwd"))
        text = L.scrub_secrets(text)
        rec = {
            "id": L.next_id(rows), "title": L.derive_title(text),
            "source_unit": "owner", "origin_project": proj,
            "observation": {"evidence": text, "impact": "value"},
            "root_cause": "owner statement",
            "proposed": {"description": text, "mechanism": "knowledge", "scope": scope,
                         "scope_asked": scope, "target": None},
            "expected_effect": "the agent acts on this statement", "limits": "", "why_not": "",
            "validation": {"method": "", "benchmark": None, "result": "unvalidated", "detail": ""},
            "status": "promoted", "version": 1, "confidence": "high",
            "provenance": [{"unit": "owner", "project": proj, "ts": r.get("ts") or "", "kind": "origin"}],
            "terms": L.derive_terms(text), "owner_statement": True, "candidate": False,
            "statement_origin": "migrated from the old statement file",
            "recurrences_after_promotion": 0,
            "flagged_not_working": False, "promoted_at": r.get("ts") or L.now(),
            "mechanism_ref": None, "replay": None, "created": r.get("ts") or L.now()}
        rows.append(rec)
        touched.append(rec)
    counts = {"lessons_in_old_store": len(lessons), "lessons_migrated": added, "lessons_already_migrated": already,
              "owner_statements_migrated": statements, "owner_statements_duplicate": dup,
              "occurrences_attached": attached, "occurrences_without_a_lesson": orphans,
              "malformed_lines_skipped": dict(malformed), "dropped_rows": dict(dropped),
              "learning_records_after": len(rows)}
    pdata.ensure()
    pdata.write_text("learnings-migrated.json", json.dumps(dict(counts, ts=L.now(), backup=bdir), indent=2, sort_keys=True) + "\n")
    L.save_learnings(rows, "migrate: lessons and owner statements become learning records", created=touched, via="migration")
    pdata.commit("migrate: learning migration recorded", ["learnings-migrated.json"])
    return ["learning migration: backed up to %s; %d lesson(s) in the old store, %d carried over (%d already there); "
            "%d owner statement(s) carried over (%d duplicate); %d occurrence(s) attached as provenance, %d without "
            "a lesson left out; %d malformed line(s) skipped (lessons.jsonl %d, learn.jsonl %d); dropped as not "
            "evidence or not carried: %d impression(s), %d sighting(s), %d pattern row(s); now %d learning record(s); "
            "nothing is validated" % (bdir, len(lessons), added, already, statements, dup, attached, orphans,
                                      sum(malformed.values()), malformed["lessons.jsonl"], malformed["learn.jsonl"],
                                      dropped["impression"], dropped["sighting"], dropped["pattern"], len(rows))]


# ---- snapshots (before an update) -------------------------------------------------------------
SKIP_TOP = {"backups", "generated", "install", ".lock"}


def snapshot(reason):
    """Copy personal data (without backups, generated files and install records) into backups/. Returns the folder."""
    bdir = pdata.backup_dir(reason)
    d = paths.data()
    for n in sorted(os.listdir(d)):
        if n in SKIP_TOP or n.startswith("retro.db") or ".tmp" in n:
            continue
        _copy_into(os.path.join(d, n), bdir, n)
    if os.path.exists(paths.data_file("retro.db")):
        _sqlite_copy(paths.data_file("retro.db"), os.path.join(bdir, "retro.db"))
    return bdir


# ---- update ---------------------------------------------------------------------------------------
def _pgit(*a, timeout=120):
    return subprocess.run(["git", "-C", paths.REPO] + list(a), capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))


def cmd_update(args):
    if "--post" in args:
        return post_update()
    say = print
    try:
        top = _pgit("rev-parse", "--show-toplevel")
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(paths.REPO):
            say("sisi update: %s is not a git clone, so there is nothing to fetch. Replace it with a newer copy and run "
                "`sisi update --post` to rebuild." % paths.REPO)
            return 1
        if _pgit("rev-parse", "--verify", "-q", "HEAD").returncode != 0:
            say("sisi update: the product repository has no commits yet; nothing to update.")
            return 1
        up = _pgit("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        if up.returncode != 0:
            say("sisi update: the product has no upstream branch. Set one (`git -C %s branch --set-upstream-to=origin/main`) "
                "and try again. Nothing was changed." % paths.REPO)
            return 1
        dirty = _pgit("status", "--porcelain", "--untracked-files=no").stdout.strip()
        if dirty:
            say("sisi update: the product has local changes, so it will not be updated (nothing is ever discarded):\n%s\n"
                "Commit or stash them, then run `sisi update` again." % dirty)
            return 1
        f = _pgit("fetch", "--quiet")
        if f.returncode != 0:
            say("sisi update: fetch failed: %s" % (f.stderr.strip() or f.stdout.strip()))
            return 1
        before = _pgit("rev-parse", "HEAD").stdout.strip()
        m = _pgit("merge", "--ff-only", "--quiet", "@{u}")
        if m.returncode != 0:
            say("sisi update: the product cannot be fast-forwarded to %s (local commits?): %s\nNothing was changed."
                % (up.stdout.strip(), m.stderr.strip() or m.stdout.strip()))
            return 1
        after = _pgit("rev-parse", "HEAD").stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        say("sisi update: git failed: %r" % e)
        return 1
    say("product: %s" % ("already up to date at %s" % after[:10] if before == after else "%s -> %s" % (before[:10], after[:10])))
    sys.stdout.flush()
    # continue in a fresh process so the new code does the rest
    p = subprocess.run([sys.executable, paths.launcher(), "update", "--post"], capture_output=True, text=True)
    print(p.stdout, end="")
    print(p.stderr, end="", file=sys.stderr)
    return p.returncode


def post_update():
    """After the product changed: back up personal data, migrate its format, keep replacements, rebuild, check."""
    try:
        pdata.ensure()
        print("backup: %s" % snapshot("update"))
        for n in run():
            print(n)
        for r in overlay.scan_retests():
            if str(r.get("action", "")).startswith("stale"):
                print("rule %s: %s (queued in retest.jsonl)" % (r["id"], r["action"]))
            else:
                print("kept your version of %s %s; its base changed in this update, queued in retest.jsonl" % (r["kind"], r["id"]))
        b = overlay.build_canon()
        print("rulebook rebuilt: %d lines%s" % (b["lines"], " - OVER THE %d-LINE BUDGET; shorten or replace a rule" % overlay.MAX_LINES if b["over_budget"] else ""))
    except pdata.DataError as e:
        print("sisi update: %s" % e)
        return 1
    from . import cli
    print("doctor:")
    return cli.cmd_wiring("doctor")


# ---- export / import ------------------------------------------------------------------------------
def _tar_filter(ti):
    parts = ti.name.split("/")
    if len(parts) > 1 and parts[0] == "personal" and (parts[1] in SKIP_TOP or parts[1].startswith("retro.db") or ".tmp" in parts[1]):
        return None
    return ti


def export(path=None):
    path = path or os.path.join(os.getcwd(), "sisi-export-%s.tar.gz" % time.strftime("%Y%m%d-%H%M%S"))
    pdata.ensure()
    tmpdb = None
    with pdata.lock():
        with tarfile.open(path, "w:gz") as tf:
            meta = json.dumps({"sisi_export": 1, "personal_format": pdata.version(),
                               "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}).encode()
            ti = tarfile.TarInfo("sisi-export.json")
            ti.size, ti.mtime = len(meta), int(time.time())
            tf.addfile(ti, io.BytesIO(meta))
            tf.add(paths.data(), arcname="personal", filter=_tar_filter)
            if os.path.exists(paths.data_file("retro.db")):
                import tempfile
                fd, tmpdb = tempfile.mkstemp(suffix=".db")
                os.close(fd)
                _sqlite_copy(paths.data_file("retro.db"), tmpdb)
                tf.add(tmpdb, arcname="personal/retro.db")
            st = paths.state()
            for name in ("results.jsonl", "sessions"):
                if os.path.exists(os.path.join(st, name)):
                    tf.add(os.path.join(st, name), arcname="state/" + name)
    if tmpdb:
        try:
            os.unlink(tmpdb)
        except OSError:
            pass
    return path


def _safe(name):
    return not (name.startswith("/") or ".." in name.split("/") or "\0" in name)


def import_archive(path):
    """Restore an export. Returns notes. The existing personal folder, if any, is set aside, never deleted."""
    notes = []
    try:
        tf = tarfile.open(path, "r:*")
    except (OSError, tarfile.TarError) as e:
        raise pdata.DataError("cannot read %s: %s" % (path, e))
    with tf:
        members = tf.getmembers()
        try:
            meta = json.loads(tf.extractfile("sisi-export.json").read())
        except (KeyError, ValueError, AttributeError):
            raise pdata.DataError("%s is not a sisi export (no sisi-export.json)" % path)
        if int(meta.get("personal_format", 0)) > pdata.FORMAT_VERSION:
            raise pdata.DataError("the export is personal-data format %s, newer than this sisi understands (%d); update sisi first"
                                  % (meta.get("personal_format"), pdata.FORMAT_VERSION))
        for m in members:
            if not _safe(m.name) or not (m.isfile() or m.isdir()) or \
                    not (m.name == "sisi-export.json" or m.name.split("/")[0] in ("personal", "state")):
                raise pdata.DataError("the archive holds an unexpected entry %r; nothing was restored" % m.name)
        data = paths.data()
        if os.path.isdir(data) and os.listdir(data):
            aside = "%s.before-import-%s" % (data.rstrip("/"), time.strftime("%Y%m%d-%H%M%S"))
            os.rename(data, aside)
            notes.append("the existing personal data was set aside at %s" % aside)
        os.makedirs(data, exist_ok=True)
        st = paths.state()
        for m in members:
            head, _, rel = m.name.partition("/")
            if head == "personal":
                dst = os.path.join(data, rel) if rel else data
            elif head == "state" and rel:
                dst = os.path.join(st, rel)
                if os.path.exists(dst) and not m.isdir():
                    if rel == "results.jsonl":
                        tmp = dst + ".import"
                        with open(tmp, "wb") as f:
                            f.write(tf.extractfile(m).read())
                        _union_lines(tmp, dst)
                        os.unlink(tmp)
                    continue
            else:
                continue
            if m.isdir():
                os.makedirs(dst, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(tf.extractfile(m).read())
            os.chmod(dst, m.mode & 0o777 or 0o644)
            os.utime(dst, (m.mtime, m.mtime))
    notes += migrate_learnings()
    notes += pdata.upgrade()
    b = overlay.build_canon()
    notes.append("rulebook rebuilt: %d lines" % b["lines"])
    return notes
