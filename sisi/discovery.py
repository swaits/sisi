"""A changing environment: workers that appear after sisi was installed become routable through normal use.

Three ways in, none scheduled (everything runs inside a hook or a command the person already ran):
  host    the after-tool hook watches for the host's capability listing and its delegation tool (their
          names and the shape of their data are in canon/discovery.json) and records each provider and
          model the host says can run a task, as the worker `provider/model` reached through the host's
          cross-provider delegation. Kept in the scratch folder: the next listing rebuilds it.
  PATH    session start lists the executables in the user-level folders on PATH (cached; refreshed on a
          folder's change, an age or a counter) and names the new ones once. Nothing is executed.
  driver  `sisi workers learn NAME` hands a cheap worker a brief; the driver it writes (a small JSON file:
          the format of workers.DRIVERS as data) is validated, stored in the user store as unverified,
          proved by ONE smoke task, and only then usable. A driver with a flag that switches off approvals
          waits for the owner (`sisi approve`) and never runs, smoke task included, before that.
A worker that arrives this way is unproven: routine work only (difficulty 1) until it has judged attempts,
checked a level more carefully, and explored more often when it costs nothing extra (see routing.py).
Every hook entry point fails open. A driver file is untrusted input written by an agent: validated field by
field and run without a shell.
"""
import json, os, re, shlex, time

from . import paths, store

DEFAULTS = {"path_refresh_s": 6 * 3600, "path_every_starts": 25, "drop_after_listings": 3,
            "catalogue_over": 8, "smoke_timeout_s": 120, "allowance_cache_s": 300, "allowance_timeout_s": 8}
MAX_NAMED = 5
SMOKE_PROMPT = ("Reply with exactly this one word and nothing else: %s. "
                "Do not read, write, create or run anything.")
PLACEHOLDERS = ("{model_flag}", "{effort_flag}", "{cwd_flag}", "{cwd}")
DRIVER_FIELDS = ("name", "exe", "run", "list", "list_kind", "model_flag", "effort_flag", "cwd_flag", "plan",
                 "auth_signatures", "limit_signatures", "tokens_regex", "approvals_off_reason", "notes")
USAGE_WORDS = re.compile(r"unknown (flag|option|command)|unrecogni[sz]ed|invalid (option|flag|argument)|"
                         r"no such (option|flag)|unexpected argument|flag provided but not defined|"
                         r"usage:|did you mean", re.I)
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
_EXE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")

_DATA = []


def data():
    """canon/discovery.json (flag patterns, hints) with the hosts' tools from canon/orchestration-tools.json (the one
    description of a host's tools, read through orchestration.reach_specs), read once per process."""
    if not _DATA:
        try:
            with open(paths.canon("discovery.json"), encoding="utf-8") as f:
                d = json.load(f)
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        try:
            from . import orchestration
            d = dict(d, hosts=orchestration.reach_specs())
        except Exception as e:  # no hosts: nothing is learned from a host, the rest of discovery works
            store.log_error("discovery-hosts", e)
            d = dict(d, hosts=[])
        _DATA.append(d)
    return _DATA[0]


def conf():
    """The `discovery` settings, each valid or its default; the config is read once per call."""
    c = store.config().get("discovery")
    c = c if isinstance(c, dict) else {}
    return {k: (c[k] if isinstance(c.get(k), (int, float)) and not isinstance(c.get(k), bool) and c[k] >= 0 else d)
            for k, d in DEFAULTS.items()}


# ---------------------------------------------------------------- small files


def _state_file(name):
    return os.path.join(paths.state(), "discovery", name)


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _day(ts):
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "an unknown date"


def _plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


# ---------------------------------------------------------------- a new command-line tool on PATH


def user_path_dirs(path=None):
    """The PATH folders that live under the user's own home (system folders are never listed)."""
    home = os.path.realpath(paths.home())
    out = []
    for d in (os.environ.get("PATH", "") if path is None else path).split(os.pathsep):
        if not d or not os.path.isabs(d):
            continue
        rp = os.path.realpath(d)
        if (rp == home or rp.startswith(home + os.sep)) and os.path.isdir(rp) and rp not in out:
            out.append(rp)
    return out


def list_executables(folder):
    """Names of the executable files in one folder. Nothing is run; a file is only looked at."""
    names = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if not e.name.startswith(".") and e.is_file() and os.access(e.path, os.X_OK):
                        names.append(e.name)
                except OSError:
                    pass
    except OSError:
        pass
    return names


def _marks(dirs):
    out = {}
    for d in dirs:
        try:
            out[d] = os.stat(d).st_mtime_ns
        except OSError:
            out[d] = 0
    return out


def _known_tool_names():
    """Names sisi already has a driver for (built in or learned): never announced as new."""
    from . import workers
    names = {d["exe"] for d in workers.DRIVERS}
    names.update(load_drivers())
    return names


def _candidate_names(names, known):
    skip = set(data().get("not_a_tool") or ()) | known
    return [n for n in names if _EXE_NAME.match(n) and n not in skip]


def _hinted(name):
    hints = set(data().get("agent_name_hints") or ())
    return bool(hints & set(re.split(r"[-_.]", name.lower())))


def new_tools_line(new):
    """One line naming at most five new tools, those whose names look like an agent's first."""
    ordered = sorted(new, key=lambda n: (not _hinted(n), n))
    shown = ordered[:MAX_NAMED]
    more = " and %d more" % (len(ordered) - len(shown)) if len(ordered) > len(shown) else ""
    return ("sisi: new command-line tool%s on this machine since the last look: %s%s. If one is an AI coding agent, "
            "have a fast, cheap worker learn it so it can be routed to: `sisi workers learn NAME` prints the brief "
            "for that worker. Ordinary programs can be ignored." % ("" if len(new) == 1 else "s", ", ".join(shown), more))


def session_start(now=None):
    """The session-start notice about new executables in the user-level PATH folders, or "". The first
    run stores the list and says nothing. The list is looked at again when a folder changed, when it is
    older than discovery.path_refresh_s, or after discovery.path_every_starts session starts; otherwise
    one stat per folder is all it costs. A name is announced once."""
    now = time.time() if now is None else now
    f = _state_file("path.json")
    st = _load(f)
    dirs = user_path_dirs()
    marks = _marks(dirs)
    starts = int(st.get("starts") or 0) + 1
    first = not isinstance(st.get("names"), list)
    c = conf()
    due = (first or st.get("marks") != marks or now - float(st.get("checked") or 0) >= c["path_refresh_s"]
           or starts >= c["path_every_starts"])
    if not due:
        st["starts"] = starts
        _save(f, st)
        return ""
    names = sorted({n for d in dirs for n in list_executables(d)})
    announced = [n for n in st.get("announced") or [] if isinstance(n, str)]
    new = [] if first else _candidate_names([n for n in names if n not in set(st["names"]) | set(announced)],
                                            _known_tool_names())
    st.update(names=names, marks=marks, checked=now, starts=0, announced=(announced + new)[-500:])
    _save(f, st)
    return new_tools_line(new) if new else ""


# ---------------------------------------------------------------- what the host can reach


def dig(obj, dotted):
    for part in str(dotted or "").split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def _objects(x, depth=0):
    """Every JSON object inside a tool result, which a host may wrap as text blocks or a string."""
    if depth > 5:
        return
    if isinstance(x, str):
        s = x.strip()
        if s[:1] in "{[":
            try:
                yield from _objects(json.loads(s), depth + 1)
            except ValueError:
                pass
    elif isinstance(x, dict):
        yield x
        for k in ("content", "structuredContent", "result", "text", "output"):
            if k in x:
                yield from _objects(x[k], depth + 1)
    elif isinstance(x, list):
        for item in x[:20]:
            yield from _objects(item, depth + 1)


def _clean_id(v, limit=200):
    return v if isinstance(v, str) and 0 < len(v) <= limit and v.isprintable() else None


