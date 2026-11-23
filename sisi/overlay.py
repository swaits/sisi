"""The overlay: how what sisi learned changes the base rulebook, verifiers and recipes without editing the product.

Files, all under <personal>/overlay/:
  rules/<id>.md          a rule: `## Title` then the body. Same id as a base rule = replaces it; new id = adds one.
  rules/disabled.txt     ids of rules switched off (one per line)
  rules/order.txt        order of added rules (ids, one per line); base rules keep the base order
  rules/full-order.txt   whole-book reading order from a whole-document round (ids; numbers follow it)
  traces/                where each folded lesson lives in a rewritten document (never agent-loaded)
  verifiers/<section>/<id>.md   a verifier in the library's own format (replaces the product's of that id, or adds)
  verifiers/disabled.txt        ids of verifiers switched off
  done/<id>.md           a recipe in the library's own format (replace or add)
  done/disabled.txt             ids of recipes switched off
  bases.json             for each replacement: the hash of the base item it was made against

The effective rulebook (base + overlay) is generated to <personal>/generated/core.md.
Every command that changes the overlay is one commit in the personal git repository and is refused when the
generated rulebook would exceed MAX_LINES.
"""
import contextlib, hashlib, json, os, re, sys, tempfile, time

from . import paths

# Budgets for what every session always loads, including the generated `More: sisi rule N` line
# under each rule. 200 lines is the largest size vendor guidance supports (Anthropic: "target under
# 200 lines per CLAUDE.md file"); published measurements say adherence falls as the number of
# simultaneous instructions grows, so the book stays small and exactness comes from enforced checks
# and request-time delivery. Characters are budgeted too, in the same proportion, because wrapping
# games must not load more text. A learning round still may not grow the book without shortening.
MAX_LINES = 200
MAX_CHARS = 12000
KINDS = ("rule", "verifier", "recipe")
ID_TAIL = re.compile(r"\s*\{#([A-Za-z0-9][A-Za-z0-9_-]*)\}\s*$")
NUM = re.compile(r"^\d+\.\s+")
ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class OverlayError(Exception):
    pass


def sha(b):
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40] or "rule"


# ---- rules: parse and render -------------------------------------------------
def parse_rules(text):
    """(preamble, [rule]) where rule = {id, title, body, hash}. A rule starts at a `## ` heading,
    `## 3. Title {#id}`; without {#id} the id is a slug of the title."""
    pre, rules, cur = [], [], None
    for line in text.split("\n"):
        if line.startswith("## "):
            if cur:
                rules.append(cur)
            t = NUM.sub("", line[3:].strip())
            m = ID_TAIL.search(t)
            rid = m.group(1) if m else None
            if m:
                t = t[:m.start()]
            cur = {"id": rid or slug(t), "title": t.strip(), "lines": []}
        elif cur is not None:
            cur["lines"].append(line)
        else:
            pre.append(line)
    if cur:
        rules.append(cur)
    for r in rules:
        r["body"] = "\n".join(r.pop("lines")).strip("\n")
        r["hash"] = sha(r["title"] + "\n" + r["body"])
    return "\n".join(pre).strip("\n"), rules


def parse_rule_file(text, rid=None):
    pre, rules = parse_rules(text)
    if pre.strip():
        raise OverlayError("a rule file must start with a `## Title` heading (found text before it)")
    if len(rules) != 1:
        raise OverlayError("a rule file holds exactly one rule (one `## Title` heading), found %d" % len(rules))
    r = rules[0]
    if rid:
        if not ID_OK.match(rid):
            raise OverlayError("bad rule id %r (letters, digits, - and _)" % rid)
        if "{#" in text.split("\n", 1)[0] and r["id"] != rid:
            raise OverlayError("the heading says {#%s} but the id is %s" % (r["id"], rid))
        r["id"] = rid
    if not r["body"].strip():
        raise OverlayError("the rule has no body")
    return r


