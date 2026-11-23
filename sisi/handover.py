"""Project handover: project-scope records leave sisi's care for the project's own documents.

A learning or `sisi learn` statement the owner (or the retro) scoped to a project, explicitly,
waits here until an agent files it in that project's own design documentation or work list and
confirms with `sisi handover done ID --where PATH`. The items are read from the learning store;
a small filed log (id, project, path, date) keeps the trace of what was filed, and the user
store's git history keeps the rest.
"""
import json, os

from . import learning as L, paths, scope


def filed_path():
    return paths.data_file("handover-filed.jsonl")


def _filed():
    return {r.get("hid") for r in L._read_jsonl(filed_path())[0]}


def _item(r):
    pr = r.get("proposed") or {}
    return {"hid": r["id"], "kind": "learn" if r.get("owner_statement") else "lesson", "lesson_id": r["id"],
            "project": r.get("origin_project"), "date": r.get("created") or "",
            "text": pr.get("description") or r.get("title"), "change": pr.get("description"),
            "short": r.get("title"), "aim": (r.get("observation") or {}).get("impact"),
            "change_kind": pr.get("mechanism"), "moment": (r.get("observation") or {}).get("evidence"),
            "cause": r.get("root_cause"),
            "occurrences": [{"ts": p.get("ts"), "repo": p.get("project"), "tool": None}
                            for p in r.get("provenance") or []]}


def load_pile():
    """Project-scope records waiting to be filed: explicitly scoped to a project, written by sisi's
    own commands, not withdrawn, not yet filed."""
    ledger = L.load_ledger()
    done = _filed()
    return [_item(r) for r in L.load_learnings()
            if (r.get("proposed") or {}).get("scope_asked") == "project" and L.is_registered(r, ledger)
            and r.get("status") not in L.ENDED and not r.get("candidate") and r["id"] not in done]


def for_project(pid):
    return [it for it in load_pile() if it.get("project") == pid]


def notice(cwd):
    """The session-start / request-time line inside the owning project only."""
    items = for_project(scope.project_id(cwd))
    if not items:
        return ""
    return ("sisi: %d item(s) recorded by sisi belong to this project. File each in this project's own "
            "design documentation or work list (wherever this project keeps them; if it has neither, create "
            "a short section in its main agent instructions file or a docs file), then confirm each with "
            "`sisi handover done ID --where PATH`. `sisi handover` lists them in full."
            % len(items))


def _norm(t):
    return " ".join(str(t or "").split()).lower()


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
        out.append("  learning %s (%s/%s): %s" % (it.get("lesson_id"), it.get("aim"), it.get("change_kind"),
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
        rec = {"hid": it.get("hid"), "kind": it.get("kind"), "lesson_id": it.get("lesson_id"),
               "project": it.get("project"), "where": ap, "date": L.now()}
        from . import pdata
        pdata.write_text("handover-filed.jsonl", (pdata.read_text("handover-filed.jsonl", "") or "")
                         + json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
        pdata.commit("handover: %s filed in %s" % (it.get("hid"), ap), ["handover-filed.jsonl"])
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