def parse_listing(result, spec, blocking=()):
    """[{provider, kind, name, usable, reason, models: [{id, label}]}] from a capability listing, by the
    host's field names (the data file). A provider is usable only when the host says it can run a task
    and states no blocking constraint. Anything malformed is skipped."""
    cap = spec.get("capability") or {}
    found = None
    for obj in _objects(result):
        rows = dig(obj, cap.get("providers"))
        if isinstance(rows, list):
            found = rows
            break
    out = []
    for p in (found or [])[:200]:
        pid = _clean_id(p.get(cap.get("provider"))) if isinstance(p, dict) else None
        if pid is None:
            continue
        constraints = [c for c in (p.get(cap.get("constraints")) or []) if isinstance(c, str)][:5]
        blocked = [c for c in constraints if any(w in c.lower() for w in blocking)]
        usable = p.get(cap.get("usable")) is True and not blocked
        models = []
        raw = p.get(cap.get("models"))
        for m in (raw[:2000] if isinstance(raw, list) else []):
            mid = _clean_id(m.get(cap.get("model"))) if isinstance(m, dict) else None
            if mid:
                label = m.get(cap.get("label"))
                models.append({"id": mid, "label": label[:80] if isinstance(label, str) else None})
        out.append({"provider": pid, "kind": _clean_id(p.get(cap.get("kind")), 60),
                    "name": _clean_id(p.get(cap.get("name")), 80), "usable": usable,
                    "reason": (blocked or constraints or [None])[0] if not usable else None, "models": models})
    return out


def host_state_file():
    return _state_file("host-workers.json")


def apply_listing(state, host, parsed, now, drop_after, catalogue_over):
    """Fold a listing into the stored host workers. Returns how many usable workers are new and worth
    trying (a provider with more models than discovery.catalogue_over is a catalogue, not a menu).
    A worker missing from `drop_after` listings in a row is forgotten."""
    rec = state.setdefault("hosts", {}).setdefault(host, {"providers": {}})
    provs = rec["providers"]
    seen = set()
    fresh = 0
    for p in parsed:
        entry = provs.setdefault(p["provider"], {"models": {}})
        entry.update(kind=p["kind"], name=p["name"], usable=p["usable"], reason=p["reason"])
        small = len(p["models"]) <= catalogue_over
        for m in p["models"]:
            mrec = entry["models"].get(m["id"])
            if mrec is None:
                mrec = entry["models"][m["id"]] = {"first_seen": now, "announced": False, "source": "listing"}
            if p["usable"] and small and not mrec.get("announced"):
                fresh += 1
            if p["usable"]:
                mrec["announced"] = True
            mrec.update(label=m["label"], last_seen=now, missed=0)
            seen.add((p["provider"], m["id"]))
    for pid in list(provs):
        for mid in list(provs[pid]["models"]):
            if (pid, mid) not in seen:
                mrec = provs[pid]["models"][mid]
                mrec["missed"] = int(mrec.get("missed") or 0) + 1
                if mrec["missed"] >= drop_after:
                    del provs[pid]["models"][mid]
        if not provs[pid]["models"]:
            del provs[pid]
    return fresh


def apply_delegation(state, host, provider, model, now):
    """A delegation seen in use: recorded the same way, already announced (the agent just used it)."""
    provs = state.setdefault("hosts", {}).setdefault(host, {"providers": {}})["providers"]
    entry = provs.setdefault(provider, {"models": {}, "usable": True})
    mrec = entry["models"].setdefault(model, {"first_seen": now, "source": "delegation", "label": None})
    mrec.update(announced=True, last_seen=now, missed=0, used=now)
    return mrec


def _match(pattern, tool):
    try:
        return bool(pattern) and bool(re.search(pattern, tool))
    except re.error:
        return False


def _tool_input(payload):
    for k in ("tool_input", "toolInput", "input"):
        if isinstance(payload.get(k), dict):
            return payload[k]
    return {}


def _tool_result(payload):
    for k in ("tool_response", "toolResponse", "tool_result", "tool_output", "result", "output"):
        if payload.get(k) is not None:
            return payload[k]
    return None


def after_tool(payload):
    """The after-tool hook's one call. A listing or delegation tool of a known host updates the stored
    host workers; once per set of new workers it prints one line to the agent. Everything else returns
    at once. Fails open."""
    try:
        if not isinstance(payload, dict):
            return
        tool = payload.get("tool_name") or payload.get("toolName") or payload.get("tool")
        if not isinstance(tool, str) or not tool:
            return
        hosts = [h for h in data().get("hosts") or [] if isinstance(h, dict)]
        listing = next((h for h in hosts if _match(h.get("capability_tool"), tool)), None)
        delegation = None if listing else next((h for h in hosts if _match(h.get("delegation_tool"), tool)), None)
        if listing is None and delegation is None:
            return
        f = host_state_file()
        state = _load(f)
        now = time.time()
        line = ""
        if listing is not None:
            parsed = parse_listing(_tool_result(payload), listing, data().get("blocking_constraint_words") or ())
            if not parsed:
                return
            c = conf()
            fresh = apply_listing(state, listing["host"], parsed, now, int(c["drop_after_listings"]) or 1,
                                  c["catalogue_over"])
            if fresh:
                line = ("sisi: %s reachable through the host's cross-provider delegation (new and unproven: "
                        "routine work only until judged; `sisi workers` lists them, `sisi route` can choose them)."
                        % _plural(fresh, "new worker"))
        else:
            spec = delegation.get("delegation") or {}
            inp = _tool_input(payload)
            provider, model = _clean_id(dig(inp, spec.get("provider"))), _clean_id(dig(inp, spec.get("model")))
            if not provider or not model:
                return
            apply_delegation(state, delegation["host"], provider, model, now)
        _save(f, state)
        if line:
            import sys
            ev = payload.get("hook_event_name") or "PostToolUse"
            sys.stdout.write(json.dumps({"systemMessage": line, "hookSpecificOutput": {
                "hookEventName": ev, "additionalContext": line}}) + "\n")
    except Exception as e:  # a tool call is never held up by this
        store.log_error("discovery-after-tool", e)


def host_tools():
    """Discovery entries (the shape workers.discover() makes) for the providers the host lists, one per
    provider, each model named `provider/model` as the host names it."""
    out = []
    spec = {h.get("host"): h for h in data().get("hosts") or [] if isinstance(h, dict)}
    for host, hrec in (_load(host_state_file()).get("hosts") or {}).items():
        d = (spec.get(host) or {}).get("delegation") or {}
        for pid, p in sorted((hrec.get("providers") or {}).items()):
            if not isinstance(p, dict) or not isinstance(p.get("models"), dict):
                continue
            usable = p.get("usable") is not False
            firsts = [m.get("first_seen") for m in p["models"].values() if isinstance(m, dict) and m.get("first_seen")]
            out.append({"name": pid, "installed": True, "usable": usable,
                        "reason": None if usable else "the host says it cannot run a task (%s)" % (p.get("reason") or "no reason given"),
                        "models": ["%s/%s" % (pid, m) for m in sorted(p["models"])], "plan": None,
                        "host": {"host": host, "provider": pid, "tool": d.get("tool_name"), "provider_field": d.get("provider"),
                                 "model_field": d.get("model"), "first_seen": min(firsts) if firsts else None}})
    return out


def host_route(tool_entry, worker):
    """(provider, model) the host's delegation tool needs for a worker of this provider entry."""
    prov = tool_entry["host"]["provider"]
    return prov, worker[len(prov) + 1:] if worker.startswith(prov + "/") else worker


def host_mechanism(entry, worker):
    h = entry["host"]
    prov, model = host_route(entry, worker)
    return ("use the host's cross-provider delegation%s: %s=%s and %s=%s"
            % (" (its `%s` tool)" % h["tool"] if h.get("tool") else "", h.get("provider_field") or "provider", prov,
               h.get("model_field") or "model", model))


# ---------------------------------------------------------------- learned drivers: validation


def _bypass_patterns():
    out = []
    for p in data().get("approval_bypass_patterns") or []:
        try:
            out.append(re.compile(p, re.I))
        except re.error:
            pass
    return out


def bypass_args(argv):
    """The arguments of a command that switch off approvals or a sandbox, by the patterns in the data file."""
    pats = _bypass_patterns()
    return [a for a in argv if isinstance(a, str) and any(p.search(a) for p in pats)]


def _signatures(v, field, problems):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > 12 or not all(isinstance(s, str) and 6 <= len(s.strip()) <= 80 for s in v):
        problems.append("%s: a list of at most 12 phrases of 6 to 80 characters" % field)
        return []
    return [s.strip().lower() for s in v]