def rule_text(r):
    return "## %s\n\n%s\n" % (r["title"], r["body"])


def add_to_body(body, add):
    """The rule's body with the sentence(s) `add` placed before its `Why:` paragraph: on the end
    of the paragraph just before it (no new line), or as a paragraph of their own when that one is a
    list. A rule without a Why paragraph gets them at the end."""
    paras = body.split("\n\n")
    at = next((i for i in range(len(paras) - 1, -1, -1) if paras[i].lstrip().startswith("Why:")), None)
    if at is None:
        at = len(paras)
    if at == 0:
        paras.insert(0, add)
        return "\n\n".join(paras)
    prev = paras[at - 1]
    if any(re.match(r"\s*(?:[-*]|\d+[.)])\s", l) for l in prev.splitlines()):
        paras.insert(at, add)
    else:
        paras[at - 1] = prev.rstrip() + " " + add
    return "\n\n".join(paras)


def rule_with_added(rid, add, base=None):
    """The parsed rule `rid` (from `base`, else the rule in force) with `add` before its Why."""
    cur = base or next((r for r in effective()[1] if r["id"] == rid), None)
    if cur is None:
        raise OverlayError("no rule %r (the brief lists the ids)" % rid)
    return dict(cur, body=add_to_body(cur["body"], add))


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def base_rules():
    try:
        return parse_rules(_read(paths.canon("core.md")))
    except OSError as e:
        raise OverlayError("cannot read the base rulebook %s: %s" % (paths.canon("core.md"), e))


