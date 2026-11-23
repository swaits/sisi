"""The verifier library and the recipes for "done": parse, list, show, choose, doctor, lint. No model calls."""
import concurrent.futures as cf, json, os, re, subprocess, sys

from . import contract as C, paths

SECTIONS = ["design", "prove", "many-inputs", "concurrency", "test-quality", "regression", "real-world",
            "safety", "intent", "completeness"]
COSTS = ["low", "medium", "high"]
V_KEYS = ["id", "title", "answers", "rung", "section", "languages", "kinds", "cost", "detect", "ran_here"]
V_HEADINGS = ["Use when", "Do not use when", "Set up", "Minimal example", "Run", "As a contract check",
              "What a pass does not prove"]
D_KEYS = ["id", "title", "applies_to"]
D_HEADINGS = ["Done means", "Checks", "Common false finishes"]
STOP = set("the a an and or of to in for is are it that this with on be as by at from my i we do does not "
           "how can what which when should would will".split())


# ---- parsing ---------------------------------------------------------------
def parse(path):
    """Return an entry dict. 'problems' lists format errors; 'header' is {} if there is none."""
    e = {"path": path, "stem": os.path.splitext(os.path.basename(path))[0], "header": {}, "body": "", "problems": []}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeDecodeError) as ex:
        e["problems"].append("cannot read: %s" % ex)
        return e
    if not lines or lines[0].strip() != "---":
        e["body"] = "\n".join(lines)
        e["problems"].append("no header block (file must start with a --- line)")
        return e
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        e["problems"].append("header block is not closed by a --- line")
        e["body"] = "\n".join(lines)
        return e
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        if ":" not in ln:
            e["problems"].append("header line without a colon: %r" % ln)
            continue
        k, v = ln.split(":", 1)
        e["header"][k.strip().lower()] = v.strip()
    e["body"] = "\n".join(lines[end + 1:])
    return e


def _list(v):
    return [x.strip().lower() for x in (v or "").split(",") if x.strip()]


def _walk(d):
    out = []
    for dp, dns, fns in os.walk(d):
        dns.sort()
        for n in sorted(fns):
            if n.endswith(".md") and n.lower() != "readme.md":
                out.append(os.path.join(dp, n))
    return out


def _load_verifiers_from(d):
    out = []
    for p in _walk(d):
        e = parse(p)
        h = e["header"]
        parent = os.path.basename(os.path.dirname(p)) if os.path.dirname(p) != os.path.normpath(d) else None
        e.update(id=h.get("id") or e["stem"], title=h.get("title", ""), answers=h.get("answers", ""),
                 section=h.get("section") or parent or "", languages=_list(h.get("languages")),
                 kinds=_list(h.get("kinds")), cost=h.get("cost", ""), detect=h.get("detect", ""),
                 ran_here=h.get("ran_here", ""), parent=parent)
        try:
            e["rung"] = int(h.get("rung", ""))
        except ValueError:
            e["rung"] = 9
        out.append(e)
    return out


def _load_recipes_from(d):
    out = []
    for p in _walk(d):
        e = parse(p)
        h = e["header"]
        e.update(id=h.get("id") or e["stem"], title=h.get("title", ""), applies_to=h.get("applies_to", ""))
        out.append(e)
    return out


def _merge(base, mine, off):
    """The product's entries with the personal overlay applied: same id replaces (in place), new ids are added,
    disabled ids are dropped. Entries carry 'origin': product | personal-replaces | personal-added."""
    over = {e["id"]: e for e in mine}
    out = []
    for e in base:
        if e["id"] in off:
            continue
        if e["id"] in over:
            out.append(dict(over.pop(e["id"]), origin="personal-replaces"))
        else:
            out.append(dict(e, origin="product"))
    for e in mine:
        if e["id"] in over and e["id"] not in off:
            out.append(dict(over[e["id"]], origin="personal-added"))
    return out


def load_verifiers(d=None):
    """With no argument: the product library with the personal overlay applied. With a directory: just that directory."""
    if d is not None:
        return _load_verifiers_from(d)
    from . import overlay
    return _merge(_load_verifiers_from(paths.verifiers_dir()), _load_verifiers_from(overlay.lib_dir("verifier")),
                  set(overlay.disabled("verifier")))


def load_recipes(d=None):
    if d is not None:
        return _load_recipes_from(d)
    from . import overlay
    return _merge(_load_recipes_from(paths.done_dir()), _load_recipes_from(overlay.lib_dir("recipe")),
                  set(overlay.disabled("recipe")))