def _argv(v, field, problems, prompt):
    if not isinstance(v, list) or not 1 <= len(v) <= 40 or not all(isinstance(a, str) for a in v):
        problems.append("%s: a list of 1 to 40 arguments" % field)
        return None
    count = 0
    for a in v:
        if not a or len(a) > 300 or "\0" in a or "\n" in a:
            problems.append("%s: an argument is empty, longer than 300 characters or has a control character" % field)
            return None
        if a == "{prompt}":
            count += 1
        elif a in PLACEHOLDERS:
            pass
        elif "{" in a or "}" in a:
            problems.append("%s: %r mixes text with a placeholder; a placeholder must be a whole argument" % (field, a[:40]))
            return None
    if prompt and count != 1:
        problems.append("%s: exactly one argument must be the whole token {prompt} (found %d)" % (field, count))
    if not prompt and count:
        problems.append("%s: must not contain {prompt}" % field)
    return list(v)


def validate_driver(obj, which, builtin_names=()):
    """(driver, problems): a clean driver dict from an agent-written file, or the list of what is wrong.
    `which(name)` finds a command on PATH. Only known fields pass; the command is a bare argument list."""
    problems = []
    if not isinstance(obj, dict):
        return None, ["the file must hold one JSON object"]
    extra = sorted(set(obj) - set(DRIVER_FIELDS))
    if extra:
        problems.append("unknown field(s): %s (allowed: %s)" % (", ".join(extra[:6]), ", ".join(DRIVER_FIELDS)))
    name, exe = obj.get("name"), obj.get("exe")
    if not isinstance(name, str) or not _NAME.match(name):
        problems.append("name: lowercase letters, digits, dot, dash or underscore, up to 40 characters")
    elif name in builtin_names:
        problems.append("name: %r belongs to a driver sisi already has" % name)
    if not isinstance(exe, str) or not _EXE_NAME.match(exe):
        problems.append("exe: a bare command name, no folder (it must be found on PATH)")
    elif exe in (data().get("not_a_tool") or ()):
        problems.append("exe: %r is a shell or interpreter, not an agent tool" % exe)
    elif not which(exe):
        problems.append("exe: %r is not on PATH" % exe)
    run = _argv(obj.get("run"), "run", problems, True)
    if run is not None and isinstance(exe, str) and run[0] != exe:
        problems.append("run: the first argument must be exe (%r)" % exe)
    lst = None
    if obj.get("list") is not None:
        lst = _argv(obj.get("list"), "list", problems, False)
        if lst is not None and (lst[0] != exe or any(a in PLACEHOLDERS for a in lst)):
            problems.append("list: must start with exe and hold no placeholders")
    if obj.get("list_kind") not in (None, "lines"):
        problems.append('list_kind: only "lines" (one model name per line)')
    flags = {}
    for field in ("model_flag", "effort_flag", "cwd_flag"):
        v = obj.get(field)
        if v is not None and not (isinstance(v, str) and re.match(r"^-[A-Za-z-]{1,40}$", v)):
            problems.append("%s: a flag such as --model, or null" % field)
        flags[field] = v
    plan = obj.get("plan")
    if plan not in (None, "free", "flat", "per-use"):
        problems.append('plan: "free", "flat", "per-use" or null')
    for field in ("approvals_off_reason", "notes"):
        v = obj.get(field)
        if v is not None and not (isinstance(v, str) and len(v) <= 600):
            problems.append("%s: text of at most 600 characters" % field)
    rx = obj.get("tokens_regex")
    if rx is not None:
        try:
            if not (isinstance(rx, str) and len(rx) <= 120 and re.compile(rx).groups == 1):
                raise ValueError
        except (re.error, ValueError):
            problems.append("tokens_regex: a regular expression of at most 120 characters with exactly one group")
    sig = {"auth_signatures": _signatures(obj.get("auth_signatures"), "auth_signatures", problems),
           "limit_signatures": _signatures(obj.get("limit_signatures"), "limit_signatures", problems)}
    if problems:
        return None, problems
    driver = {"name": name, "exe": exe, "run": run, "list": lst, "list_kind": "lines" if lst else None,
              "model_flag": flags["model_flag"], "effort_flag": flags["effort_flag"], "cwd_flag": flags["cwd_flag"],
              "plan": plan, "tokens_regex": rx, "approvals_off_reason": obj.get("approvals_off_reason"),
              "notes": obj.get("notes"), "bypass_args": [], "learned": True}
    driver.update(sig)
    return driver, []


# ---------------------------------------------------------------- learned drivers: the store


def drivers_path():
    return paths.data_file("worker-drivers.json")


def load_drivers():
    d = _load(drivers_path()).get("drivers")
    return {k: v for k, v in d.items() if isinstance(v, dict) and isinstance(v.get("driver"), dict)} if isinstance(d, dict) else {}


def save_drivers(drivers):
    _save(drivers_path(), {"drivers": drivers})


def driver_for(name):
    """The learned driver NAME may run, or None: only a usable one (verified by its smoke task, and
    approved by the owner when it switches off approvals) is ever run."""
    rec = load_drivers().get(name or "")
    return rec["driver"] if rec and rec.get("state") == "usable" else None


STATE_WORDS = {"usable": None, "waiting-owner": "waiting for the owner: `sisi approve drv-%s`",
               "unverified": "learned but not yet proved by its smoke task", "failed": "its smoke task failed"}


def learned_tools(which=None):
    """Discovery entries for the learned drivers, from the store alone (no tool is run)."""
    import shutil
    which = which or shutil.which
    out = []
    for name, rec in sorted(load_drivers().items()):
        d = rec["driver"]
        path = which(d.get("exe") or "")
        state = rec.get("state")
        why = STATE_WORDS.get(state)
        why = (why % name if why and "%s" in why else why)
        if why and rec.get("reason"):
            why = "%s (%s)" % (why, rec["reason"])
        plan = "flat" if d.get("plan") in ("free", "flat") else d.get("plan")
        out.append({"name": name, "installed": bool(path), "path": path, "usable": state == "usable" and bool(path),
                    "reason": why, "models": [m for m in rec.get("models") or [] if isinstance(m, str)],
                    "learned_by_use": not d.get("list"), "plan": plan, "with_default": True,
                    "learned": {"by": rec.get("learned_by"), "at": rec.get("learned_at"), "state": state,
                                "free": d.get("plan") == "free"}})
    return out


def merge_tools(tools):
    """The discovered tools plus the learned drivers and the host's providers. Built-in tools win a name."""
    have = {t.get("name") for t in tools}
    extra = [t for t in learned_tools() + host_tools() if t["name"] not in have]
    return list(tools) + extra


def tool_lines(t):
    """Extra lines for `sisi workers` under one tool: who learned it, or how the host reaches it."""
    if t.get("learned"):
        info = t["learned"]
        return ["  learned by %s on %s (%s); `sisi workers forget %s` removes it"
                % (info.get("by") or "an unknown worker", _day(info.get("at")), info.get("state"), t["name"])] + provider_lines(t)
    if t.get("host"):
        h = t["host"]
        return ["  reached through the host's cross-provider delegation (first seen %s); new workers are unproven: "
                "routine work only until judged" % _day(h.get("first_seen"))] + provider_lines(t)
    return provider_lines(t)


# ---------------------------------------------------------------- running a learned tool once


def _valid_name(name):
    return isinstance(name, str) and bool(_NAME.match(name))


def smoke(driver, timeout=None):
    """Run ONE tiny read-only task through a driver, in a temporary folder, with a time limit and no
    input. Returns {"ok", "kind", "note", "output", "seconds"}; kind is ok, login, quota, error, timeout,
    bad-template or no-answer. The command is an argument list: the brief never reaches a shell."""
    import shutil, subprocess, tempfile, uuid
    from . import workers
    timeout = float(conf()["smoke_timeout_s"] if timeout is None else timeout)
    nonce = "ok" + uuid.uuid4().hex[:8]
    tmp = tempfile.mkdtemp(prefix="sisi-smoke-")
    cmd = workers.build_command(driver, {"model": None, "worker": driver["name"] + "/default"},
                                SMOKE_PROMPT % nonce, tmp, 1)
    started = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=tmp, stdin=subprocess.DEVNULL,
                           env=dict(os.environ, SISI_WORKER_RUN="1"))
        rc, out, err = r.returncode, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired as e:
        txt = lambda v: v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        return {"ok": False, "kind": "timeout", "output": (txt(e.stdout) + txt(e.stderr))[-600:], "seconds": timeout,
                "note": "did not finish within %gs; it may be waiting for a question it cannot be asked "
                        "(a login, an approval)" % timeout}
    except OSError as e:
        return {"ok": False, "kind": "error", "output": "", "seconds": 0.0, "note": "could not start it: %s" % e}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    text = out + "\n" + err
    res = {"output": " ".join(text.split())[:600], "seconds": round(time.time() - started, 1)}
    fail = workers.classify_failure(text, rc, extra_signatures(driver))
    if fail is not None:
        kind = {"auth": "login", "limit": "quota"}.get(fail[0], "error")
        return dict(res, ok=False, kind=kind, note=fail[1])
    if rc != 0:
        bad = bool(USAGE_WORDS.search(text))
        return dict(res, ok=False, kind="bad-template" if bad else "error",
                    note=("it rejected the command line" if bad else "it exited with status %s" % rc))
    if nonce not in text:
        return dict(res, ok=False, kind="no-answer", note="it ran but did not answer the smoke prompt "
                    "(the template may not run a task without interaction)")
    return dict(res, ok=True, kind="ok", note="answered the smoke prompt")


