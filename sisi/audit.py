"""Inventory of standing instructions each tool loads. Counts lines; does not judge."""
import glob, json, os, re

from . import paths


def _lines(p):
    try:
        with open(p, "rb") as f:
            return f.read().count(b"\n") + 1
    except OSError:
        return None


def _imports(p, depth=0, seen=None):
    """Files pulled in by `@path` lines (Claude Code import syntax)."""
    seen = seen if seen is not None else set()
    out = []
    try:
        text = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for m in re.finditer(r"^@(\S+)\s*$", text, re.M):
        q = os.path.expanduser(m.group(1))
        if not os.path.isabs(q):
            q = os.path.join(os.path.dirname(p), q)
        if q not in seen and os.path.isfile(q):
            seen.add(q)
            out.append(("import of %s" % os.path.basename(p), q))
            if depth < 4:
                out += _imports(q, depth + 1, seen)
    return out


def _skills(d, label):
    return [(label, f) for f in sorted(glob.glob(os.path.join(d, "*", "SKILL.md")))]


def _dirmd(d, label):
    return [(label, f) for f in sorted(glob.glob(os.path.join(d, "**", "*.md"), recursive=True))]


def collect():
    h = paths.home()
    j = lambda *a: os.path.join(h, *a)
    inv = {}
    cl = []
    for f in (j(".claude", "CLAUDE.md"),):
        if os.path.isfile(f):
            cl.append(("global instructions", f))
            cl += _imports(f)
    cl += _dirmd(j(".claude", "rules"), "rules")
    cl += _skills(j(".claude", "skills"), "skill")
    cl += _skills(j(".agents", "skills"), "skill (shared)")
    try:
        with open(j(".claude", "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            plugins = json.load(f).get("plugins", {})
    except (OSError, ValueError, AttributeError):
        plugins = {}
    for name, entries in sorted(plugins.items()):
        for e in entries if isinstance(entries, list) else []:
            ip = e.get("installPath") if isinstance(e, dict) else None
            if ip:
                pl = "plugin " + name
                cl += _skills(ip, pl + " skill") + _dirmd(os.path.join(ip, "commands"), pl + " command") \
                    + _dirmd(os.path.join(ip, "agents"), pl + " agent")
    inv["claude-code"] = cl
    cx = []
    for n in ("AGENTS.override.md", "AGENTS.md"):
        f = j(".codex", n)
        if os.path.isfile(f):
            cx.append(("global instructions", f))
    cx += _skills(j(".codex", "skills"), "skill") + _skills(j(".agents", "skills"), "skill (shared)")
    inv["codex"] = cx
    oc = []
    f = j(".config", "opencode", "AGENTS.md")
    if os.path.isfile(f):
        oc.append(("global instructions", f))
    else:
        f2 = j(".claude", "CLAUDE.md")
        if os.path.isfile(f2):
            oc.append(("global instructions (fallback to Claude's file)", f2))
    for n in ("opencode.json", "opencode.jsonc"):
        cf = j(".config", "opencode", n)
        try:
            for ins in json.load(open(cf, encoding="utf-8")).get("instructions", []):
                q = os.path.expanduser(ins)
                if os.path.isfile(q):
                    oc.append(("config instructions", q))
        except (OSError, ValueError, AttributeError):
            pass
    oc += _dirmd(j(".config", "opencode", "agents"), "agent") + _dirmd(j(".config", "opencode", "commands"), "command")
    oc += _skills(j(".agents", "skills"), "skill (shared)")
    inv["opencode"] = oc
    mu = []
    for f in (j(".config", "muse", "AGENTS.md"),):
        if os.path.isfile(f):
            mu.append(("global instructions", f))
    mu += _skills(j(".agents", "skills"), "skill (shared)")
    inv["muse"] = mu
    return inv


def main(args=()):
    inv = collect()
    grand = 0
    for tool, items in inv.items():
        print("%s" % tool)
        tot = 0
        for label, f in items:
            n = _lines(f) or 0
            tot += n
            print("  %6d  %-34s %s" % (n, label[:34], f))
        if not items:
            print("  (none found)")
        print("  %6d  total\n" % tot)
        grand += tot
    print("all tools: %d lines (shared files counted once per tool)" % grand)
    return 0
