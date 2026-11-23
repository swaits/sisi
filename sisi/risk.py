"""Risk profiles: ceremony follows risk, not diff size (SPEC 5.3, target section 3).

`assess` is a pure function from changed paths (and optionally diff text) to a floor
profile plus the reasons. Tables come from canon/risk.json, a user-store adjustment
file, and a project override at .sisi/risk.json; later tables only add patterns.

How ONE path is classified (`classify_path`), in this order:
  0. Code stage (R-5.3-2, R-5.3-4): a file with a source-code extension (the "code" pattern)
     is never `trivial`. Kind patterns marked "unless_code" (documentation, assets, styling,
     content, text) do not apply to code files, so `docs/conf.py` and `AuthorList.tsx` fall
     through to the name stage and are at least isolated.
  1. Kind stage (patterns with "stage": "kind"; the first match wins and is final).
     What the file IS comes before what it is called: documentation, assets, styling,
     fixtures, tests, generated output, lockfiles and manifests, vendored code. So
     `docs/installation.md` is documentation and `Cargo.lock` is a lockfile whatever
     their names contain. Documentation, assets and styling are trivial; fixtures,
     generated output and ordinary tests are isolated; lockfiles, manifests and vendored
     code are integration (behaviour of code you did not write changes: not trivial, but
     not critical either). A test of data, critical or release code is `logic`: it is not
     itself critical, but it is not trivial. A test of anything else stays isolated.
  2. Name stage (patterns with "stage": "name"): globs on the path, and tokens on the
     directory names and file stem split on punctuation and camelCase (`AuthorCard` is
     "author", "card", never "auth"). Tokens match whole words; a trailing `*` is a prefix
     and is used only where no unrelated word starts that way (never for `pars`: parsley).
     A pattern may carry an "except" (glob/token) that cancels it, e.g. a front-end
     "view model" or a machine-learning "model" is not an ORM model. A pattern may also carry
     a "requires" (a second cue that must be in the same path: `key` AND `rotate`) and
     "min_stem_tokens" (compound file names only). The highest matching
     profile wins. A source file that matches nothing is isolated.
  3. Override patterns (no "stage": project and user-store adjustments) only raise.
How a CHANGE is classified (`assess`): the highest floor among its paths; a change that
touches two or more top-level packages (tests, docs, fixtures, generated output and root
files do not count as packages) is at least integration; diff keywords raise the floor but
only from the diff of files that are not docs, tests, fixtures, lockfiles or manifests.
Every rule is a maximum over a growing set, so adding a path never lowers the floor.
"""
import fnmatch, json, os, re, subprocess

PROFILES = ["trivial", "isolated", "logic", "integration", "data", "critical", "release"]
_ORDER = {name: i for i, name in enumerate(PROFILES)}
_TRIVIAL_PROFILES = {"trivial"}
_DEFAULT_REASON = "ordinary source file: one module's behaviour"
_CONTAINERS = {"src", "lib", "app", "packages", "apps", "services", "crates", "modules", "libs",
               "cmd", "internal", "pkg"}
_NO_PACKAGE_KINDS = {"doc", "asset", "style", "content", "template", "fixture", "test", "generated", "text"}
_TOKEN_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def default_table():
    from . import paths
    return _load_json(paths.canon("risk.json"))


def requirements_for(profile, table=None):
    """What a profile carries (target section 3 table), held as data for the gate."""
    table = table or default_table()
    reqs = table.get("requirements") or {}
    if profile in reqs:
        return dict(reqs[profile])
    # Fall back to the built-in table shape so a partial override still answers.
    return dict(default_table().get("requirements", {}).get(profile, {}))


def _patterns_from(table):
    out = []
    for p in (table or {}).get("patterns") or []:
        if isinstance(p, dict) and p.get("profile") in _ORDER and (p.get("glob") or p.get("token") or p.get("keyword")):
            out.append(p)
    return out


def load_patterns(cwd=None):
    """Canon patterns plus user-store, learned (cycle) and project adjustments, in that order."""
    from . import paths
    pats = _patterns_from(default_table())
    pats += _patterns_from(_load_json(paths.data_file("risk.json")))
    if cwd:
        from . import cycle
        pats += cycle.risk_patterns(cwd)  # learned by a cycle, for this project only unless earned wider
        from . import gitutil
        root = gitutil.root(cwd) or os.path.abspath(cwd)
        pats += _patterns_from(_load_json(os.path.join(root, ".sisi", "risk.json")))
    return pats


def _expand_braces(pat):
    m = re.search(r"\{([^{}]*)\}", pat)
    if not m:
        return [pat]
    out = []
    for alt in m.group(1).split(","):
        out += _expand_braces(pat[:m.start()] + alt + pat[m.end():])
    return out