def _lines(p):
    try:
        return [l.strip() for l in _read(p).splitlines() if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def disabled(kind):
    return _lines(paths.overlay_dir({"rule": "rules", "verifier": "verifiers", "recipe": "done"}[kind], "disabled.txt"))


def retired_ids():
    """{old rule id: the rule that now carries its subject, or None} from canon/rule-ids.json.
    An unreadable file reads as empty here; the protection check uses retired_strict()."""
    try:
        return retired_strict()
    except OverlayError:
        return {}


def retired_strict():
    try:
        with open(paths.canon("rule-ids.json"), encoding="utf-8") as f:
            d = json.load(f)["retired"]
        if not isinstance(d, dict) or not all(isinstance(k, str) and (v is None or isinstance(v, str)) for k, v in d.items()):
            raise ValueError("retired must map ids to an id or null")
        return d
    except FileNotFoundError:
        return {}  # a product without the map has retired nothing
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise OverlayError("canon/rule-ids.json cannot be read (%s)" % e)


def _is_retired(rid):
    """A retired id that no base rule uses: an overlay entry under it is stale, never applied."""
    return rid in retired_ids() and rid not in {r["id"] for r in base_rules()[1]}


def overlay_rules(include_stale=False):
    d = paths.overlay_dir("rules")
    out = {}
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if n.endswith(".md"):
            stem = n[:-3]
            try:
                r = parse_rule_file(_read(os.path.join(d, n)), stem)
            except (OverlayError, OSError):
                continue  # a broken file is ignored here; `overlay list` reports it
            out[stem] = r
    if not include_stale:
        out = {k: v for k, v in out.items() if not _is_retired(k)}
    return out


def stale_entries():
    """Overlay rule entries keyed by a retired id: [(id, 'replacement'|'disabling', new id or None)].
    They stay in the store and are not applied."""
    out = []
    ret = retired_ids()
    for rid in sorted(overlay_rules(include_stale=True)):
        if _is_retired(rid):
            out.append((rid, "replacement", ret[rid]))
    for rid in disabled("rule"):
        if _is_retired(rid):
            out.append((rid, "disabling", ret[rid]))
    return out


def bases():
    try:
        with open(paths.overlay_dir("bases.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def effective():
    """(preamble, rules) with the overlay applied. Each rule gets 'origin': base | replaced | added."""
    pre, base = base_rules()
    over, off = overlay_rules(), set(disabled("rule"))
    out, base_ids = [], {r["id"] for r in base}
    for r in base:
        if r["id"] in off:
            continue
        if r["id"] in over:
            out.append(dict(over[r["id"]], origin="replaced"))
        else:
            out.append(dict(r, origin="base"))
    order = [i for i in _lines(paths.overlay_dir("rules", "order.txt")) if i in over and i not in base_ids]
    rest = sorted(i for i in over if i not in base_ids and i not in order)
    for i in dict.fromkeys(order + rest):
        if i not in off:
            out.append(dict(over[i], origin="added"))
    # A whole-document round may reorder the whole book: rules/full-order.txt then names every
    # rule in reading order. Ids stay stable; numbers follow this order, and anything stored
    # refers to rules by id (`rule:<id>`), never by number.
    full = _lines(paths.overlay_dir("rules", "full-order.txt"))
    if full:
        rank = {i: n for n, i in enumerate(full)}
        out.sort(key=lambda r: rank.get(r["id"], len(rank)))
    return pre, out


def overlay_hash():
    h, any_ = hashlib.sha256(), False
    for dp, dns, fns in os.walk(paths.overlay_dir("rules")):
        dns.sort()
        for n in sorted(fns):
            any_ = True
            h.update(n.encode() + b"\0")
            with open(os.path.join(dp, n), "rb") as f:
                h.update(f.read() + b"\0")
    return h.hexdigest()[:8] if any_ else "none"


def more_line(n):
    """The generated pointer under each rule: the command that prints the rule in full."""
    return "More: `sisi rule %d` (reasons, history, lessons behind it, how it is enforced)." % n


def _render(pre, rules):
    try:
        with open(paths.canon("core.md"), "rb") as f:
            base_h = sha(f.read())[:8]
    except OSError:
        base_h = "missing"
    head = "<!-- generated by sisi from the product canon/core.md (%s) and the personal overlay (%s); " \
           "do not edit -->" % (base_h, overlay_hash())
    parts = [head]
    if pre.strip():
        parts.append(pre)
    for n, r in enumerate(rules, 1):
        # the pointer rides on the body's last line: it costs no line of the always-loaded budget
        parts.append("## %d. %s {#%s}\n\n%s\n%s" % (n, r["title"], r["id"], r["body"], more_line(n)))
    return "\n\n".join(parts) + "\n"


def render():
    pre, rules = effective()
    return _render(pre, rules)


def render_with(changes):
    """The rulebook as it would render with these rules (id -> parsed rule) added or replaced:
    the size check a cycle runs before it writes anything."""
    pre, rules = effective()
    rules = list(rules)
    at = {r["id"]: i for i, r in enumerate(rules)}
    for rid, r in changes.items():
        r = dict(r, origin="added")
        if rid in at:
            rules[at[rid]] = r
        else:
            at[rid] = len(rules)
            rules.append(r)
    return _render(pre, rules)


def protected_rules():
    """Ids no cycle and no overlay command may replace or disable (canon/protected.json). Fails
    closed: when the file cannot be read, nothing about a rule may be changed."""
    try:
        with open(paths.canon("protected.json"), encoding="utf-8") as f:
            d = json.load(f)
        rules = d["rules"]
        if not isinstance(rules, list) or not all(isinstance(x, str) for x in rules):
            raise ValueError("rules must be a list of ids")
        prot = set(rules)
        # a retired id whose subject is now a protected rule stays untouchable: the map is no way round
        return prot | {old for old, new in retired_strict().items() if new in prot}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise OverlayError("canon/protected.json cannot be read (%s): changes to rules are refused until it can" % e)


def size(text):
    return len(text.splitlines()), len(text)


def build_canon(strict=False):
    """Write the generated rulebook. Idempotent: identical content only refreshes the timestamp.
    strict: refuse (raise) when over the size budget, before writing anything."""
    from . import pdata
    text = render()
    lines, chars = size(text)
    over = lines > MAX_LINES or chars > MAX_CHARS
    if over and strict:
        raise OverlayError("the rulebook would be %d lines and %d characters; the budgets are %d lines and %d "
                           "characters. Shorten or replace another rule first (`sisi doctor` shows the size)"
                           % (lines, chars, MAX_LINES, MAX_CHARS))
    pdata.ensure()
    p = paths.generated()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        same = _read(p) == text
    except OSError:
        same = False
    if same:
        os.utime(p, None)
    else:
        tmp = p + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    return {"path": p, "lines": lines, "chars": chars, "over_budget": over, "changed": not same}


def is_stale():
    """Is the generated rulebook older than the base rulebook or the overlay's rules? A few stat calls."""
    try:
        g = os.stat(paths.generated()).st_mtime_ns
    except OSError:
        return True
    for p in (paths.canon("core.md"), paths.overlay_dir("rules")):
        try:
            if os.stat(p).st_mtime_ns > g:
                return True
        except OSError:
            pass
    return False


def cost():
    """Always-loaded size: the generated rulebook. No lesson list is loaded at session start."""
    try:
        lines, chars = size(_read(paths.generated()))
    except OSError:
        lines = chars = None
    return {"rulebook_lines": lines, "rulebook_chars": chars, "rulebook_budget_lines": MAX_LINES,
            "rulebook_budget_chars": MAX_CHARS}


def cost_line(c=None):
    c = c or cost()
    if c["rulebook_lines"] is None:
        return "rulebook not generated yet (run `sisi update`)"
    return "rulebook %d lines (budget %d), %d characters (budget %d)" % (
        c["rulebook_lines"], c["rulebook_budget_lines"], c["rulebook_chars"],
        c.get("rulebook_budget_chars", MAX_CHARS))


# ---- library overlay (verifiers, recipes) ---------------------------------------
def lib_dir(kind):
    return paths.overlay_dir("verifiers" if kind == "verifier" else "done")


def _base_entries(kind):
    from . import verifiers as V
    return V.load_verifiers(paths.verifiers_dir()) if kind == "verifier" else V.load_recipes(paths.done_dir())


def base_hash(kind, id):
    if kind == "rule":
        for r in base_rules()[1]:
            if r["id"] == id:
                return r["hash"]
        return None
    for e in _base_entries(kind):
        if e["id"] == id:
            try:
                with open(e["path"], "rb") as f:
                    return sha(f.read())
            except OSError:
                return None
    return None


def _overlay_entry_paths(kind, id):
    from . import verifiers as V
    return [p for p in V._walk(lib_dir(kind)) if os.path.splitext(os.path.basename(p))[0] == id]


# ---- transactions ----------------------------------------------------------
def _snapshot(d):
    snap = {}
    for dp, dns, fns in os.walk(d):
        for n in fns:
            p = os.path.join(dp, n)
            with open(p, "rb") as f:
                snap[os.path.relpath(p, d)] = f.read()
    return snap


def _restore(d, snap):
    for dp, dns, fns in os.walk(d, topdown=False):
        for n in fns:
            os.unlink(os.path.join(dp, n))
        for n in dns:
            try:
                os.rmdir(os.path.join(dp, n))
            except OSError:
                pass
    for rel, b in snap.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b)


@contextlib.contextmanager
def _txn(msg):
    """Apply an overlay change: roll the overlay back if it fails the size budget, a lint, or the commit."""
    from . import pdata
    pdata.ensure()
    d = paths.overlay_dir()
    with pdata.lock():
        snap = _snapshot(d)
        try:
            yield
            build_canon(strict=True)
            if pdata._commit(msg, ["overlay"]) is None:
                raise OverlayError("nothing changed")
        except BaseException:
            _restore(d, snap)
            try:
                build_canon()
            except Exception:
                pass
            raise


def _write(rel, text):
    p = paths.overlay_dir(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def _remove(p):
    try:
        os.unlink(p)
    except OSError:
        pass


def _set_lines(rel, ids):
    p = paths.overlay_dir(rel)
    if ids:
        _write(rel, "\n".join(ids) + "\n")
    else:
        _remove(p)


def _set_base(kind, id, h):
    b = bases()
    key = "%s:%s" % (kind, id)
    if h is None:
        b.pop(key, None)
    else:
        b[key] = h
    if b:
        _write("bases.json", json.dumps(b, indent=1, sort_keys=True) + "\n")
    else:
        _remove(paths.overlay_dir("bases.json"))


def _read_source(arg):
    if arg in (None, "-"):
        return sys.stdin.read()
    try:
        return _read(arg)
    except OSError as e:
        raise OverlayError("cannot read %s: %s" % (arg, e))


# ---- rule commands ----------------------------------------------------------
def add_rule(text, rid=None):
    r = parse_rule_file(text, rid)
    if r["id"] in {x["id"] for x in base_rules()[1]}:
        raise OverlayError("%r is a base rule id; use replace-rule to change it" % r["id"])
    if r["id"] in retired_ids():
        raise OverlayError("%r is a retired rule id (now %s); choose another id" % (r["id"], retired_ids()[r["id"]] or "split across several rules"))
    if r["id"] in overlay_rules():
        raise OverlayError("an added rule %r already exists; use replace-rule to change it" % r["id"])
    with _txn("overlay: add rule %s" % r["id"]):
        _write("rules/%s.md" % r["id"], rule_text(r))
        _set_lines("rules/order.txt", _lines(paths.overlay_dir("rules", "order.txt")) + [r["id"]])
    return r["id"]


def replace_rule(rid, text):
    known = {x["id"] for x in base_rules()[1]} | set(overlay_rules())
    if rid not in known:
        raise OverlayError("no rule %r (see `sisi overlay list`, or `sisi canon` for the ids)" % rid)
    r = parse_rule_file(text, rid)
    with _txn("overlay: replace rule %s" % rid):
        _write("rules/%s.md" % rid, rule_text(r))
        _set_base("rule", rid, base_hash("rule", rid))
    return rid


def set_disabled(kind, id, off):
    if kind == "rule":
        known = {x["id"] for x in base_rules()[1]} | set(overlay_rules())
    else:
        from . import verifiers as V
        known = {e["id"] for e in (V.load_verifiers() if kind == "verifier" else V.load_recipes())} | set(disabled(kind))
    cur = disabled(kind)
    if off:
        if id not in known:
            raise OverlayError("no %s %r" % (kind, id))
        if id in cur:
            raise OverlayError("%s %r is already disabled" % (kind, id))
        new = cur + [id]
    else:
        if id not in cur:
            raise OverlayError("%s %r is not disabled" % (kind, id))
        new = [x for x in cur if x != id]
    rel = {"rule": "rules", "verifier": "verifiers", "recipe": "done"}[kind] + "/disabled.txt"
    with _txn("overlay: %s %s %s" % ("disable" if off else "enable", kind, id)):
        _set_lines(rel, new)
    return id


# ---- verifier and recipe commands -----------------------------------------------
def _put_entry(kind, text, expect_id, replacing):
    from . import verifiers as V
    tmp = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    try:
        tmp.write(text)
        tmp.close()
        e = V.parse(tmp.name)
    finally:
        _remove(tmp.name)
    h = e["header"]
    if not h:
        raise OverlayError("the file has no header block (it must start with a --- line; see docs/verifier-format.md)")
    id = h.get("id")
    if not id or not ID_OK.match(id):
        raise OverlayError("the header needs an id: line (letters, digits, - and _)")
    if expect_id and id != expect_id:
        raise OverlayError("the header id is %r but you asked for %r" % (id, expect_id))
    in_base = any(x["id"] == id for x in _base_entries(kind))
    mine = _overlay_entry_paths(kind, id)
    if replacing and not (in_base or mine):
        raise OverlayError("no %s %r to replace (see `sisi overlay list`); use add-%s" % (kind, id, kind))
    if not replacing and (in_base or mine):
        raise OverlayError("%s %r already exists; use replace-%s to change it" % (kind, id, kind))
    if kind == "verifier":
        sec = h.get("section")
        if not sec:
            raise OverlayError("the header needs a section: line")
        rel = "verifiers/%s/%s.md" % (sec, id)
    else:
        rel = "done/%s.md" % id
    return id, rel, mine


def _lint_new(rel):
    from . import verifiers as V
    p = paths.overlay_dir(rel)
    bad = [x for x in V.lint() if x.startswith(p + ":")]
    if bad:
        raise OverlayError("the file does not pass `sisi verifiers lint`:\n  " + "\n  ".join(b[len(p) + 2:] for b in bad))


def put_entry(kind, text, id=None, replacing=False):
    id, rel, mine = _put_entry(kind, text, id, replacing)
    with _txn("overlay: %s %s %s" % ("replace" if replacing else "add", kind, id)):
        for p in mine:
            _remove(p)
        _write(rel, text if text.endswith("\n") else text + "\n")
        if replacing:
            _set_base(kind, id, base_hash(kind, id))
        _lint_new(rel)
    return id


# ---- listing and diff -----------------------------------------------------------
def _origin_sets():
    """{kind: {'added': [...], 'replaced': [...], 'disabled': [...]}} for the whole overlay."""
    out = {}
    base_rule_ids = {r["id"] for r in base_rules()[1]}
    ov = overlay_rules()
    out["rule"] = {"replaced": sorted(i for i in ov if i in base_rule_ids), "added": sorted(i for i in ov if i not in base_rule_ids),
                   "disabled": sorted(disabled("rule"))}
    for kind in ("verifier", "recipe"):
        from . import verifiers as V
        base_ids = {e["id"] for e in _base_entries(kind)}
        mine = {os.path.splitext(os.path.basename(p))[0] for p in V._walk(lib_dir(kind))}
        out[kind] = {"replaced": sorted(mine & base_ids), "added": sorted(mine - base_ids), "disabled": sorted(disabled(kind))}
    return out


def retest_queue():
    items = []
    try:
        with open(paths.data_file("retest.jsonl"), encoding="utf-8") as f:
            for l in f:
                try:
                    items.append(json.loads(l))
                except ValueError:
                    pass
    except OSError:
        pass
    return items


def cmd_list():
    o = _origin_sets()
    n = 0
    for kind in KINDS:
        for how in ("added", "replaced", "disabled"):
            for i in o[kind][how]:
                print("%-8s %-9s %s" % (kind, how, i))
                n += 1
    for rid, how, repl in stale_entries():
        print("%-8s %-9s %s (retired id, %s; not applied, kept in your store)" % ("rule", "stale", rid, "now " + repl if repl else "split across several rules"))
        n += 1
    if not n:
        print("the overlay is empty: base rules, verifiers and recipes are used as they are")
    q = retest_queue()
    if q:
        print("\n%d replaced item(s) whose base changed in an update are queued for re-testing (retest.jsonl)" % len(q))
    return 0


def _udiff(a, b, na, nb):
    import difflib
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), na, nb))


