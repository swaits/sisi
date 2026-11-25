"""Open faults per project: seen problems that must get a started fix, a named blocker, or evidence of a fix."""
import json, os, time
from . import store

USAGE = 'usage: sisi fault "<what is wrong, 4+ words>" | --started N "<fix>" | --blocked N "<blocker and unblock>" | --fixed N "<evidence>"'
HEAD = 'sisi: open faults. Fix each now or say what blocks it (`sisi fault --started N "<fix>"` | `--blocked N "<blocker>"` | `--fixed N "<evidence>"`):'
BLOCK = 'sisi: open fault(s) with no fix started and no blocker named: %s. Start a fix (`sisi fault --started N "<fix>"`), name what blocks it (`sisi fault --blocked N "<blocker and unblock>"`), or close it (`sisi fault --fixed N "<evidence>"`).'
_path = lambda cwd=None: os.path.join(store.STATE, "core-faults", store.project_key(cwd) + ".json")


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

def show(cwd=None, gate=False):
    opened = [f for f in _load(_path(cwd))["items"] if not gate or f["state"] == "open"]
    return (BLOCK % "; ".join("#%d %s" % (f["id"], f["text"]) for f in opened) if gate else "\n".join([HEAD] + [_fmt(f) for f in opened])) if opened else ""


def run(args, cwd=None):
    if not args:
        return print("\n".join(lines(cwd)) or "no open faults.") or 0
    flag = args[0] if args[0] in ("--started", "--blocked", "--fixed") else ""
    body = " ".join(" ".join(args[2:] if flag else args).split())[:300]
    if (flag and (len(args) < 3 or not args[1].isdecimal() or len(body.split()) < 2)) or (not flag and (args[0].startswith("-") or len(body.split()) < 4)):
        return print(USAGE) or 1
    p = _path(cwd)
    try:
        with store.lock(p):
            doc = _load(p, strict=True)
            if os.path.exists(p) and not (os.stat(p).st_mode & 0o200):
                raise OSError("%s is read-only" % p)
            if flag:
                hit = next((f for f in doc["items"] if f["id"] == int(args[1])), None)
                if not hit:
                    return print("sisi fault: #%s not found; %s" % (args[1], USAGE)) or 1
                doc["items"] = [f for f in doc["items"] if f["id"] != hit["id"]] if flag == "--fixed" else doc["items"]
                hit.update(state=flag[2:], note=body)
            else:
                hit = {"id": doc["next"], "state": "open", "at": time.time(), "text": body, "note": ""}
                doc["next"], doc["items"] = doc["next"] + 1, doc["items"] + [hit]
            out = json.dumps(doc)
            if len(out.encode("utf-8")) > 64000:
                raise OSError("%s would exceed 64,000 bytes" % p)
            store.write(p, out)
    except OSError as e:
        return print("sisi fault: %s" % e) or 1
    return print(_fmt(hit)) or 0
