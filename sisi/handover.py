"""Project handover pile: project-scoped items leave the global store.

Scoping a lesson or a `sisi learn` statement to a project moves it here: a pile in
the personal store, keyed by project id, kept only until an agent files it in that
project's own design documentation or work list and confirms with
`sisi handover done ID --where PATH`. After confirmation the item is gone from
every global listing; a small filed log (id, project, path, date) keeps the trace,
and the personal store's git history keeps the rest.
"""
import json, os

from . import paths, scope, store


def pile_path():
    return paths.data_file("handover.json")


def filed_path():
    return paths.data_file("handover-filed.jsonl")


def load_pile():
    try:
        with open(pile_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def save_pile(items):
    os.makedirs(os.path.dirname(pile_path()), exist_ok=True)
    tmp = pile_path() + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, pile_path())


def _next_hid(items):
    n = len(items)
    try:
        with open(filed_path(), encoding="utf-8") as f:
            n += sum(1 for _ in f)
    except OSError:
        pass
    return "h%d" % (n + 1)


def add_item(item):
    items = load_pile()
    item = dict(item)
    item.setdefault("hid", _next_hid(items))
    item.setdefault("date", store.now())
    items.append(item)
    save_pile(items)
    return item


def for_project(pid):
    return [it for it in load_pile() if it.get("project") == pid]


def counts_by_project():
    out = {}
    for it in load_pile():
        out[it.get("project") or ""] = out.get(it.get("project") or "", 0) + 1
    return out


def notice(cwd):
    """The session-start / request-time line inside the owning project only."""
    try:
        items = for_project(scope.project_id(cwd))
    except Exception:
        return ""
    if not items:
        return ""
    return ("sisi: %d item(s) recorded by sisi belong to this project. File each in this project's own "
            "design documentation or work list (wherever this project keeps them; if it has neither, create "
            "a short section in its main agent instructions file or a docs file), then confirm each with "
            "`sisi handover done ID --where PATH`. `sisi handover` lists them in full."
            % len(items))


def _norm(t):
    return " ".join(str(t or "").split()).lower()


def move_lesson(con, lesson_id, pid):
    """Copy a lesson (with its occurrences, the historical example) into the pile and remove
    it from the delivered global data. Returns the pile item, or None."""
    r = con.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    occ = [dict(o) for o in con.execute("SELECT * FROM occurrences WHERE lesson_id=? ORDER BY id", (lesson_id,))]
    item = {"kind": "lesson", "lesson_id": d["id"], "project": pid,
            "date": d.get("created") or store.now(),
            "aim": d.get("aim"), "change_kind": d.get("change_kind"), "target": d.get("target"),
            "change": d.get("change"), "short": d.get("short"), "when": d.get("when_terms"),
            "moment": d.get("moment"), "cause": d.get("cause"),
            "occurrences": [{"ts": o.get("ts"), "repo": o.get("repo"), "cwd": o.get("cwd"),
                             "tool": o.get("tool"), "session": o.get("session"), "moment": o.get("moment")}
                            for o in occ]}
    con.execute("DELETE FROM impressions WHERE lesson_id=?", (lesson_id,))
    con.execute("DELETE FROM sightings WHERE lesson_id=?", (lesson_id,))
    # the occurrence rows stay: they are the history of the work itself (and what satisfies
    # the retro gate for that session), not delivered lesson data
    con.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
    return add_item(item)


def move_learn(rec, pid):
    item = {"kind": "learn", "project": pid, "date": rec.get("ts") or store.now(),
            "text": rec.get("text"), "cwd": rec.get("cwd"),
            "occurrences": [{"ts": rec.get("ts"), "repo": rec.get("cwd"), "tool": rec.get("tool")}]}
    return add_item(item)


def _find(items, ident):
    for it in items:
        if str(ident) in (str(it.get("hid")), str(it.get("lesson_id") or "")):
            return it
    return None