def cmd_diff():
    o = _origin_sets()
    base_rules_ = {r["id"]: r for r in base_rules()[1]}
    ov = overlay_rules()
    any_ = False
    for i in o["rule"]["added"]:
        any_ = True
        print("+ rule %s (added)\n%s" % (i, rule_text(ov[i])))
    for i in o["rule"]["replaced"]:
        any_ = True
        print("~ rule %s (replaced)\n%s" % (i, _udiff(rule_text(base_rules_[i]), rule_text(ov[i]), "product", "personal")))
    for i in o["rule"]["disabled"]:
        any_ = True
        print("- rule %s (disabled)" % i)
    for kind in ("verifier", "recipe"):
        base = {e["id"]: e for e in _base_entries(kind)}
        from . import verifiers as V
        for p in V._walk(lib_dir(kind)):
            i = os.path.splitext(os.path.basename(p))[0]
            any_ = True
            if i in base:
                print("~ %s %s (replaced)\n%s" % (kind, i, _udiff(_read(base[i]["path"]), _read(p), "product", "personal")))
            else:
                print("+ %s %s (added)" % (kind, i))
        for i in o[kind]["disabled"]:
            any_ = True
            print("- %s %s (disabled)" % (kind, i))
    if not any_:
        print("no differences from the product")
    return 0