def extra_signatures(driver):
    """The failure phrases a learned driver adds ({} for a built-in one)."""
    d = driver or {}
    return {"auth": d.get("auth_signatures") or [], "limit": d.get("limit_signatures") or []}


def tokens_from(driver, text):
    """Total tokens a learned tool prints, by the driver's own regular expression, else None."""
    rx = (driver or {}).get("tokens_regex")
    if not rx:
        return None
    try:
        m = re.search(rx, (text or "")[-200000:])
        return int(m.group(1).replace(",", "")) if m else None
    except (re.error, ValueError, IndexError):
        return None


def held_note(cand):
    """For a candidate whose learned driver may not run yet: why not (never run, never marked missing)."""
    rec = load_drivers().get(cand.get("tool") or "")
    if rec is None or rec.get("state") == "usable":
        return None
    return "%s is held: its learned driver is not usable yet (%s); trying the next choice" % (
        cand["worker"], rec.get("reason") or STATE_WORDS.get(rec.get("state")) or rec.get("state"))


def models_of(driver, timeout=30):
    """The model names a learned tool lists (its own list command, run once), or []."""
    import subprocess
    from . import workers
    if not driver.get("list"):
        return []
    try:
        r = subprocess.run(driver["list"], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    # a tool may print a progress line before the list: only a token shaped like an id (a digit or - _ . / :) counts
    return [m for m in workers._parse_models({"list_kind": "lines"}, r.stdout or "") if re.search(r"[-_./:\d]", m)][:500]


def prove(name, drivers, now=None):
    """Run the smoke task for a stored driver and record what happened. Returns the smoke result."""
    from . import workers
    rec = drivers[name]
    res = smoke(rec["driver"])
    now = time.time() if now is None else now
    rec["smoke"] = {"at": now, "kind": res["kind"], "note": res["note"], "output": res["output"]}
    if res["ok"]:
        rec.update(state="usable", reason=None, verified_at=now, models=models_of(rec["driver"]))
        workers.clear_down(name)
    elif res["kind"] in ("login", "quota", "error"):
        rec.update(state="unverified", reason="%s: %s" % (res["kind"], res["note"]))
    else:
        rec.update(state="failed", reason="%s: %s" % (res["kind"], res["note"]))
    save_drivers(drivers)
    return res


def describe_driver(name, rec):
    d = rec["driver"]
    lines = ["%s: waiting for the owner" % ("drv-" + name),
             "  the tool %s was learned by %s on %s; it runs the brief of every task through this command"
             % (name, rec.get("learned_by") or "an unknown worker", _day(rec.get("learned_at"))),
             "  COMMAND (an argument list, run without a shell; {prompt} is the task's brief): %s" % " ".join(d["run"]),
             "  switches off approvals or a sandbox: %s" % " ".join(rec.get("bypass") or []),
             "  the worker's reason: %s" % (d.get("approvals_off_reason") or "none stated"),
             "  until approved it never runs, its one smoke task included"]
    return lines


def record(name, path, by=None, now=None):
    """`sisi workers learn NAME --record FILE`: validate, store as unverified, and prove it with one smoke
    task, unless it switches off approvals, in which case it waits for the owner. Returns (exit code, lines)."""
    import shutil
    from . import workers
    now = time.time() if now is None else now
    try:
        if os.path.getsize(path) > 20000:
            return 1, ["sisi workers learn: the driver file is larger than 20000 bytes"]
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError) as e:
        return 1, ["sisi workers learn: cannot read %s as JSON: %s" % (path, e)]
    driver, problems = validate_driver(obj, shutil.which, {d["name"] for d in workers.DRIVERS} | {d["exe"] for d in workers.DRIVERS})
    if driver is None:
        return 1, ["sisi workers learn: the driver file is not valid:"] + ["  - " + p for p in problems]
    if driver["name"] != name or driver["exe"] != name:
        return 1, ["sisi workers learn: the file's name and exe must both be %r, the tool the brief was written for" % name]
    drivers = load_drivers()
    flags = bypass_args(driver["run"] + (driver["list"] or []))
    rec = {"driver": driver, "state": "unverified", "reason": None, "learned_by": by or store.tool() or "an unknown worker",
           "learned_at": now, "bypass": flags, "models": []}
    drivers[name] = rec
    if flags:
        rec.update(state="waiting-owner", reason="it switches off approvals or a sandbox (%s)" % " ".join(flags))
        save_drivers(drivers)
        return 0, ["driver %s stored, WAITING FOR THE OWNER: its command has %s." % (name, " ".join(flags))] + \
            describe_driver(name, rec) + ["The owner decides, in a terminal: sisi approve drv-%s --yes | --no" % name]
    save_drivers(drivers)
    res = prove(name, drivers, now)
    lines = ["driver %s stored; smoke task: %s" % (name, "PASSED, the driver is usable" if res["ok"] else
                                                      "FAILED (%s): %s" % (res["kind"], res["note"]))]
    if res["output"]:
        lines.append("the tool printed: %s" % res["output"])
    if not res["ok"]:
        lines.append("the driver stays unusable (%s). Fix the file and run `sisi workers learn %s --record FILE` again%s."
                     % (drivers[name]["reason"], name, ", or log the tool in and run `sisi workers learn %s --verify`" % name
                        if res["kind"] in ("login", "quota") else ""))
    return (0 if res["ok"] else 1), lines


def verify(name):
    drivers = load_drivers()
    rec = drivers.get(name)
    if rec is None:
        return 1, ["sisi workers learn: no stored driver %r (see `sisi workers`)" % name]
    if rec.get("state") == "waiting-owner":
        return 1, ["sisi workers learn: %s waits for the owner (`sisi approve drv-%s`); it is not run before" % (name, name)]
    res = prove(name, drivers)
    return (0 if res["ok"] else 1), ["smoke task for %s: %s" % (name, "PASSED, usable" if res["ok"] else
                                                               "FAILED (%s): %s" % (res["kind"], res["note"]))]


def forget(name):
    """`sisi workers forget NAME`: remove a learned driver, or a provider the host listed."""
    drivers = load_drivers()
    if name in drivers:
        del drivers[name]
        save_drivers(drivers)
        return 0, ["forgot the learned driver %s" % name]
    f = host_state_file()
    state = _load(f)
    hit = [h for h, r in (state.get("hosts") or {}).items() if name in (r.get("providers") or {})]
    for h in hit:
        del state["hosts"][h]["providers"][name]
    if hit:
        _save(f, state)
        return 0, ["forgot the host provider %s (it returns when the host lists it again)" % name]
    return 1, ["sisi workers forget: %r is neither a learned tool nor a host provider" % name]


# ---------------------------------------------------------------- the owner's approval of a waiting driver


def waiting_drivers():
    return {n: r for n, r in load_drivers().items() if r.get("state") == "waiting-owner"}


def waiting_decisions():
    """What waits for the owner here, as `sisi approve` lists and decides it: one dict per learned driver
    (`drv-NAME`) and per allowance probe (`probe-PROVIDER`) with {"id", "kind", "lines" (the full action),
    "action" (a short record of it for the approvals log), "apply" (a function of yes, True or False, returning
    (exit code, text))}. The ask itself (the full action shown, the random word typed back at the terminal, the
    refusals recorded) is cycle.cmd_approve's, the same for every kind; this module only says what is waiting
    and what each decision does."""
    out = []
    for n, r in sorted(waiting_drivers().items()):
        out.append({"id": "drv-" + n, "kind": "driver", "lines": describe_driver(n, r),
                    "action": {"action": "approve-driver", "tool": n, "command": list(r["driver"]["run"]),
                               "bypass": list(r.get("bypass") or [])},
                    "apply": (lambda yes, n=n: _decide_driver(n, yes))})
    for n, d in sorted(waiting_probes().items()):
        out.append({"id": "probe-" + n, "kind": "probe", "lines": describe_probe(n, d),
                    "action": {"action": "approve-probe", "provider": n,
                               "command": d.get("command") or d.get("secret_command"), "url": d.get("url")},
                    "apply": (lambda yes, n=n: _decide_probe(n, yes))})
    return out