def _glob_match(path, pattern):
    p = path.replace(os.sep, "/").lower()
    for pat in _expand_braces(pattern.replace(os.sep, "/").lower()):
        if fnmatch.fnmatchcase(p, pat):
            return True
        # A leading **/ should also match at the root.
        if pat.startswith("**/") and fnmatch.fnmatchcase(p, pat[3:]):
            return True
        # A trailing /** should match the directory itself and anything under it.
        if pat.endswith("/**") and (p == pat[:-3] or p.startswith(pat[:-2])):
            return True
    return False


def _as_list(v):
    return [v] if isinstance(v, str) else list(v or [])


def _tokens(name):
    return [t.lower() for t in _TOKEN_RE.findall(name)]


def _path_tokens(path):
    """(directory tokens, file stem tokens) of a path."""
    parts = [x for x in path.replace(os.sep, "/").split("/") if x and x != "."]
    if not parts:
        return [], []
    stem = parts[-1].rsplit(".", 1)[0] if "." in parts[-1].lstrip(".") else parts[-1]
    dirs = [t for d in parts[:-1] for t in _tokens(d)]
    return dirs, _tokens(stem)


def _token_match(path, wanted, scope):
    dirs, stem = _path_tokens(path)
    have = (dirs if scope == "dir" else stem if scope == "stem" else dirs + stem)
    for w in wanted:
        w = w.lower()
        for t in have:
            if (t.startswith(w[:-1]) if w.endswith("*") else t == w):
                return True
    return False


def _pattern_hits(path, pat):
    if isinstance(pat.get("except"), dict) and _pattern_hits(path, pat["except"]):
        return False  # a pattern's own exclusion (e.g. a front-end "view model" is not stored data)
    if isinstance(pat.get("requires"), dict) and not _pattern_hits(path, pat["requires"]):
        return False  # a pattern that needs a second cue in the same path (e.g. "key" AND "rotate")
    if pat.get("min_stem_tokens") and len(_path_tokens(path)[1]) < pat["min_stem_tokens"]:
        return False  # compound names only: `user_store`, not a bare `Store`
    if pat.get("glob") and any(_glob_match(path, g) for g in _as_list(pat["glob"])):
        return True
    if pat.get("token") and _token_match(path, _as_list(pat["token"]), pat.get("scope") or "any"):
        return True
    return False


def _name_stage(path, pats):
    """(profile, reason) from the name patterns: the highest match, else an ordinary file."""
    best = None
    for pat in pats:
        if pat.get("stage") == "name" and _pattern_hits(path, pat):
            if best is None or _ORDER[pat["profile"]] > _ORDER[best[0]]:
                best = (pat["profile"], pat.get("reason") or pat["profile"])
    return best or ("isolated", _DEFAULT_REASON)


def classify_path(path, patterns=None):
    """(profile, kind, reason) for one path. `kind` is the kind-stage match, or None."""
    pats = list(patterns if patterns is not None else _patterns_from(default_table()))
    p = str(path).replace(os.sep, "/")
    kind, profile, reason = None, None, None
    is_code = any(pat.get("stage") == "code" and _pattern_hits(p, pat) for pat in pats)
    for pat in pats:
        if pat.get("unless_code") and is_code:
            continue  # a code file is not documentation, an asset or styling whatever it is called
        if pat.get("stage") == "kind" and _pattern_hits(p, pat):
            kind, profile, reason = pat.get("kind") or "kind", pat["profile"], pat.get("reason") or pat["profile"]
            if pat.get("elevate"):
                name_prof, name_reason = _name_stage(p, pats)
                if _ORDER[name_prof] >= _ORDER["data"]:
                    profile, reason = "logic", "test of %s code (%s)" % (name_prof, name_reason)
            break
    if kind is None:
        profile, reason = _name_stage(p, pats)
    if is_code and profile == "trivial":
        profile, reason = "isolated", "source code is never trivial"
    for pat in pats:  # overrides (no stage) only raise
        if pat.get("stage") not in ("kind", "name", "code") and (pat.get("glob") or pat.get("token")) \
                and _pattern_hits(p, pat) and _ORDER[pat["profile"]] > _ORDER[profile]:
            profile, reason = pat["profile"], pat.get("reason") or pat["profile"]
    return profile, kind, reason


def _packages(paths):
    pkgs = set()
    for raw in paths:
        parts = [x for x in raw.replace(os.sep, "/").split("/") if x and x != "."]
        if len(parts) < 2:
            continue
        if parts[0] in _CONTAINERS and len(parts) >= 3:
            pkgs.add(parts[1])
        else:
            pkgs.add(parts[0])
    return pkgs


_DIFF_HEAD = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.M)