# ---- revert ------------------------------------------------------------------
def revert(commit):
    from . import pdata
    pdata.ensure()
    with pdata.lock():
        r = pdata.git("rev-parse", "--verify", "-q", commit + "^{commit}", check=False)
        if r.returncode != 0:
            raise OverlayError("no such commit %r in the personal repository (see `git -C %s log`)" % (commit, paths.data()))
        full = r.stdout.strip()
        files = [x for x in pdata.git("show", "--name-only", "--format=", full).stdout.split("\n") if x]
        if not files or any(not f.startswith("overlay/") for f in files):
            raise OverlayError("%s is not an overlay change (it touches %s); only overlay commits can be reverted here"
                               % (commit, ", ".join(f for f in files if not f.startswith("overlay/")) or "nothing"))
        r = pdata.git("revert", "--no-edit", full, check=False)
        if r.returncode != 0:
            pdata.git("revert", "--abort", check=False)
            raise OverlayError("cannot revert %s cleanly (%s); nothing was changed" % (commit, (r.stderr or r.stdout).strip().splitlines()[-1:]))
    return build_canon()


# ---- update support -------------------------------------------------------------
def scan_retests():
    """After the product changed: for every replacement whose base item changed, keep the person's version and
    queue it for re-testing. Returns the new queue records."""
    from . import pdata
    b = bases()
    new, changed = [], False
    for key in sorted(b):
        kind, _, id = key.partition(":")
        if kind not in KINDS:
            continue
        if kind == "rule" and _is_retired(id):
            continue  # reported below as stale, not as a kept personal version
        old, cur = b[key], base_hash(kind, id)
        if old == cur:
            continue
        if old is None and cur is None:
            continue
        new.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": kind, "id": id,
                    "old_base_hash": old, "new_base_hash": cur, "action": "kept the personal version"})
        b[key] = cur
        changed = True
    seen = {(r.get("kind"), r.get("id")) for r in retest_queue() if str(r.get("action", "")).startswith("stale")}
    for rid, how, repl in stale_entries():
        if ("rule", rid) in seen:
            continue  # reported once
        # not the 'kept your version' route: this text was written against a rule that no longer exists
        new.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": "rule", "id": rid,
                    "old_base_hash": b.get("rule:" + rid), "new_base_hash": None,
                    "action": "stale: your %s of the retired rule %s was written against the old wording; "
                              "not applied to %s, kept in your store" % (how, rid, repl or "the rules that replaced it")})
        changed = True
    if changed:
        with pdata.lock():
            p = paths.data_file("retest.jsonl")
            with open(p, "a", encoding="utf-8") as f:
                for r in new:
                    f.write(json.dumps(r, sort_keys=True) + "\n")
            _write("bases.json", json.dumps(b, indent=1, sort_keys=True) + "\n")
        pdata.commit("update: %d overlay item(s) queued (base changed, personal versions kept; or stale under a retired rule id)" % len(new),
                     ["overlay", "retest.jsonl"])
    return new