def waiting_count():
    return len(waiting_drivers()) + len(waiting_probes())


def _decide_probe(name, yes):
    provs = load_providers()
    if not isinstance(provs.get(name, {}).get("allowance"), dict):
        return 2, "sisi approve: nothing named probe-%s waits for a decision" % name
    if not yes:
        provs[name].pop("allowance", None)
        save_providers(provs)
        return 0, "probe-%s refused; the probe was removed" % name
    provs[name]["allowance"]["state"] = "usable"
    save_providers(provs)
    return 0, "probe-%s approved; it is read when `sisi workers` is asked and when routing needs it" % name


def _decide_driver(name, yes):
    if not yes:
        forget(name)
        return 0, "drv-%s refused; the driver was removed" % name
    drivers = load_drivers()
    if name not in drivers:
        return 2, "sisi approve: nothing named drv-%s waits for a decision" % name
    drivers[name]["state"] = "unverified"
    drivers[name]["approved_at"] = time.time()
    save_drivers(drivers)
    res = prove(name, drivers)
    return (0 if res["ok"] else 1), "drv-%s approved. Smoke task: %s" % (
        name, "PASSED, the driver is usable" if res["ok"] else "FAILED (%s): %s" % (res["kind"], res["note"]))


# ---------------------------------------------------------------- the brief for a cheap worker


def learn_brief(name, exe_path):
    help_ = data().get("driver_format_help") or {}
    fields = "\n".join("  %s: %s" % (k, help_[k]) for k in DRIVER_FIELDS if k in help_)
    return "\n".join([
        "You are a worker. Do this task yourself; do not delegate it further.",
        "",
        "## Outcome and scope",
        "Teach sisi to run the command-line AI tool `%s` (at %s) as a worker: write ONE small JSON file, a driver, "
        "that says how to run a single task through it without interaction. Out of scope: running real tasks, "
        "logging in, changing the tool's settings, installing anything." % (name, exe_path),
        "",
        "## Context and sources of truth",
        "The tool's own help output is the only source. Run `%s --help` and `%s help SUBCOMMAND` for what it shows. "
        "Find: how to run one task without interaction (a print or exec mode, the prompt as an argument); how to choose a "
        "model; how to list models (only if help shows a list command); how to set the working folder; where it reports "
        "token usage; what its login, quota and rate-limit errors say (quote the phrases help shows; do not provoke them); "
        "whether it is free, a flat subscription or billed per use. Driver fields:\n%s" % (name, name, fields),
        "",
        "## Constraints and interfaces",
        "Run only commands that print help, a version or a list. Never start a task, log in or log out, or change a setting.",
        "The command is run without a shell, as an argument list; the whole token {prompt} is where the brief goes.",
        "Never include a flag that switches off approvals or a sandbox unless the tool cannot run without one; then say "
        "why in approvals_off_reason. Such a driver waits for the owner and is not run before they approve it.",
        "If the tool cannot run a task without interaction, or needs a login that is not done, write no file and "
        "report exactly what it printed.",
        "",
        "## Acceptance",
        "`sisi workers learn %s --check FILE` prints `valid`. Every field you set is traced in your report to a line "
        "of the tool's help (quote it); a field you could not trace is null." % name,
        "",
        "## Deliverables and report format",
        "The driver file (JSON) at FILE in the folder you were given, and a short report: each field with the help line "
        "behind it, what you could not find, and the output of the record command below.",
        "",
        "## Files you may change",
        "Only the one driver file, FILE. Everything else is read-only.",
        "",
        "## Verification",
        "Run `sisi workers learn %s --record FILE`. It validates the file, stores it, and runs one tiny read-only smoke task "
        "through the tool (a temporary folder, a time limit). Paste its output in your report. If it says the driver is "
        "unusable, say why and do not retry more than once." % name,
        "",
        "## Budget and escalation",
        "About ten help commands and fifteen minutes. Stop and report instead of guessing when help does not answer a field.",
        ""])


USAGE = ("usage: sisi workers learn NAME                     print the brief for a cheap worker that learns the tool\n"
         "       sisi workers learn NAME --check FILE       validate a driver file, change nothing\n"
         "       sisi workers learn NAME --record FILE [--by TEXT]   validate, store, run one smoke task\n"
         "       sisi workers learn NAME --verify           run the smoke task again for a stored driver\n"
         "       sisi workers forget NAME                   remove a learned driver or a host provider")


def _opt(args, name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def cmd_learn(args):
    import shutil
    from . import workers
    args = list(args)
    name = args[0] if args and not args[0].startswith("-") else None
    if not _valid_name(name):
        print(USAGE)
        return 1
    if "--record" in args or "--check" in args:
        path = _opt(args, "--record") or _opt(args, "--check")
        if not path:
            print(USAGE)
            return 1
        if "--check" in args:
            try:
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
            except (OSError, ValueError) as e:
                print("sisi workers learn: cannot read %s as JSON: %s" % (path, e))
                return 1
            driver, problems = validate_driver(obj, shutil.which, {d["name"] for d in workers.DRIVERS})
            if driver is None or driver["name"] != name:
                print("\n".join(["not valid:"] + ["  - " + p for p in (problems or ["the file's name is not %r" % name])]))
                return 1
            flags = bypass_args(driver["run"] + (driver["list"] or []))
            print("valid" + (" (it switches off approvals or a sandbox with %s: it will wait for the owner)" % " ".join(flags)
                             if flags else ""))
            return 0
        code, lines = record(name, path, by=_opt(args, "--by"))
    elif "--verify" in args:
        code, lines = verify(name)
    else:
        exe = shutil.which(name)
        if not exe:
            print("sisi workers learn: %r is not on PATH" % name)
            return 1
        print(learn_brief(name, exe))
        return 0
    print("\n".join(lines))
    return code


def cmd_forget(args):
    if not args or not _valid_name(args[0]):
        print(USAGE)
        return 1
    code, lines = forget(args[0])
    print("\n".join(lines))
    return code


# ---------------------------------------------------------------- routing: new workers are unproven


def judged_counts(records):
    """{worker id, lower case: judged attempts} from the delegation record."""
    out = {}
    for r in records:
        if r.get("kind") == "attempt" and r.get("worker"):
            k = str(r["worker"]).lower()
            out[k] = out.get(k, 0) + 1
    return out


def annotate(cands, records, tools):
    """Mark the candidates that came from a learned driver or from the host: unproven until they have
    judged attempts (routing.MIN_ATTEMPTS), and a candidate to try (`unproven_ok`) when the tool's own
    default model, or when its provider lists no more than discovery.catalogue_over models. An unknown
    plan counts as per-use. A host worker is started by the host, so its mechanism says how. Also for every
    candidate: the plan its provider has (a provider fact; a model's own price fact still wins), and the
    owner's vouch, which lifts an unproven worker to the vouched difficulty until it has its own record."""
    marked = {t["name"]: t for t in tools if t.get("learned") or t.get("host")}
    providers, vouches = load_providers(), load_vouches()
    if not (marked or providers or vouches):
        return cands
    from . import routing
    counts = judged_counts(records)
    cap = conf()["catalogue_over"]
    prices = None
    for c in cands:
        n = counts.get(c["worker"].lower(), 0)
        prov = routing.provider_of(c["worker"])
        pf = providers.get(prov) if prov else None
        if pf and pf.get("plan"):
            if prices is None:
                from . import workers
                prices = workers.load_prices()
            from . import workers as _w
            if not _w._price_for(prices, c.get("tool"), c.get("model"), c["worker"]).get("plan"):
                c["plan"] = "per-use" if pf["plan"] == "per-use" else "flat"
        if c.get("plan") == "free":
            c["plan"] = "flat"
        v = vouches.get(c["worker"].lower())
        if v and n < routing.MIN_ATTEMPTS:  # once it has its own thick record, the record decides
            level = min(int(v.get("up_to") or 0), 2 if v.get("relayed") else 3)
            if level > 0:
                c["vouch"] = {"level": level, "why": v.get("why"), "date": v.get("date"), "relayed": bool(v.get("relayed"))}
                c["unproven"] = True
                c["unproven_ok"] = True
        t = marked.get(c.get("tool"))
        if t is None:
            continue
        c["unproven"] = n < routing.MIN_ATTEMPTS
        if c["unproven"]:
            c["plan"] = c.get("plan") or "per-use"
            if c.get("usable", True) and (c.get("model") is None or len(t.get("models") or []) <= cap):
                c["unproven_ok"] = True
        if t.get("host"):
            c["host_native"] = True
            c["host_mechanism"] = host_mechanism(t, c["worker"])
    return cands


def facts_targets(cands):
    """The worker ids to research: candidates to try that have no price and no standing yet."""
    return [c["worker"] for c in cands if c.get("unproven_ok") and not c.get("price_source") and c.get("standing") is None]


def facts_phrase(targets):
    shown = targets[:MAX_NAMED]
    return "the new workers %s%s" % (", ".join(shown), " and %d more" % (len(targets) - len(shown)) if len(targets) > len(shown) else "")


UNPROVEN_LINE = ("unproven: check this result with at least the tests or a read of the diff "
                 "(a new worker with no judged record; routine work only until it has one)")


def unproven_lines(cand):
    return [UNPROVEN_LINE] if cand and cand.get("unproven") else []


# ---------------------------------------------------------------- providers: plan, allowance, failure phrases; the owner's vouch
# One tool can carry several providers (the part of a worker id before the first slash), each with its own
# plan, allowance and failure phrases. They are facts in the user store, set by command (R-12-1, R-7.2-3).

_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")
PLANS = ("flat", "free", "per-use")
SIGNATURE_CLASSES = ("auth", "limit", "missing", "error")


def providers_path():
    return paths.data_file("worker-providers.json")


def load_providers():
    d = _load(providers_path()).get("providers")
    return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}


