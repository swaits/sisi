"""Risk profiles: ceremony follows risk, not diff size (SPEC 5.3, target section 3).

`assess` is a pure function from changed paths (and optionally diff text) to a floor
profile plus the reasons. Tables come from canon/risk.json, a user-store adjustment
file, and a project override at .sisi/risk.json; later tables only add patterns.
"""
import fnmatch, json, os, subprocess

PROFILES = ["trivial", "isolated", "logic", "integration", "data", "critical", "release"]
_ORDER = {name: i for i, name in enumerate(PROFILES)}
_TRIVIAL_PROFILES = {"trivial"}


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
        if isinstance(p, dict) and p.get("profile") in _ORDER and (p.get("glob") or p.get("keyword")):
            out.append(p)
    return out


def load_patterns(cwd=None):
    """Canon patterns plus user-store and project adjustments, in that order."""
    from . import paths
    pats = _patterns_from(default_table())
    pats += _patterns_from(_load_json(paths.data_file("risk.json")))
    if cwd:
        from . import gitutil
        root = gitutil.root(cwd) or os.path.abspath(cwd)
        pats += _patterns_from(_load_json(os.path.join(root, ".sisi", "risk.json")))
    return pats


def _glob_match(path, pattern):
    p = path.replace(os.sep, "/")
    pat = pattern.replace(os.sep, "/")
    if fnmatch.fnmatch(p, pat):
        return True
    # A leading **/ should also match at the root.
    if pat.startswith("**/") and fnmatch.fnmatch(p, pat[3:]):
        return True
    # A trailing /** should match the directory itself and anything under it.
    if pat.endswith("/**") and (p == pat[:-3] or p.startswith(pat[:-2])):
        return True
    return False


def _packages(paths):
    pkgs = set()
    for raw in paths:
        parts = [x for x in raw.replace(os.sep, "/").split("/") if x and x != "."]
        if len(parts) < 2:
            continue
        if parts[0] in ("src", "lib", "app") and len(parts) >= 3:
            pkgs.add(parts[1])
        elif len(parts) >= 2:
            pkgs.add(parts[0])
    return pkgs


def assess(paths, diff_text=None, extra_patterns=None, patterns=None):
    """Return (floor_profile, reasons). Adding a path never lowers the floor."""
    pats = list(patterns if patterns is not None else _patterns_from(default_table()))
    if extra_patterns:
        pats += [p for p in extra_patterns if isinstance(p, dict) and p.get("profile") in _ORDER]
    clean = [str(p).replace(os.sep, "/") for p in (paths or []) if str(p).strip()]
    if not clean:
        return "trivial", ["no changed paths"]
    best, reasons = "trivial", []
    matched_profiles = []
    trivial_hits = set()
    for pat in pats:
        prof = pat["profile"]
        reason = pat.get("reason") or prof
        if pat.get("glob"):
            hits = [p for p in clean if _glob_match(p, pat["glob"])]
            if hits:
                matched_profiles.append(prof)
                if prof == "trivial":
                    trivial_hits.update(hits)
                if _ORDER[prof] >= _ORDER[best]:
                    if _ORDER[prof] > _ORDER[best]:
                        best, reasons = prof, []
                    reasons.append("%s: %s" % (hits[0], reason))
        if pat.get("keyword") and diff_text:
            if pat["keyword"].lower() in diff_text.lower():
                matched_profiles.append(prof)
                if _ORDER[prof] >= _ORDER[best]:
                    if _ORDER[prof] > _ORDER[best]:
                        best, reasons = prof, []
                    reasons.append("diff: %s" % reason)
    # Structural rules that patterns cannot express. Documentation and styling
    # paths do not count as packages: two docs folders are not an integration.
    pkgs = _packages([p for p in clean if p not in trivial_hits])
    if len(pkgs) >= 2 and _ORDER["integration"] >= _ORDER[best]:
        if _ORDER["integration"] > _ORDER[best]:
            best, reasons = "integration", []
        reasons.append("touches %d top-level packages (%s): integration surface"
                       % (len(pkgs), ", ".join(sorted(pkgs))))
    if best == "trivial" and len(trivial_hits) == len(clean):
        return "trivial", reasons or ["documentation, text or styling only"]
    if best == "trivial":
        return "isolated", ["one module's behaviour changed"]
    if not reasons:
        reasons = ["%s: matched the %s profile" % (clean[0], best)]
    # Keep reasons short and de-duplicated, strongest first is unnecessary: keep order.
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return best, out[:6]


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
                        diff_text += "\n" + f.read(20000)
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