# ---- command line ----------------------------------------------------------------
def _rule_change_waits(action):
    """Replacing or disabling a rule from the command line obeys the same rules as a cycle: a
    protected rule is refused, anything else waits for the owner's `sisi approve`."""
    from . import cycle, documents
    rid = action["rule_id"]
    if rid in protected_rules():
        raise OverlayError("rule %r is protected (canon/protected.json); it cannot be replaced or disabled "
                           "from here or by a cycle" % rid)
    if rid not in {x["id"] for x in base_rules()[1]} | set(overlay_rules()):
        raise OverlayError("no rule %r (see `sisi overlay list`, or `sisi canon` for the ids)" % rid)
    if action["action"] == "replace-rule":
        ok, msg = documents.check_budgets(render_with({rid: parse_rule_file(action["rule_text"], rid)}))
        if not ok:
            raise OverlayError(msg)
    pid = cycle.park_rule_change(action, ["%s %s: changing or disabling an existing rule needs the owner" % (action["action"], rid)])
    print("%s %s waits for the owner: nothing changed. The owner decides in a terminal: `sisi approve %s --yes`"
          % (action["action"], rid, pid))
    return 0



USAGE = """usage: sisi overlay list | diff
       sisi overlay add-rule [--id ID] FILE|-      replace-rule ID FILE|-      disable-rule ID      enable-rule ID
       (replace-rule and disable-rule wait for the owner's `sisi approve`; protected rules are refused)
       sisi overlay add-verifier FILE|-           replace-verifier ID FILE|-  disable-verifier ID  enable-verifier ID
       sisi overlay add-recipe FILE|-             replace-recipe ID FILE|-    disable-recipe ID    enable-recipe ID
       sisi overlay revert COMMIT
Each change is one commit in the personal data repository; rules are refused if the rulebook would pass %d lines.""" % MAX_LINES