def save_providers(providers):
    _save(providers_path(), {"providers": providers})


def vouches_path():
    return paths.data_file("worker-vouches.json")


def load_vouches():
    d = _load(vouches_path()).get("vouches")
    return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}


def save_vouches(vouches):
    _save(vouches_path(), {"vouches": vouches})


# ---- a small path language over JSON: name, .name, [n], [*], [key=value], or `re:REGEX` over raw text

_PATH_TOKEN = re.compile(r"\.?([A-Za-z_][\w-]*)|\[([^\]]*)\]")


def path_values(obj, path):
    """The values a path finds in parsed JSON (or in raw text, for a path starting `re:`: the first group of every match)."""
    path = str(path or "")
    if path.startswith("re:"):
        text = obj if isinstance(obj, str) else json.dumps(obj)
        return [m.group(1) for m in re.finditer(path[3:], text[-200000:]) if m.groups()]
    cur, pos = [obj], 0
    for m in _PATH_TOKEN.finditer(path):
        if m.start() != pos:
            raise ValueError("cannot read the path at %r" % path[pos:pos + 10])
        pos = m.end()
        name, br = m.group(1), m.group(2)
        nxt = []
        for item in cur:
            if name is not None:
                if isinstance(item, dict) and name in item:
                    nxt.append(item[name])
            elif br == "*":
                nxt.extend(item if isinstance(item, list) else [])
            elif br.isdigit():
                if isinstance(item, list) and int(br) < len(item):
                    nxt.append(item[int(br)])
            elif "=" in br:
                key, want = br.split("=", 1)
                for x in (item if isinstance(item, list) else [item]):
                    got = x.get(key) if isinstance(x, dict) else None
                    got = "true" if got is True else "false" if got is False else got
                    if got is not None and str(got) == want:
                        nxt.append(x)
        cur = nxt
    if pos != len(path) or not path:
        raise ValueError("cannot read the path %r" % path[:40])
    return cur


def time_value(v):
    """Epoch seconds from a number (seconds or milliseconds) or a date text, else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str) and re.match(r"^\d+(\.\d+)?$", v.strip()):
        v = float(v)
    if isinstance(v, (int, float)):
        return float(v) / 1000.0 if v > 1e11 else float(v)
    if isinstance(v, str):
        from . import workers
        return workers._parse_time(v)
    return None


def _json_in(text):
    """The first JSON object a tool's output holds (the whole text, a line, or the outermost braces), or None."""
    text = (text or "").strip()
    tries = [text] + [ln.strip() for ln in text.splitlines() if ln.strip().startswith("{")]
    if "{" in text and "}" in text:
        tries.append(text[text.index("{"):text.rindex("}") + 1])
    for cand in tries:
        try:
            d = json.loads(cand)
            if isinstance(d, (dict, list)):
                return d
        except ValueError:
            pass
    return None


# ---- commands: plan, vouch, allowance, signature


def _flags(args, valued, boolean=()):
    """(positionals, {flag: value}, {boolean flags set}, unknown flags) from an argument list."""
    pos, vals, bools, unknown = [], {}, set(), []
    i = 0
    while i < len(args):
        a = args[i]
        if a in valued and i + 1 < len(args):
            vals[a] = args[i + 1]
            i += 2
            continue
        if a in boolean:
            bools.add(a)
        elif a.startswith("--"):
            unknown.append(a)
        else:
            pos.append(a)
        i += 1
    return pos, vals, bools, unknown


PROVIDER_USAGE = (
    "usage: sisi workers plan PROVIDER flat|free|per-use --source S [--note TEXT]   how routing costs the provider's workers\n"
    "       sisi workers vouch WORKER --up-to 1|2|3 --why \"TEXT\" | --remove   the owner's word that a worker handles up to that difficulty\n"
    "       sisi workers allowance PROVIDER --url URL --header 'Name={secret}' --secret-from-command CMD --secret-path PATH\n"
    "               --remaining-path PATH --reset-path PATH [--total-path PATH]  (or --command CMD, no secret) | --remove\n"
    "       sisi workers signature PROVIDER --match 'TEXT or re:REGEX' --class auth|limit|missing|error [--until-path PATH] | --remove")


def cmd_provider(args):
    sub, rest = args[0], list(args[1:])
    try:
        return {"plan": _cmd_plan, "vouch": _cmd_vouch, "allowance": _cmd_allowance, "signature": _cmd_signature}[sub](rest)
    except (ValueError, re.error) as e:
        print("sisi workers %s: %s" % (sub, e))
        return 1


def _need_provider(name):
    if not isinstance(name, str) or not _PROVIDER.match(name.lower()):
        raise ValueError("a provider is the part of a worker id before its first slash (letters, digits, dot, dash)")
    return name.lower()


def _cmd_plan(args):
    pos, v, b, bad = _flags(args, ("--note", "--source"), ("--remove",))
    if bad or not pos:
        print(PROVIDER_USAGE)
        return 1
    prov = _need_provider(pos[0])
    provs = load_providers()
    if "--remove" in b:
        if prov in provs:
            for k in ("plan", "note", "source", "date"):
                provs[prov].pop(k, None)
            save_providers(provs)
        print("plan fact for %s removed" % prov)
        return 0
    if len(pos) != 2 or pos[1] not in PLANS or not v.get("--source"):
        raise ValueError("a plan is flat, free or per-use, and a fact needs its --source (nothing recorded)")
    entry = provs.setdefault(prov, {})
    entry.update(plan=pos[1], source=v["--source"][:200], date=time.strftime("%Y-%m-%d"))
    if v.get("--note"):
        entry["note"] = v["--note"][:300]
    save_providers(provs)
    print("recorded the plan of provider %s: %s%s (from %s). %s" % (
        prov, pos[1], " (%s)" % entry["note"] if entry.get("note") else "", entry["source"],
        "A flat or free plan with allowance left costs nothing extra per task; a model's own price fact is a "
        "relative cost inside the plan." if pos[1] != "per-use" else "Billed per use."))
    return 0


def _cmd_vouch(args):
    pos, v, b, bad = _flags(args, ("--up-to", "--why"), ("--remove",))
    vouches = load_vouches()
    if bad or not pos:
        for ln in vouch_lines():
            print(ln)
        if not vouches:
            print(PROVIDER_USAGE.split("\n")[1])
        return 0 if not bad else 1
    worker = pos[0].lower()
    if "--remove" in b:
        vouches.pop(worker, None)
        save_vouches(vouches)
        print("vouch for %s removed" % worker)
        return 0
    up = v.get("--up-to")
    if up not in ("1", "2", "3") or not (v.get("--why") or "").strip():
        raise ValueError("--up-to wants 1, 2 or 3, and --why wants the owner's own words, quoted")
    from . import learning
    origin = learning.statement_origin(v["--why"])
    relayed = origin != "typed by the owner"
    vouches[worker] = {"up_to": int(up), "why": v["--why"].strip()[:400], "origin": origin, "relayed": relayed,
                       "date": time.strftime("%Y-%m-%d")}
    save_vouches(vouches)
    print("vouched for %s up to difficulty %s (%s)%s" % (
        worker, up, origin, ": counted only up to difficulty 2, because the quoted words were not found in a message "
        "the owner typed" if relayed and int(up) > 2 else ""))
    print("It is treated as capable up to that difficulty (`sisi route --explain` says \"the owner's word\"), checked a level "
          "more carefully, until it has its own judged record; a thick bad record overrides it.")
    return 0