def _key_text(it):
    if it.get("kind") == "learn":
        return it.get("text") or ""
    return it.get("change") or it.get("short") or ""


def _item_lines(it):
    out = ["%s  %s  recorded %s  project %s" % (it.get("hid"), it.get("kind"), (it.get("date") or "")[:10],
                                               scope.project_label(it.get("project") or ""))]
    if it.get("kind") == "learn":
        out.append('  what the owner said: "%s"' % " ".join(str(it.get("text") or "").split()))
    else:
        out.append("  lesson #%s (%s/%s): %s" % (it.get("lesson_id"), it.get("aim"), it.get("change_kind"),
                                                " ".join(str(it.get("change") or "").split())))
        if it.get("short"):
            out.append("  short: %s" % it["short"])
        if it.get("moment"):
            out.append("  where it came from: %s (cause: %s)" % (" ".join(str(it["moment"]).split()),
                                                                 " ".join(str(it.get("cause") or "").split())))
    for o in it.get("occurrences") or []:
        out.append("  - %s  repo %s  tool %s" % ((o.get("ts") or "")[:10], o.get("repo") or o.get("cwd") or "-",
                                                o.get("tool") or "-"))
    return out


def main(argv):
    argv = list(argv)
    if argv and argv[0] == "done":
        if len(argv) < 2:
            print("usage: sisi handover done ID --where PATH [--quote FRAGMENT]")
            return 2
        ident = argv[1]
        where, quote, i = None, None, 2
        while i < len(argv):
            if argv[i] == "--where" and i + 1 < len(argv):
                where = argv[i + 1]; i += 2
            elif argv[i] == "--quote" and i + 1 < len(argv):
                quote = argv[i + 1]; i += 2
            else:
                print("usage: sisi handover done ID --where PATH [--quote FRAGMENT]")
                return 2
        if not where:
            print("sisi handover: --where PATH is required (the file in this project you filed it in)")
            return 2
        items = load_pile()
        it = _find(items, ident)
        if it is None:
            print("sisi handover: no waiting item %r (`sisi handover` lists them)" % ident)
            return 1
        cwd = os.getcwd()
        root = scope.project_id(cwd)
        # the file must be in this project
        ap = where if os.path.isabs(where) else os.path.join(cwd, where)
        ap = os.path.realpath(ap)
        from . import gitutil
        groot = gitutil.root(cwd)
        base = os.path.realpath(groot) if groot else os.path.realpath(cwd)
        if not (ap == base or ap.startswith(base + os.sep)):
            print("sisi handover: %s is not inside this project (%s); nothing was filed" % (where, base))
            return 1
        if not os.path.isfile(ap):
            print("sisi handover: %s does not exist in this project; nothing was filed" % where)
            return 1
        try:
            with open(ap, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            print("sisi handover: cannot read %s: %s" % (where, e))
            return 1
        need = quote if quote is not None else _key_text(it)
        if _norm(need) not in _norm(content):
            print("sisi handover: refused: %s does not contain the item's key text (%r). File it there "
                  "first, or pass --quote with a quoted fragment of the item that the file does contain."
                  % (where, " ".join(str(need).split())[:120]))
            return 1
        save_pile([x for x in items if x is not it])
        rec = {"hid": it.get("hid"), "kind": it.get("kind"), "lesson_id": it.get("lesson_id"),
               "project": it.get("project"), "where": ap, "date": store.now()}
        os.makedirs(os.path.dirname(filed_path()), exist_ok=True)
        with open(filed_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
        print("filed %s in %s; removed from the handover pile" % (ident, where))
        return 0
    if argv not in ([], ["--all"]):
        print("usage: sisi handover [--all] | done ID --where PATH [--quote FRAGMENT]")
        return 2
    items = load_pile() if argv == ["--all"] else for_project(scope.project_id(os.getcwd()))
    if not items:
        print("nothing waiting to be filed" + (" here" if argv != ["--all"] else ""))
        return 0
    for it in items:
        for line in _item_lines(it):
            print(line)
    return 0