def main(args):
    args = list(args)
    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if args else 1
    sub = args.pop(0)
    try:
        if sub == "list":
            return cmd_list()
        if sub == "diff":
            return cmd_diff()
        if sub == "revert":
            if len(args) != 1:
                print(USAGE)
                return 1
            r = revert(args[0])
            print("reverted %s; rulebook rebuilt (%d lines)" % (args[0], r["lines"]) + (" - OVER THE %d-LINE BUDGET" % MAX_LINES if r["over_budget"] else ""))
            return 0
        m = re.match(r"^(add|replace|disable|enable)-(rule|verifier|recipe)$", sub)
        if not m:
            print("sisi overlay: unknown subcommand %r\n%s" % (sub, USAGE))
            return 1
        op, kind = m.groups()
        if op in ("disable", "enable"):
            if len(args) != 1:
                print(USAGE)
                return 1
            if kind == "rule" and op == "disable":
                return _rule_change_waits({"action": "disable-rule", "rule_id": args[0]})
            set_disabled(kind, args[0], op == "disable")
            print("%sd %s %s" % (op, kind, args[0]))
            return 0
        rid = None
        if op == "add" and kind == "rule" and "--id" in args:
            i = args.index("--id")
            rid = args[i + 1] if i + 1 < len(args) else None
            del args[i:i + 2]
        if op == "replace":
            if len(args) != 2:
                print(USAGE)
                return 1
            rid = args.pop(0)
        if len(args) != 1:
            print(USAGE)
            return 1
        text = _read_source(args[0])
        if kind == "rule" and op == "replace":
            return _rule_change_waits({"action": "replace-rule", "rule_id": rid, "rule_text": text})
        if kind == "rule":
            done = add_rule(text, rid)
        else:
            done = put_entry(kind, text, rid, replacing=(op == "replace"))
        print("%s %s %s (committed to the personal repository)" % ("added" if op == "add" else "replaced", kind, done))
        return 0
    except OverlayError as e:
        print("sisi overlay: %s" % e, file=sys.stderr)
        return 1
    except Exception as e:
        from . import pdata
        if isinstance(e, pdata.DataError):
            print("sisi overlay: %s" % e, file=sys.stderr)
            return 1
        raise