def vouch_lines():
    out = []
    counts = None
    for w, v in sorted(load_vouches().items()):
        if counts is None:
            from . import workers
            counts = judged_counts(workers.read_records())
        from . import routing
        ignored = counts.get(w, 0) >= routing.MIN_ATTEMPTS
        out.append("Vouched: %s up to difficulty %s by the owner's word (%s, %s: %s)%s" % (
            w, v.get("up_to"), v.get("origin") or "origin unknown", v.get("date") or "no date",
            (v.get("why") or "")[:100], "; ignored now: its own record decides" if ignored else
            ("; counted up to difficulty 2 only" if v.get("relayed") and int(v.get("up_to") or 0) > 2 else "")))
    return out


def _url_ok(url):
    from urllib.parse import urlsplit
    sp = urlsplit(url)
    return (sp.scheme == "https" or (sp.scheme == "http" and sp.hostname in ("localhost", "127.0.0.1", "::1"))) \
        and bool(sp.hostname) and "{secret}" not in url and not sp.username


def _cmd_allowance(args):
    valued = ("--url", "--header", "--secret-from-command", "--secret-path", "--remaining-path", "--reset-path",
              "--total-path", "--command")
    pos, v, b, bad = _flags(args, valued, ("--remove",))
    provs = load_providers()
    if bad or not pos:
        for p, e in sorted(provs.items()):
            if e.get("allowance"):
                print("\n".join(describe_probe(p, e["allowance"])))
        print(PROVIDER_USAGE.split("\n")[2])
        return 0 if not bad else 1
    prov = _need_provider(pos[0])
    if "--remove" in b:
        provs.get(prov, {}).pop("allowance", None)
        save_providers(provs)
        print("allowance probe for %s removed" % prov)
        return 0
    for need in ("--remaining-path", "--reset-path"):
        if not v.get(need):
            raise ValueError("%s is required" % need)
    defn = {"remaining_path": v["--remaining-path"], "reset_path": v["--reset-path"]}
    paths_to_check = [defn["remaining_path"], defn["reset_path"]]
    if v.get("--total-path"):
        defn["total_path"] = v["--total-path"]
        paths_to_check.append(v["--total-path"])
    if v.get("--command"):
        if v.get("--url") or v.get("--secret-from-command"):
            raise ValueError("--command (a tool that prints its own allowance) takes no --url or secret")
        if not shlex.split(v["--command"]):
            raise ValueError("--command is empty")
        defn["command"] = v["--command"]
    else:
        if not v.get("--url") or not _url_ok(v["--url"]):
            raise ValueError("--url must be an https address (no key inside it); a plain http address only for this machine")
        header = v.get("--header") or ""
        name, _eq, value = header.partition("=")
        if not re.match(r"^[A-Za-z][A-Za-z0-9-]{0,40}$", name) or "{secret}" not in value or "\n" in value:
            raise ValueError("--header is Name={secret} (the key is put where {secret} stands, at probe time)")
        if not v.get("--secret-from-command") or not shlex.split(v["--secret-from-command"]) or not v.get("--secret-path"):
            raise ValueError("--secret-from-command and --secret-path say where the key comes from; it is never stored")
        defn.update(url=v["--url"], header=header, secret_command=v["--secret-from-command"], secret_path=v["--secret-path"])
        paths_to_check.append(v["--secret-path"])
    for pth in paths_to_check:
        if pth.startswith("re:"):
            re.compile(pth[3:])
        else:
            path_values({}, pth)  # raises ValueError for a path it cannot read
    defn["state"] = "waiting-owner"  # a probe runs a command or sends a request with a key: only the owner's decision lets it
    defn["defined"] = time.strftime("%Y-%m-%d")
    provs.setdefault(prov, {})["allowance"] = defn
    save_providers(provs)
    print("\n".join(describe_probe(prov, defn)))
    if defn["state"] != "usable":
        print("The probe is stored but not used until the owner decides, in a terminal: sisi approve probe-%s --yes | --no" % prov)
    return 0


def waiting_probes():
    return {p: e["allowance"] for p, e in load_providers().items()
            if isinstance(e.get("allowance"), dict) and e["allowance"].get("state") == "waiting-owner"}


def describe_probe(prov, d):
    lines = ["%sprobe-%s: an allowance probe for provider %s" % ("" if d.get("state") == "usable" else "WAITING FOR THE OWNER: ", prov, prov)]
    if d.get("command"):
        lines.append("  runs (an argument list, no shell): %s" % d["command"])
    else:
        lines += ["  sends one GET to %s with the header %s" % (d["url"], d["header"].partition("=")[0]),
                  "  the key is read when the probe runs, by running (no shell): %s, taking %s" % (d["secret_command"], d["secret_path"]),
                  "  the key is used for that one request and is never stored or printed; a redirect is never followed"]
    lines.append("  reads remaining from %s and the reset time from %s%s" % (
        d["remaining_path"], d["reset_path"], ", total from %s" % d["total_path"] if d.get("total_path") else ""))
    return lines


def _cmd_signature(args):
    pos, v, b, bad = _flags(args, ("--match", "--class", "--until-path"), ("--remove",))
    if bad or not pos:
        for p, e in sorted(load_providers().items()):
            for sg in e.get("signatures") or []:
                print("%s: %r is %s%s" % (p, sg["match"], sg["class"], " (reset from %s)" % sg["until_path"] if sg.get("until_path") else ""))
        print(PROVIDER_USAGE.split("\n")[4])
        return 0 if not bad else 1
    prov = _need_provider(pos[0])
    provs = load_providers()
    entry = provs.setdefault(prov, {})
    sigs = [x for x in entry.get("signatures") or [] if isinstance(x, dict)]
    match = (v.get("--match") or "").strip()
    if not 4 <= len(match) <= 120:
        raise ValueError("--match is a phrase or re:REGEX of 4 to 120 characters")
    if "--remove" in b:
        entry["signatures"] = [x for x in sigs if x["match"] != match]
        save_providers(provs)
        print("signature removed")
        return 0
    if v.get("--class") not in SIGNATURE_CLASSES:
        raise ValueError("--class is auth, limit, missing or error")
    if match.startswith("re:"):
        re.compile(match[3:])
    sig = {"match": match, "class": v["--class"]}
    if v.get("--until-path"):
        if v["--until-path"].startswith("re:"):
            re.compile(v["--until-path"][3:])
        else:
            path_values({}, v["--until-path"])
        sig["until_path"] = v["--until-path"]
    entry["signatures"] = [x for x in sigs if x["match"] != match] + [sig]
    save_providers(provs)
    print("provider %s: output matching %r is now classified %s, before the built-in phrases" % (prov, match, sig["class"]))
    return 0


# ---- failures by a provider's own phrases


def provider_failure(cand, text):
    """(reason, note, retry_after_s) when one of the worker's provider's recorded phrases is in the output, else None.
    Consulted before the built-in classifier: a provider's own error code can be an auth problem and not a limit."""
    from . import routing
    prov = routing.provider_of(cand.get("worker"))
    sigs = (load_providers().get(prov) or {}).get("signatures") if prov else None
    low = (text or "").lower()
    for sg in sigs or []:
        m = sg.get("match") or ""
        try:
            hit = bool(re.search(m[3:], text or "")) if m.startswith("re:") else m.lower() in low
        except re.error:
            hit = False
        if not hit:
            continue
        retry = None
        if sg.get("until_path"):
            try:
                found = path_values(_json_in(text) if not sg["until_path"].startswith("re:") else text, sg["until_path"])
                at = next((t for t in (time_value(x) for x in found) if t), None)
                retry = max(60.0, at - time.time()) if at else None
            except ValueError:
                pass
        return sg["class"], "%s's own failure phrase %r" % (prov, m[:60]), retry
    return None