def _diff_blocks(diff_text):
    """[(path or None, text)]: text before the first `diff --git` header has no path."""
    heads = list(_DIFF_HEAD.finditer(diff_text))
    if not heads:
        return [(None, diff_text)]
    out = [(None, diff_text[:heads[0].start()])]
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(diff_text)
        out.append((m.group(2), diff_text[m.start():end]))
    return out


def assess(paths, diff_text=None, extra_patterns=None, patterns=None):
    """Return (floor_profile, reasons). Adding a path never lowers the floor."""
    pats = list(patterns if patterns is not None else _patterns_from(default_table()))
    if extra_patterns:
        pats += [p for p in extra_patterns if isinstance(p, dict) and p.get("profile") in _ORDER]
    clean = [str(p).replace(os.sep, "/") for p in (paths or []) if str(p).strip()]
    if not clean:
        return "trivial", ["no changed paths"]
    best, reasons = "trivial", []

    def offer(prof, text):
        nonlocal best, reasons
        if _ORDER[prof] > _ORDER[best]:
            best, reasons = prof, []
        if prof == best and text not in reasons:
            reasons.append(text)

    kinds = {}
    for p in clean:
        prof, kind, why = classify_path(p, pats)
        kinds[p] = kind
        offer(prof, "%s: %s" % (p, why))
    if diff_text:
        for dpath, text in _diff_blocks(diff_text):
            if dpath is not None and classify_path(dpath, pats)[1]:
                continue  # docs, tests, lockfiles and the like are not scanned for keywords
            low = text.lower()
            for pat in pats:
                kw = pat.get("keyword")
                if kw and re.search(r"\b" + re.escape(kw.lower()), low):
                    offer(pat["profile"], "diff: %s" % (pat.get("reason") or pat["profile"]))
    # Structural rule that patterns cannot express: several top-level packages.
    pkgs = _packages([p for p in clean if kinds[p] not in _NO_PACKAGE_KINDS])
    if len(pkgs) >= 2:
        offer("integration", "touches %d top-level packages (%s): integration surface"
              % (len(pkgs), ", ".join(sorted(pkgs))))
    return best, reasons[:6]


def floor_for_working_tree(cwd):
    """(floor, reasons, files) for the working tree against HEAD, untracked included."""
    from . import gitutil
    m = gitutil.measure(cwd)
    files = m.get("files") or []
    diff_text = ""
    try:
        top = gitutil.root(cwd) or cwd
        base = gitutil.head(cwd) or gitutil.EMPTY_TREE
        p = subprocess.run(["git", "diff", "--no-ext-diff", base], cwd=top,
                           capture_output=True, timeout=10)
        diff_text = p.stdout.decode("utf-8", "replace")[:200000]
        # Untracked file contents are part of the change too.
        for rel in files[:50]:
            fp = os.path.join(top, rel)
            try:
                if os.path.isfile(fp) and os.path.getsize(fp) < 200000:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        diff_text += "\ndiff --git a/%s b/%s\n" % (rel, rel) + f.read(20000)
            except OSError:
                pass
    except Exception:
        diff_text = ""
    profile, reasons = assess(files, diff_text=diff_text, patterns=load_patterns(cwd))
    return profile, reasons, files


def declared_profile(cwd):
    """The profile declared in .sisi/contract.json, if any."""
    try:
        with open(os.path.join(cwd, ".sisi", "contract.json"), encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict):
            r = c.get("risk")
            if isinstance(r, dict) and r.get("profile") in _ORDER:
                return r["profile"]
            if c.get("risk_profile") in _ORDER:
                return c["risk_profile"]
    except (OSError, ValueError):
        pass
    return None


def main(args=()):
    """`sisi risk [--json]`: floor, reasons, declared profile, and what the floor requires."""
    args = list(args)
    as_json = "--json" in args
    cwd = os.getcwd()
    floor, reasons, files = floor_for_working_tree(cwd)
    declared = declared_profile(cwd)
    reqs = requirements_for(floor)
    if as_json:
        print(json.dumps({"floor": floor, "reasons": reasons, "files": files,
                          "declared": declared, "requirements": reqs}, indent=2))
        return 0
    print("risk floor: %s" % floor)
    for r in reasons:
        print("  - %s" % r)
    print("(the floor is a minimum worked out from paths alone, not a verdict: judge the change itself too)")
    print("declared: %s" % (declared or "none (no .sisi/contract.json risk.profile)"))
    print("requires: contract=%s, checks=%s, requirement model=%s, risk note=%s, "
          "independent evidence=%s, retro=%s"
          % ("yes" if reqs.get("contract") else "no", reqs.get("checks", "-"),
             "yes" if reqs.get("requirement_model") else "no",
             "yes" if reqs.get("risk_note") else "no",
             "yes" if reqs.get("independent_evidence") else "no", reqs.get("retro", "-")))
    if files:
        print("changed files: %d" % len(files))
    return 0