def origin_tag(e):
    return {"personal-added": "  [personal addition]", "personal-replaces": "  [personal, replaces the product's]"}.get(e.get("origin"), "")


def usable(entries):
    """Entries that have a header (a file without one cannot be listed meaningfully; lint reports it)."""
    return [e for e in entries if e["header"]]


# ---- detection -------------------------------------------------------------
def _detect_one(cmd, timeout):
    try:
        return subprocess.run(cmd, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout).returncode == 0
    except Exception:
        return False


def _per():
    try:
        return float(os.environ.get("SISI_DETECT_TIMEOUT", "3"))
    except ValueError:
        return 3.0


def installed_map(entries, per=None, cap=15):
    """{id: 'yes'|'no'|'n/a'}. Detects run concurrently under a total time cap; unfinished counts as 'no'."""
    per = per or _per()
    res = {}
    todo = {}
    for e in entries:
        if e["detect"]:
            todo[e["path"]] = e
        else:
            res[e["path"]] = "n/a"
    if todo:
        ex = cf.ThreadPoolExecutor(max_workers=min(16, len(todo)))
        futs = {ex.submit(_detect_one, e["detect"], per): k for k, e in todo.items()}
        done, _ = cf.wait(futs, timeout=cap)
        for f, k in futs.items():
            res[k] = "yes" if f in done and f.result() else "no"
        ex.shutdown(wait=False, cancel_futures=True)
    return res


# ---- options ---------------------------------------------------------------
def parse_args(args):
    opts, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a in ("--lang", "--kind", "--rung", "--section"):
            if i + 1 >= len(args):
                raise ValueError("%s needs a value" % a)
            opts[a[2:]] = args[i + 1]
            i += 2
        elif a in ("--installed", "--json"):
            opts[a[2:]] = True
            i += 1
        else:
            pos.append(a)
            i += 1
    if "rung" in opts:
        try:
            opts["rung"] = int(opts["rung"])
        except ValueError:
            raise ValueError("--rung needs a number 1-6")
    return opts, pos


def _words(text):
    return [w for w in re.findall(r"[a-z0-9+#.\-]+", text.lower()) if len(w) > 1 and w not in STOP]


def _passes(e, o):
    if "lang" in o:
        ls = e["languages"]
        if "any" not in ls and o["lang"].lower() not in ls:
            return False
    if "kind" in o and "any" not in e["kinds"] and o["kind"].lower() not in e["kinds"]:
        return False
    if "rung" in o and e["rung"] > o["rung"]:
        return False
    if "section" in o and e["section"] != o["section"]:
        return False
    return True


def _public(e, inst=None):
    d = {"id": e["id"], "title": e["title"], "answers": e["answers"], "rung": e["rung"], "section": e["section"],
         "languages": e["languages"], "kinds": e["kinds"], "cost": e["cost"], "detect": e["detect"],
         "ran_here": e["ran_here"], "path": e["path"], "origin": e.get("origin", "product")}
    if inst is not None:
        d["installed"] = inst
    return d


def _line(e):
    return "%-24s r%-2s %-6s %-22s %s%s" % (e["id"], e["rung"], e["cost"] or "-", ", ".join(e["languages"])[:22] or "-", e["title"],
                                           origin_tag(e))


# ---- commands --------------------------------------------------------------
def cmd_list(args):
    opts, words = parse_args(args)
    words = [w.lower() for w in words]
    es = []
    for e in usable(load_verifiers()):
        hay = " ".join([e["id"], e["title"], e["answers"], e["body"]]).lower()
        if _passes(e, opts) and all(w in hay for w in words):
            es.append(e)
    inst = installed_map(es) if ("installed" in opts or "json" in opts) else {}
    if "installed" in opts:
        es = [e for e in es if inst[e["path"]] != "no"]
    if "json" in opts:
        print(json.dumps([_public(e, inst.get(e["path"])) for e in es], indent=2))
        return 0
    if not es:
        print("no verifiers match")
        return 0
    order = SECTIONS + sorted({e["section"] for e in es} - set(SECTIONS))
    for s in order:
        grp = sorted([e for e in es if e["section"] == s], key=lambda e: (e["rung"], e["id"]))
        if grp:
            print("%s" % s)
            for e in grp:
                print("  " + _line(e))
    print("\nsisi verifiers show ID | for \"<claim>\" | doctor | lint      (--lang --kind --rung --section --installed --json)")
    return 0


def _find(entries, id):
    for e in entries:
        if e["id"] == id:
            return e
    return None