# ---- allowance probes


class ProbeError(Exception):
    """Carries a message that is safe to show: never text from the tool or server, never the key."""


def _secret_of(d):
    import subprocess
    try:
        r = subprocess.run(shlex.split(d["secret_command"]), capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ProbeError("the secret command could not be run")
    if r.returncode != 0:
        raise ProbeError("the secret command exited with status %d" % r.returncode)
    out = r.stdout or ""
    try:
        found = path_values(_json_in(out) if not d["secret_path"].startswith("re:") else out, d["secret_path"])
    except ValueError:
        raise ProbeError("the secret path cannot be read")
    key = next((x for x in found if isinstance(x, str) and 8 <= len(x) <= 4096 and x.isprintable()), None)
    if key is None:
        raise ProbeError("the secret path found no key in the command's output")
    return key


def _fetch(d, secret):
    """The text a probe reads: a tool's own output, or one GET (no redirects: the handler's redirect_request answers
    None, so a 3xx is an error; a short timeout; a size limit)."""
    import subprocess
    if d.get("command"):
        try:
            r = subprocess.run(shlex.split(d["command"]), capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ProbeError("the allowance command could not be run")
        if r.returncode != 0:
            raise ProbeError("the allowance command exited with status %d" % r.returncode)
        return r.stdout or ""
    import urllib.error, urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None  # a redirect would carry the key to a place the owner never named

    name, _eq, value = d["header"].partition("=")
    req = urllib.request.Request(d["url"], headers={name: value.replace("{secret}", secret), "Accept": "application/json",
                                                    "User-Agent": "sisi-allowance-probe"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=conf()["allowance_timeout_s"]) as resp:
            return resp.read(1000000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ProbeError("the server answered HTTP %d%s" % (e.code, " (a redirect, which is never followed)" if 300 <= e.code < 400 else ""))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ProbeError("the request failed (%s)" % type(e).__name__)


def probe_once(d):
    """One reading from a probe definition: [{remaining, reset, total}] windows. Raises ProbeError."""
    secret = _secret_of(d) if d.get("secret_command") else ""
    text = _fetch(d, secret)
    obj = _json_in(text)
    src = obj if obj is not None else text
    try:
        rem = path_values(src, d["remaining_path"])
        rst = path_values(src, d["reset_path"])
        tot = path_values(src, d["total_path"]) if d.get("total_path") else []
    except ValueError:
        raise ProbeError("a path of the probe cannot be read")
    wins = []
    for i, x in enumerate(rem):
        try:
            left = float(x)
        except (TypeError, ValueError):
            continue
        total = None
        if i < len(tot) and isinstance(tot[i], (int, float)) and not isinstance(tot[i], bool) and tot[i] > 0:
            total = float(tot[i])
        wins.append({"remaining": left, "reset": time_value(rst[i]) if i < len(rst) else None, "total": total})
    if not wins:
        raise ProbeError("the answer held no number at the remaining path")
    return wins


def allowance_cache():
    return _state_file("allowance.json")


def read_allowance(prov, d, now, force=False):
    """The cached or fresh reading for a provider: {"at", "ok", "windows", "error"}. A probe that fails changes
    nothing: the last good windows stay, with the error beside them."""
    cache = _load(allowance_cache())
    last = cache.get(prov) if isinstance(cache.get(prov), dict) else {}
    if not force and last and now - float(last.get("at") or 0) < conf()["allowance_cache_s"]:
        return last
    new = {"at": now, "ok": True, "windows": last.get("windows") or []}
    try:
        new["windows"] = probe_once(d)
    except ProbeError as e:
        new.update(ok=False, error=str(e))
    except Exception as e:  # never let a probe hold a command up
        new.update(ok=False, error="the probe failed (%s)" % type(e).__name__)
    cache[prov] = new
    try:
        _save(allowance_cache(), cache)
    except OSError:
        pass
    return new


def allowance_state(reading):
    """{"left", "pct", "exhausted", "until"} from a reading's windows: the smallest remaining decides whether
    service is out; service returns when every exhausted window has reset, so the latest of those resets."""
    wins = reading.get("windows") or []
    if not wins:
        return None
    spent = [w for w in wins if w["remaining"] <= 0]
    pcts = [100.0 * w["remaining"] / w["total"] for w in wins if w.get("total")]
    until = None
    if spent and all(w.get("reset") for w in spent):
        until = max(w["reset"] for w in spent)
    return {"left": min(w["remaining"] for w in wins), "pct": min(pcts) if pcts else None,
            "exhausted": bool(spent), "until": until}


def _probes():
    return {p: e["allowance"] for p, e in load_providers().items()
            if isinstance(e.get("allowance"), dict) and e["allowance"].get("state") == "usable"}


def routing_provider(c):
    from . import routing
    return routing.provider_of(c.get("worker"))


def apply_allowances(cands, now=None, force=False):
    """Read each defined probe (when its cached reading is old), set the candidates' allowance, and mark a provider
    whose allowance is spent as down until the reset it reports. Returns the set of providers that are spent now."""
    probes = _probes()
    spent = set()
    if not probes:
        return spent
    from . import workers
    now = time.time() if now is None else now
    for prov, d in probes.items():
        reading = read_allowance(prov, d, now, force)
        st = allowance_state(reading) if reading.get("ok") else None
        if st is None:
            continue
        note = "allowance probe: nothing left%s" % (" until %s" % workers._when(st["until"]) if st["until"] else "")
        down = workers.read_availability().get(prov)
        if st["exhausted"]:
            spent.add(prov)
            if not (down and float(down.get("retry_at") or 0) > now):
                workers.record_down([prov], "limit", note, now=now, until_ts=st["until"] or now + 900, provider=prov)
        elif down and str(down.get("note") or "").startswith("allowance probe"):
            workers.clear_down(prov)
        for c in cands:
            if routing_provider(c) == prov:
                c["allowance_pct_left"] = 0.0 if st["exhausted"] else st["pct"]
    return spent


def refresh_allowances(force=False):
    return apply_allowances([], force=force)


def limit_until(cand):
    """When a provider that just reported a limit is back, by its own probe (read now), or None."""
    prov = routing_provider(cand)
    d = _probes().get(prov) if prov else None
    if d is None:
        return None
    st = allowance_state(read_allowance(prov, d, time.time(), True))
    return st["until"] if st and st["exhausted"] else None


def provider_lines(t):
    """`sisi workers` lines under a tool for each of its providers that has a fact: plan, allowance, phrases, models."""
    provs = load_providers()
    if not provs:
        return []
    from . import routing
    names = {routing.provider_of(m) for m in t.get("models") or [] if routing.provider_of(m)}
    out = []
    for prov in sorted(names & set(provs)):
        e = provs[prov]
        bits = []
        if e.get("plan"):
            bits.append("%s plan%s (%s, %s)" % ("flat-rate" if e["plan"] in ("flat", "free") else "per-use",
                                              " - %s" % e["note"] if e.get("note") else "", e.get("source") or "no source", e.get("date") or "no date"))
        out.append("  provider %s: %s" % (prov, "; ".join(bits) or "facts recorded"))
        d = e.get("allowance")
        if d and d.get("state") == "usable":
            r = _load(allowance_cache()).get(prov) or {}
            st = allowance_state(r) if r else None
            if st:
                resets = [w["reset"] for w in r["windows"] if w.get("reset")]
                out.append("    allowance left: %s%s%s%s" % (
                    ("%g%% (smallest window)" % st["pct"]) if st["pct"] is not None else ("%g (smallest window)" % st["left"]),
                    (", NONE LEFT, back %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(st["until"])) if st["until"] else ", none left")
                    if st["exhausted"] else "",
                    "; next reset %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(min(resets))) if resets else "",
                    "; the last probe failed, this is the reading before it (%s)" % r["error"] if not r.get("ok") else ""))
            elif r.get("error"):
                out.append("    allowance: the probe failed (%s); nothing is assumed" % r["error"])
        elif d:
            out.append("    allowance probe waits for the owner: `sisi approve probe-%s`" % prov)
        for sg in e.get("signatures") or []:
            out.append("    failure phrase %r is classified %s" % (sg["match"], sg["class"]))
        mods = [m.split("/", 1)[1] for m in t.get("models") or [] if routing.provider_of(m) == prov]
        out.append("    models: %s" % ", ".join(mods[:12] + (["... and %d more" % (len(mods) - 12)] if len(mods) > 12 else [])))
    return out
