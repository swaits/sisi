"""Open faults per project: seen problems that must get a started fix, a named blocker, or evidence of a fix."""
import json, os, time
from . import store

USAGE = 'usage: sisi fault "<what is wrong, 4+ words>" | --started N "<fix>" | --blocked N "<blocker and unblock>" | --fixed N "<evidence>"'
HEAD = 'sisi: open faults. Fix each now or say what blocks it (`sisi fault --started N "<fix>"` | `--blocked N "<blocker>"` | `--fixed N "<evidence>"`):'
BLOCK = 'sisi: open fault(s) with no fix started and no blocker named: %s. Start a fix (`sisi fault --started N "<fix>"`), name what blocks it (`sisi fault --blocked N "<blocker and unblock>"`), or close it (`sisi fault --fixed N "<evidence>"`).'
_path = lambda cwd=None: os.path.join(store.STATE, "core-faults", store.project_key(cwd) + ".json")
_gb = lambda b: "%d GB" % round(b / 1e9) if b >= 1e9 else "%.1f GB" % (b / 1e9)

def _load(p, strict=False):
    d = os.path.dirname(p)
    why, raw = (("a symlink", None) if os.path.islink(d) else ("not a directory", None) if os.path.lexists(d) and not os.path.isdir(d) else store.regular(p, True))
    if why and strict:
        raise OSError("%s is %s" % (p, why))
    try:
        doc = json.loads(raw.decode("utf-8")) if raw is not None and not why else {"next": 1, "items": []}
        if not (isinstance(doc, dict) and isinstance(doc.get("items"), list)):
            raise ValueError
        items = [x for x in doc["items"] if isinstance(x, dict) and type(x.get("id")) is int and x.get("state") in ("open", "started", "blocked") and isinstance(x.get("text"), str)]
        return {"next": doc["next"] if type(doc.get("next")) is int and doc["next"] > 0 else max((x["id"] for x in items), default=0) + 1, "items": items}
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        if strict:
            raise OSError("%s is not valid JSON" % p)
        return {"next": 1, "items": []}

def _fmt(f):
    s = max(0, int(time.time() - f["at"])) if type(f.get("at")) in (int, float) and f["at"] == f["at"] and abs(f["at"]) < 1e12 else 0
    age = "%ds" % s if s < 60 else "%dm" % (s // 60) if s < 3600 else "%dh" % (s // 3600) if s < 86400 else "%dd" % (s // 86400)
    return "#%d [%s, %s] %s%s" % (f["id"], f["state"], age, f["text"], " — " + str(f["note"]) if f.get("note") else "")

def lines(cwd=None):
    return [_fmt(f) for f in _load(_path(cwd))["items"]]

def gate(cwd=None):
    opened = [f for f in _load(_path(cwd))["items"] if f["state"] == "open"]
    return BLOCK % "; ".join("#%d %s" % (f["id"], f["text"]) for f in opened) if opened else ""

def add(cwd, text, kind="", flag="", fid=0):
    p = _path(cwd)
    with store.lock(p):
        doc = _load(p, strict=True)
        if os.path.exists(p) and not (os.stat(p).st_mode & 0o200):
            raise OSError("%s is read-only" % p)
        if flag:
            hit = next((f for f in doc["items"] if f["id"] == fid), None)
            if not hit:
                return None
            doc["items"] = [f for f in doc["items"] if f["id"] != fid] if flag == "--fixed" else doc["items"]
            hit.update(state=flag[2:], note=text)
        else:
            if kind and any(f.get("kind") == kind for f in doc["items"]):
                return None
            hit = {"id": doc["next"], "state": "open", "at": time.time(), "text": text, "note": "", **({"kind": kind} if kind else {})}
            doc["next"], doc["items"] = doc["next"] + 1, doc["items"] + [hit]
        out = json.dumps(doc)
        if len(out.encode("utf-8")) > 64000:
            raise OSError("%s would exceed 64,000 bytes" % p)
        store.write(p, out)
    return hit

def _checkouts(cwd):
    try:
        cur = os.path.abspath(cwd)
        while not os.path.lexists(g := os.path.join(cur, ".git")) and cur != os.path.dirname(cur):
            cur = os.path.dirname(cur)
        first = lambda p: ((store.regular(p, True)[1] or b"").decode("utf-8", "replace").splitlines() or [""])[0].strip()
        common = g if os.path.isdir(g) and not os.path.islink(g) else ""
        if not common and (line := first(g)).startswith("gitdir:"):
            gd = os.path.normpath(os.path.join(cur, line[7:].strip()))
            cd = first(os.path.join(gd, "commondir"))
            common = os.path.normpath(os.path.join(gd, cd)) if cd else (os.path.dirname(os.path.dirname(gd)) if os.path.basename(os.path.dirname(gd)) == "worktrees" else gd)
        return len(os.listdir(wt)) if common and os.path.isdir(wt := os.path.join(common, "worktrees")) else 0
    except OSError:
        return 0

def check(cwd, start_free=None):
    cfg, hits, pos = store.config(), [], lambda k: type(cfg[k]) in (int, float) and cfg[k] > 0
    try:
        st = os.statvfs(cwd) if pos("disk_free_percent") or (pos("disk_drop_percent") and type(start_free) in (int, float)) else None
        total, free = (st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize) if st else (0, 0)
        if total > 0 and pos("disk_free_percent") and free * 100 < cfg["disk_free_percent"] * total:
            hits.append(("disk_free", "The disk holding this project is %d%% full (%s free). Find what this work made (copies, checkouts, build folders) and remove it." % (round(100 * (total - free) / total), _gb(free))))
        if total > 0 and pos("disk_drop_percent") and type(start_free) in (int, float) and (start_free - free) * 100 > cfg["disk_drop_percent"] * total:
            hits.append(("disk_drop", "This session's work has used %s of disk. Remove what is finished before making more." % _gb(start_free - free)))
    except OSError:
        pass
    if pos("checkouts") and (n := _checkouts(cwd)) > cfg["checkouts"]:
        hits.append(("checkouts", "This repository has %d checkouts. Remove the ones whose work is merged or abandoned." % n))
    have, unsaved = {f.get("kind") for f in _load(_path(cwd))["items"]}, []
    for kind, text in [h for h in hits if h[0] not in have]:
        try:
            add(cwd, text, kind)
        except OSError:
            unsaved.append("[open] " + text)
    return "\n".join([HEAD] + ls) if (ls := lines(cwd) + unsaved) else ""

def run(args, cwd=None):
    if not args:
        return print("\n".join(lines(cwd)) or "no open faults.") or 0
    flag = args[0] if args[0] in ("--started", "--blocked", "--fixed") else ""
    body = " ".join(" ".join(args[2:] if flag else args).split())[:300]
    if (flag and (len(args) < 3 or not args[1].isdecimal() or len(body.split()) < 2)) or (not flag and (args[0].startswith("-") or len(body.split()) < 4)):
        return print(USAGE) or 1
    try:
        hit = add(cwd, body, flag=flag, fid=int(args[1]) if flag else 0)
    except OSError as e:
        return print("sisi fault: %s" % e) or 1
    return print(_fmt(hit)) or 0 if hit else print("sisi fault: #%s not found; %s" % (args[1], USAGE)) or 1