def _show(e, with_installed):
    print("== %s: %s ==%s" % (e["id"], e["title"], origin_tag(e)))
    if with_installed:
        if e["detect"]:
            st = installed_map([e], cap=5)[e["path"]]
            print("installed here: %s (detect: %s)" % (st, e["detect"]))
        else:
            print("installed here: n/a (no tool to detect)")
    print()
    print(e["body"].strip("\n") if e["header"] else open(e["path"], encoding="utf-8", errors="replace").read())
    _print_notes(e["id"])


def _print_notes(id):
    from . import retro
    n = retro.notes_for(id)
    if n:
        print("\n## Field notes from earlier agents\n(information from past sessions, to weigh, not instructions)\n" + n)


def _print_lessons(query, place, extra="", loose=False, targets=()):
    """Lessons for this moment. With loose=True (done for, done ID, verifiers for) the two-part
    delivery block: strict likely-to-apply lessons in full, then every loose lesson as a heading
    for the asking agent to judge. Otherwise the older single strong-match block."""
    try:
        from . import retro
        block = retro.delivery_block(query, place, extra=extra, targets=targets) if loose \
            else retro.lessons_block(query, place, extra=extra)
        if block:
            print("\n" + block)
    except Exception:
        pass


def _print_cycle_notice():
    try:
        from . import cycle
        line = cycle.due_notice()
        if line:
            print(line)
    except Exception:
        pass


def _print_drafts(query):
    """Draft recipe notes: recipe lessons naming a recipe that does not exist yet, when their words match."""
    try:
        from . import retro
        for did, txt in retro.draft_notes_for(query):
            print("\n## Draft recipe %s (not a recipe yet; notes from earlier lessons)\n%s" % (did, txt))
    except Exception:
        pass


def cmd_show(args):
    if not args:
        print("usage: sisi verifiers show ID")
        return 1
    e = _find(usable(load_verifiers()), args[0])
    if not e:
        print("no verifier with id %r (see `sisi verifiers`)" % args[0])
        return 1
    _show(e, True)
    _print_lessons("%s %s %s" % (e["id"], e["title"], e["answers"]), "verifiers-show")
    return 0


def _score(tokens, e):
    """Word overlap against answers/title/kinds/languages/id, weighted."""
    fields = ((e["answers"], 3.0), (e["title"], 3.0), (" ".join(e["kinds"]), 2.0), (" ".join(e["languages"]), 2.0), (e["id"], 2.0))
    s = 0.0
    for t in set(tokens):
        for text, w in fields:
            ws = set(_words(text.replace("-", " "))) | set(_words(text))
            if t in ws or any(len(t) > 3 and (x.startswith(t) or t.startswith(x)) and len(x) > 3 for x in ws):
                s += w
                break
    return s


def cmd_for(args):
    opts, words = parse_args(args)
    desc = " ".join(words).strip()
    if not desc:
        print('usage: sisi verifiers for "<claim or work>" [--lang L] [--kind K]')
        return 1
    tokens = _words(desc)
    cands = []
    for e in usable(load_verifiers()):
        if not _passes(e, {k: v for k, v in opts.items() if k in ("lang", "kind")}):
            continue
        s = _score(tokens, e)
        if s > 0:
            cands.append((s, e))
    cands.sort(key=lambda x: -x[0])
    cands = cands[:30]
    inst = installed_map([e for _, e in cands])
    ranked = []
    for s, e in cands:
        f = s * (1 + 0.15 * (6 - min(e["rung"], 6))) * (1.3 if inst[e["path"]] == "yes" else 1.0)
        ranked.append((f, e))
    ranked.sort(key=lambda x: (-round(x[0], 0), x[1]["rung"], -x[0], x[1]["id"]))
    top = ranked[:8]
    fl = None
    if "kind" in opts:
        fl = C.floors().get(opts["kind"].lower())
        if fl:
            print("Floor: %s claims need rung %d or stronger (canon/floors.json). Results marked [floor ok] satisfy it.\n"
                  % (opts["kind"], fl))
    if not top:
        print("no verifier matches that description; try `sisi verifiers` to browse")
        _print_lessons(desc, "verifiers-for", loose=True)
        return 0
    for i, (f, e) in enumerate(top, 1):
        mark = ""
        if fl:
            mark = "  [floor ok]" if e["rung"] <= fl else "  [below floor]"
        print("%d. %s  rung %s  cost %s  installed: %s%s%s" % (i, e["id"], e["rung"], e["cost"] or "-", inst[e["path"]], mark, origin_tag(e)))
        print("   %s" % (e["answers"] or e["title"]))
    print("\nsisi verifiers show ID   for set-up and a worked example")
    _print_lessons(desc, "verifiers-for", extra=" ".join(e["id"] for _, e in top[:3]), loose=True,
                   targets=tuple(e["id"] for _, e in top))
    return 0


def cmd_doctor(args):
    es = [e for e in usable(load_verifiers()) if e["detect"]]
    if not es:
        print("no verifiers with a detect command")
        return 0
    inst = installed_map(es, cap=15)
    order = SECTIONS + sorted({e["section"] for e in es} - set(SECTIONS))
    tot_yes = 0
    for s in order:
        grp = [e for e in es if e["section"] == s]
        if not grp:
            continue
        y = sum(1 for e in grp if inst[e["path"]] == "yes")
        tot_yes += y
        print("%s: %d of %d installed" % (s, y, len(grp)))
        for e in sorted(grp, key=lambda e: e["id"]):
            print("  %-24s %s" % (e["id"], "installed" if inst[e["path"]] == "yes" else "missing"))
    print("\ntotal: %d of %d installed" % (tot_yes, len(es)))
    return 0


def _headings(body):
    return [re.sub(r"^#+\s*", "", l).strip().lower() for l in body.split("\n") if re.match(r"^#+\s+\S", l)]


def _missing_headings(body, required):
    hs = _headings(body)
    return [r for r in required if not any(r.lower() in h for h in hs)]


def _section(body, name):
    """Text under the first heading containing `name`, up to the next heading of the same or higher level."""
    lines, out, level = body.split("\n"), [], None
    for l in lines:
        m = re.match(r"^(#+)\s+(.*)", l)
        if level is None:
            if m and name.lower() in m.group(2).lower():
                level = len(m.group(1))
        elif m and len(m.group(1)) <= level:
            break
        elif level is not None:
            out.append(l)
    return "\n".join(out)


ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


def cited_ids(recipe):
    """Verifier ids a recipe cites: backticked single tokens in its Checks section (commands contain spaces or
    punctuation and are ignored)."""
    return [x for x in re.findall(r"`([^`\n]+)`", _section(recipe["body"], "Checks")) if ID_RE.fullmatch(x)]


def untiered_long_checks():
    """Entries whose 'As a contract check' example has timeout_s over 60 but no "tier": "deep"."""
    bad = []
    for e in load_verifiers():
        sec = _section(e["body"], "As a contract check")
        ts = [float(x) for x in re.findall(r'"timeout_s"\s*:\s*(\d+(?:\.\d+)?)', sec)]
        if ts and max(ts) > 60 and not re.search(r'"tier"\s*:\s*"deep"', sec):
            bad.append(e)
    return bad


def lint_warnings():
    out = []
    for e in untiered_long_checks():
        out.append('%s: contract-check example has timeout_s over 60 but no "tier": "deep"' % e["path"])
    for e in load_verifiers() + load_recipes():
        try:
            with open(e["path"], encoding="utf-8") as f:
                n = len(f.read().rstrip("\n").split("\n"))
        except OSError:
            continue
        if n > 80 or n < 30:
            out.append("%s: %d lines (aim for 30-80)" % (e["path"], n))
        if e["header"].get("verified") == "memory":
            out.append("%s: verified: memory (written from memory, not checked against the tool or its docs)" % e["path"])
    return out


def lint():
    """Return a list of 'path: problem' strings."""
    out = []
    vs, rs = load_verifiers(), load_recipes()
    from . import overlay
    known = {e["header"].get("id") or e["stem"] for e in vs} | set(overlay.disabled("verifier"))  # switched off is not unknown
    for r in rs:
        for i in dict.fromkeys(cited_ids(r)):
            if i not in known:
                out.append("%s: Checks cites unknown verifier id %r" % (r["path"], i))
    for e in vs + rs:
        for p in e["problems"]:
            out.append("%s: %s" % (e["path"], p))
    for kind, entries, keys, heads in (("verifier", vs, V_KEYS, V_HEADINGS), ("recipe", rs, D_KEYS, D_HEADINGS)):
        seen = {}
        for e in entries:
            if not e["header"]:
                continue
            h, p = e["header"], e["path"]
            for k in keys:
                if k not in h or (not h[k] and k not in ("detect",)):
                    out.append("%s: missing or empty %r" % (p, k))
            if h.get("id") and h["id"] != e["stem"]:
                out.append("%s: id %r must equal the file name %r" % (p, h["id"], e["stem"]))
            if h.get("id"):
                if h["id"] in seen:
                    out.append("%s: duplicate id %r (also %s)" % (p, h["id"], seen[h["id"]]))
                seen[h["id"]] = p
            for m in _missing_headings(e["body"], heads):
                out.append("%s: body lacks the heading %r" % (p, m))
            if kind == "verifier":
                if not re.fullmatch(r"[1-6]", h.get("rung", "")):
                    out.append("%s: rung must be an integer 1-6" % p)
                if h.get("section") and h["section"] not in SECTIONS:
                    out.append("%s: unknown section %r" % (p, h["section"]))
                if e["parent"] and h.get("section") and e["parent"] != h["section"]:
                    out.append("%s: section %r does not match its directory %r" % (p, h["section"], e["parent"]))
                if h.get("cost") and h["cost"] not in COSTS:
                    out.append("%s: cost must be one of %s" % (p, ", ".join(COSTS)))
                if h.get("ran_here") and h["ran_here"] not in ("yes", "no"):
                    out.append("%s: ran_here must be yes or no" % p)
                for k in _list(h.get("kinds")):
                    if k != "any" and k not in C.KINDS:
                        out.append("%s: unknown kind %r (one of %s, or any)" % (p, k, ", ".join(C.KINDS)))
    return out


def cmd_lint(args):
    probs = lint()
    warns = lint_warnings()
    for w in warns:
        print("warning: " + w)
    if probs:
        for p in probs:
            print(p)
        print("\n%d problem(s)" % len(probs))
        return 1
    print("lint ok: %d verifiers, %d recipes%s" % (len(load_verifiers()), len(load_recipes()),
                                                   ", %d warning(s)" % len(warns) if warns else ""))
    return 0


def main(args):
    try:
        if args and args[0] == "show":
            return cmd_show(args[1:])
        if args and args[0] == "for":
            return cmd_for(args[1:])
        if args and args[0] == "doctor":
            return cmd_doctor(args[1:])
        if args and args[0] == "lint":
            return cmd_lint(args[1:])
        return cmd_list(args)
    except ValueError as e:
        print("sisi: %s" % e)
        return 1


# ---- done recipes ----------------------------------------------------------
def done_main(args):
    rs = usable(load_recipes())
    if args and args[0] == "for":
        desc = " ".join(args[1:]).strip()
        if not desc:
            print('usage: sisi done for "<description of the work>"')
            return 1
        toks = set(_words(desc))
        scored = []
        for r in rs:
            s = 0.0
            for text, w in ((r["title"], 3.0), (r["applies_to"], 3.0), (r["id"].replace("-", " "), 3.0), (r["body"], 0.2)):
                ws = set(_words(text.replace("-", " ")))
                s += w * sum(1 for t in toks if t in ws or any(len(t) > 3 and len(x) > 3 and (x.startswith(t) or t.startswith(x)) for x in ws))
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        if not scored:
            print("no recipe matches that description; `sisi done` lists them")
            _print_drafts(desc)
            _print_lessons(desc, "done-for", loose=True)
            _print_cycle_notice()
            return 0
        best = scored[0][1]
        print("Best match: %s\n" % best["id"])
        print("== %s: %s ==%s\napplies to: %s\n" % (best["id"], best["title"], origin_tag(best), best["applies_to"]))
        print(best["body"].strip("\n"))
        _print_notes(best["id"])
        if len(scored) > 1:
            print("\nOther candidates: " + ", ".join(r["id"] for _, r in scored[1:4]))
        _print_drafts(desc)
        _print_lessons(desc, "done-for", extra=best["id"] + " " + best["title"], loose=True,
                       targets=(best["id"],))
        _print_cycle_notice()
        return 0
    if args:
        r = next((x for x in rs if x["id"] == args[0]), None)
        if not r:
            print("no recipe with id %r (see `sisi done`)" % args[0])
            return 1
        print("== %s: %s ==%s\napplies to: %s\n" % (r["id"], r["title"], origin_tag(r), r["applies_to"]))
        print(r["body"].strip("\n"))
        _print_notes(r["id"])
        _print_lessons("%s %s %s" % (r["id"].replace("-", " "), r["title"], r["applies_to"]),
                       "done-show", loose=True, targets=(r["id"],))
        return 0
    if not rs:
        print("no recipes")
        return 0
    for r in sorted(rs, key=lambda r: r["id"]):
        print("%-24s %s  (%s)%s" % (r["id"], r["title"], r["applies_to"], origin_tag(r)))
    print("\nsisi done ID | for \"<description>\"")
    return 0
