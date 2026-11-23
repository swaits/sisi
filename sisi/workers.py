"""Dynamic workers: discovery of the agent command-line tools on this machine, the delegation
ledger, and running one brief through whichever worker the record chooses.

The driver table below is data about each tool's command line (how to list its models, run one task
unattended, and read its allowance where it reports one). It names no preferred model: which model
is chosen comes only from discovery plus the judged record (see routing.py). Nothing here is
scheduled; discovery refreshes when a command runs and the cached result is older than the
configured age, or after a failure marks it stale.

Personal files (all in the personal data folder):
  workers.json             the discovery cache, with the time it was read
  delegations.jsonl        the ledger: judged attempts, runs awaiting judgement, amendments
  worker-availability.json unavailability (limit, login, missing, error) with retry times
  worker-prices.json       stored prices: {"models": {"<model or worker>": {"plan": "flat"|"per-use",
                           "cost_per_million_tokens": number, "maker": name, "source": text,
                           "date": "YYYY-MM-DD"}}, "tools": {"<tool>": same shape}}
  model-strength.json      stored strength prior: {"models": {"<model or worker>":
                           {"score": 0..100, "source": text, "date": "YYYY-MM-DD"}}}
The last two start empty and are the seam later research fills in; unknown simply means unknown.
"""
import json, os, re, shutil, subprocess, sys, time, uuid

from . import paths, routing, store

LIST_TIMEOUT_S = 30
DEFAULT_REFRESH_AFTER_S = 24 * 3600
DEFAULT_RUN_TIMEOUT_S = 900
CHECKS = ("none", "diffstat", "tests", "read", "review")
OUTCOMES = ("accepted", "rejected")
EFFORTS = {1: "low", 2: "medium", 3: "high"}

# One small driver per tool. Run templates use tokens expanded by build_command():
# {prompt} the brief text, {model_flag} / {effort_flag} / {cwd_flag} the driver's flag pair (dropped
# when there is no value), {cwd} the folder. No driver passes a flag that switches off approvals or
# a sandbox; `bypass_args` are added only when config workers.allow_bypass names that tool.
DRIVERS = [
    {"name": "claude", "exe": "claude", "list": None,
     "run": ["claude", "-p", "{prompt}", "{model_flag}", "{effort_flag}", "--output-format", "text"],
     "model_flag": "--model", "effort_flag": "--effort", "cwd_flag": None,
     "bypass_args": ["--dangerously-skip-permissions"]},
    {"name": "codex", "exe": "codex", "list": ["codex", "debug", "models"], "list_kind": "codex-json",
     "auth_probe": ["codex", "doctor"],
     "run": ["codex", "exec", "{prompt}", "{model_flag}", "{cwd_flag}", "-s", "workspace-write", "-a", "on-request"],
     "model_flag": "-m", "effort_flag": None, "cwd_flag": "-C",
     "bypass_args": ["--dangerously-bypass-approvals-and-sandbox"]},
    {"name": "opencode", "exe": "opencode", "list": ["opencode", "models"], "list_kind": "lines",
     "run": ["opencode", "run", "{prompt}", "{model_flag}"],
     "model_flag": "-m", "effort_flag": None, "cwd_flag": None, "bypass_args": ["--auto"]},
    {"name": "qwen", "exe": "qwen", "list": None,
     "run": ["qwen", "{prompt}", "{model_flag}", "-o", "text"],
     "model_flag": "-m", "effort_flag": None, "cwd_flag": None, "bypass_args": ["--yolo"]},
    {"name": "muse", "exe": "muse", "list": ["muse", "exec", "--list-models"], "list_kind": "lines",
     "usage": ["muse", "usage", "--json"], "usage_kind": "muse-json",
     "run": ["muse", "exec", "{prompt}", "{model_flag}", "{effort_flag}", "{cwd_flag}"],
     "model_flag": "--model", "effort_flag": "--effort", "cwd_flag": "--workspace",
     "bypass_args": ["--yolo"]},
    {"name": "cursor-agent", "exe": "cursor-agent", "list": ["cursor-agent", "models"], "list_kind": "lines",
     "run": ["cursor-agent", "-p", "--print", "{prompt}", "{model_flag}", "--output-format", "text",
             "{cwd_flag}", "--sandbox", "enabled"],
     "model_flag": "--model", "effort_flag": None, "cwd_flag": "--workspace", "bypass_args": ["--force"]},
    {"name": "copilot", "exe": "copilot", "list": None,
     "run": ["copilot", "-p", "{prompt}", "{model_flag}", "{effort_flag}", "{cwd_flag}", "--output-format", "text"],
     "model_flag": "--model", "effort_flag": "--reasoning-effort", "cwd_flag": "-C",
     "bypass_args": ["--allow-all"]},
    {"name": "pi", "exe": "pi", "list": ["pi", "--list-models"], "list_kind": "lines",
     "run": ["pi", "-p", "{prompt}", "{model_flag}", "--mode", "text"],
     "model_flag": "--model", "effort_flag": None, "cwd_flag": None, "bypass_args": []},
    {"name": "amp", "exe": "amp", "list": None,
     "usage": ["amp", "usage"], "usage_kind": "text",
     "run": ["amp", "-x", "{prompt}", "{model_flag}", "{effort_flag}"],
     "model_flag": "--mode", "effort_flag": "--effort", "cwd_flag": None,
     "bypass_args": ["--dangerously-allow-all"]},
    {"name": "crush", "exe": "crush", "list": ["crush", "models"], "list_kind": "lines",
     "run": ["crush", "run", "{prompt}", "{model_flag}", "{cwd_flag}"],
     "model_flag": "-m", "effort_flag": None, "cwd_flag": "-c", "bypass_args": ["-y"]},
    {"name": "grok", "exe": "grok", "list": ["grok", "models"], "list_kind": "grok",
     "run": ["grok", "-p", "{prompt}", "{model_flag}", "{effort_flag}", "--output-format", "plain", "{cwd_flag}"],
     "model_flag": "-m", "effort_flag": "--effort", "cwd_flag": "--cwd", "bypass_args": ["--always-approve"]},
    {"name": "kimi", "exe": "kimi", "list": None,
     "run": ["kimi", "-p", "{prompt}", "{model_flag}"],
     "model_flag": "-m", "effort_flag": None, "cwd_flag": None, "bypass_args": ["--auto"]},
]
DRIVER_BY_NAME = {d["name"]: d for d in DRIVERS}

# Failure signatures, from the real message texts gathered on this machine. Some tools report a
# limit or login failure with a success exit status, so the output text decides, never the exit
# status alone. Order matters: login first, then limits, then passing errors.
AUTH_SIGNATURES = (
    "authentication required", "run 'agent login'", 'run "agent login"',
    "you are not authenticated", "not authenticated", "no credentials", "no codex credentials",
    "invalid or missing api key", "run 'amp login'", "run codex login", "use /login",
    "no models available", "401 unauthorized", "http 401",
)
LIMIT_SIGNATURES = (
    "provider.go-limit", "monthly usage limit reached", "usage limit reached", "usage limit",
    "rate limit", "you've hit the rate limit", "you've hit your session rate limit",
    "you've reached your weekly rate limit", "quota exceeded", "insufficient credits",
    "out of credits", "http 429", '"status":429', '"status": 429',
)
ERROR_SIGNATURES = (
    "http 500", "http 502", "http 503", "http 529", "service unavailable", "bad gateway",
    "connection refused", "network error", "temporarily unavailable",
)


def classify_failure(text, returncode=0):
    """(reason, note, retry_after_s) for a run or listing that never got to do the work, else None.
    reason is one of auth, limit, missing, error. Text decides even when the exit status is 0."""
    low = (text or "").lower()
    retry = None
    m = re.search(r"retryafterms\D{0,4}(\d+)", low)
    if m:
        retry = int(m.group(1)) / 1000.0
    for sig in AUTH_SIGNATURES:
        if sig in low:
            return "auth", "not logged in (%s)" % _phrase(text, sig), retry
    for sig in LIMIT_SIGNATURES:
        if sig in low:
            return "limit", _phrase(text, sig), retry
    for sig in ERROR_SIGNATURES:
        if sig in low:
            return "error", _phrase(text, sig), retry
    return None


def _phrase(text, sig, width=110):
    t = " ".join((text or "").split())
    i = t.lower().find(sig)
    if i < 0:
        return t[:width]
    start = max(0, i - 20)
    if start:
        start = t.find(" ", start) + 1 or start
    return t[start:start + width]


def workers_cfg():
    cfg = store.config().get("workers")
    return cfg if isinstance(cfg, dict) else {}


def _data_file(name):
    return paths.data_file(name)


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else (default if default is not None else {})
    except (OSError, ValueError):
        return default if default is not None else {}


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _run_quiet(cmd, timeout=LIST_TIMEOUT_S, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except OSError:
        return None, "", ""
    except subprocess.SubprocessError:
        return None, "", ""


_MODEL_TOKEN = re.compile(r"^[A-Za-z0-9][\w./:@-]*$")


def _parse_models(driver, out):
    kind = driver.get("list_kind") or "lines"
    models = []
    if kind == "codex-json":
        try:
            data = json.loads(out)
            for m in data.get("models") or []:
                slug = m.get("slug") if isinstance(m, dict) else None
                if slug:
                    models.append(str(slug))
        except ValueError:
            pass
        return models
    if kind == "grok":
        for token in re.findall(r"grok-[\w.]+", out or ""):
            if token not in models:
                models.append(token)
        return models
    skip = {"warning:", "error:", "error", "you", "available:", "default", "model", "models",
            "provider/model", "no", "none"}
    for line in (out or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        token = parts[0].strip()
        if token.lower() in skip or not _MODEL_TOKEN.match(token):
            continue
        if token not in models:
            models.append(token)
    return models


def _parse_usage(driver, out, err):
    """(allowance_pct_left, allowance_text, failure) from a tool's own usage command where it has one."""
    failure = classify_failure((out or "") + "\n" + (err or ""))
    if failure and failure[0] == "auth":
        return None, None, failure
    if driver.get("usage_kind") == "muse-json":
        try:
            data = json.loads(out)
            allow = data.get("allowance") or {}
            lefts, bits = [], []
            for label, key in (("weekly", "weekly"), ("short window", "window")):
                used = (allow.get(key) or {}).get("usedPercent")
                if isinstance(used, (int, float)):
                    lefts.append(100.0 - float(used))
                    bits.append("%g%% of the %s allowance left" % (100.0 - float(used), label))
            if lefts:
                return min(lefts), ", ".join(bits), None
        except ValueError:
            pass
        return None, None, None
    if driver.get("usage_kind") == "text":
        text = " ".join(((out or "").strip().splitlines() or [""])[0].split())
        return None, (text or None), None
    return None, None, None


def _discover_tool(driver):
    entry = {"name": driver["name"], "installed": False, "models": [], "usable": False,
             "learned_by_use": driver.get("list") is None}
    path = shutil.which(driver["exe"])
    if not path:
        entry["reason"] = "not found on PATH"
        return entry
    entry["installed"] = True
    entry["path"] = path
    entry["usable"] = True
    if driver.get("list"):
        rc, out, err = _run_quiet(driver["list"])
        if rc is None:
            entry.update(usable=False, reason="could not run its model list command")
            return entry
        failure = classify_failure(out + "\n" + err, rc)
        models = _parse_models(driver, out)
        if failure and failure[0] == "auth":
            entry.update(usable=False, reason=failure[1], failure_reason="auth", models=models)
        elif not models and failure:
            entry.update(usable=False, reason=failure[1], failure_reason=failure[0])
        elif not models:
            entry.update(usable=False, reason="its model list came back empty")
        else:
            entry["models"] = models
    if driver.get("auth_probe") and entry["usable"]:
        rc, out, err = _run_quiet(driver["auth_probe"])
        if rc is not None:
            failure = classify_failure(out + "\n" + err, rc)
            if failure and failure[0] == "auth":
                entry.update(usable=False, reason=failure[1], failure_reason="auth")
    if driver.get("usage") and entry["usable"]:
        rc, out, err = _run_quiet(driver["usage"])
        if rc is not None:
            left, text, failure = _parse_usage(driver, out, err)
            if failure:
                entry.update(usable=False, reason=failure[1], failure_reason=failure[0])
            else:
                if left is not None:
                    entry["allowance_pct_left"] = left
                    entry["plan"] = "flat"
                if text:
                    entry["allowance_text"] = text
    return entry


def discovery_path():
    return _data_file("workers.json")


def load_discovery():
    return read_json(discovery_path())


def discover(force=False, now=None):
    """The cached discovery, refreshed in passing when it is older than the configured age."""
    now = time.time() if now is None else now
    cached = load_discovery()
    age = workers_cfg().get("refresh_after_s", workers_cfg().get("max_age_s", DEFAULT_REFRESH_AFTER_S))
    try:
        age = float(age)
    except (TypeError, ValueError):
        age = DEFAULT_REFRESH_AFTER_S
    if not force and cached.get("tools") and now - float(cached.get("checked") or 0) < age:
        return cached
    data = {"checked": now, "tools": [_discover_tool(d) for d in DRIVERS]}
    write_json(discovery_path(), data)
    return data


def mark_discovery_stale():
    cached = load_discovery()
    if cached:
        cached["checked"] = 0
        write_json(discovery_path(), cached)


# ---------------------------------------------------------------- the ledger


def ledger_path():
    return _data_file("delegations.jsonl")


def availability_path():
    return _data_file("worker-availability.json")


def read_records(path=None):
    out = []
    try:
        with open(path or ledger_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    except OSError:
        pass
    return out


def append_record(rec):
    p = ledger_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def read_availability():
    return read_json(availability_path())


def _wait_s(reason, fails):
    if reason == "error":
        return min(30 * 60 * 2 ** (fails - 1), 8 * 3600)
    return min(24 * 3600 * 2 ** (fails - 1), 7 * 24 * 3600)


def record_down(keys, reason, note=None, now=None, retry_after_s=None):
    """Record unavailability under one or more keys (a worker, its tool, its plan prefix).
    Unavailability is kept apart from judged work: it never counts against quality."""
    now = time.time() if now is None else now
    avail = read_availability()
    for key in keys:
        if not key:
            continue
        key = str(key).strip().lower()
        entry = avail.get(key) or {"since": now, "fails": 0}
        entry["fails"] = int(entry.get("fails") or 0) + 1
        entry["reason"] = reason
        if note:
            entry["note"] = note
        entry["retry_at"] = now + (retry_after_s if retry_after_s else _wait_s(reason, entry["fails"]))
        avail[key] = entry
    write_json(availability_path(), avail)
    return avail


def clear_down(worker):
    avail = read_availability()
    if not avail:
        return
    w = str(worker or "").lower()
    model = w.rsplit("/", 1)[-1]
    keep = {k: v for k, v in avail.items()
            if k.lower() not in (w, model) and not w.startswith(k.lower() + "/")}
    if keep != avail:
        write_json(availability_path(), keep)


def ensure_imported(now=None):
    """Import the previously hand-kept ledger once, losslessly. Returns the row count, or None
    when there was nothing (more) to import. The original file is only read."""
    now = time.time() if now is None else now
    marker = _data_file("delegations-import.json")
    if os.path.exists(marker):
        return None
    try:
        from . import taskset
        src = taskset.ledger_path()
    except Exception:
        src = None
    if not src or not os.path.isfile(src):
        return None
    if os.path.realpath(src) == os.path.realpath(ledger_path()):
        return None
    rows = read_records(src)
    existing_ids = {r.get("id") for r in read_records() if r.get("kind") == "attempt"}
    count = 0
    for row in rows:
        if row.get("kind") == "attempt" and row.get("id") in existing_ids:
            continue
        append_record(dict(row))
        count += 1
    # Replay its down/up rows, and merge the availability file that sat beside it, so what was
    # known to be down stays known.
    avail = read_availability()
    for row in rows:
        ts = row.get("ts") if isinstance(row.get("ts"), (int, float)) else now
        if row.get("kind") == "down" and row.get("worker"):
            key = str(row["worker"]).lower()
            e = avail.get(key) or {"since": ts, "fails": 0}
            e["fails"] = int(e.get("fails") or 0) + 1
            e["reason"] = row.get("reason") or "error"
            if row.get("note"):
                e["note"] = row["note"]
            e["retry_at"] = ts + _wait_s(e["reason"], e["fails"])
            avail[key] = e
        elif row.get("kind") == "up" and row.get("worker"):
            avail.pop(str(row["worker"]).lower(), None)
    sibling = os.path.join(os.path.dirname(src), "availability.json")
    if os.path.isfile(sibling):
        for k, v in read_json(sibling).items():
            if isinstance(v, dict):
                avail[str(k).lower()] = v
    if avail:
        write_json(availability_path(), avail)
    write_json(marker, {"source": src, "rows": count, "ts": now})
    return count


def unjudged_runs(records=None):
    records = read_records() if records is None else records
    judged = {r.get("run_id") for r in records if r.get("kind") == "attempt" and r.get("run_id")}
    return [r for r in records if r.get("kind") == "run" and r.get("id") not in judged]


# ---------------------------------------------------------------- candidates


def prices_path():
    return _data_file("worker-prices.json")


def strength_path():
    return _data_file("model-strength.json")


def load_prices():
    return read_json(prices_path())


def load_strength_prior():
    d = read_json(strength_path())
    models = d.get("models")
    return models if isinstance(models, dict) else {}


def _price_for(prices, tool, model, worker):
    models = prices.get("models") if isinstance(prices.get("models"), dict) else {}
    tools = prices.get("tools") if isinstance(prices.get("tools"), dict) else {}
    for table, key in ((models, worker), (models, model), (tools, tool)):
        entry = table.get(key) if key else None
        if isinstance(entry, dict):
            return entry
    return {}


def _canonical(tool, model):
    if model is None:
        return "%s/default" % tool
    return model if "/" in model else "%s/%s" % (tool, model)


def _guess_tool(worker, disc_tools):
    w = str(worker or "").lower()
    model = w.rsplit("/", 1)[-1]
    for t in disc_tools:
        if model in [str(m).lower() for m in t.get("models") or []]:
            return t["name"]
    if "/" in w:
        head = w.split("/", 1)[0]
        for t in disc_tools:
            if any(str(m).lower().startswith(head + "/") for m in t.get("models") or []):
                return t["name"]
        if head in DRIVER_BY_NAME:
            return head
    if model.startswith("muse-"):
        return "muse"
    if model.startswith("claude") or routing.maker_of(model) == "claude":
        return "claude"
    if model.startswith("grok"):
        return "grok"
    return None


def build_candidates(disc=None, records=None):
    """Routing candidates from discovery, the stored price table, and workers the record
    already knows (models learned by use)."""
    disc = discover() if disc is None else disc
    records = read_records() if records is None else records
    prices = load_prices()
    disc_tools = disc.get("tools") or []
    cands, seen = [], set()

    def add(tool, model, usable=True, reason=None, allowance=None, tool_plan=None):
        worker = _canonical(tool, model) if tool else str(model)
        if worker.lower() in seen:
            return None
        seen.add(worker.lower())
        price = _price_for(prices, tool, model, worker)
        cost = price.get("cost_per_million_tokens", price.get("cost"))
        c = {"worker": worker, "tool": tool, "model": model,
             "maker": price.get("maker") or routing.maker_of(model or worker),
             "plan": price.get("plan") or tool_plan,
             "cost": float(cost) if isinstance(cost, (int, float)) else None,
             "allowance_pct_left": allowance, "usable": usable, "reason": reason,
             "price_source": price.get("source"), "price_date": price.get("date"),
             "aliases": [worker, model, ("%s/%s" % (tool, model)) if tool and model else None,
                         tool if model is None else None]}
        c["aliases"] = [a for a in c["aliases"] if a]
        cands.append(c)
        return c

    for t in disc_tools:
        if not t.get("installed", True):
            continue
        models = t.get("models") or []
        if models:
            for m in models:
                add(t["name"], m, usable=bool(t.get("usable", True)), reason=t.get("reason"),
                    allowance=t.get("allowance_pct_left"), tool_plan=t.get("plan"))
        else:
            add(t["name"], None, usable=bool(t.get("usable", True)), reason=t.get("reason"),
                allowance=t.get("allowance_pct_left"), tool_plan=t.get("plan"))

    alias_set = set()
    for c in cands:
        alias_set.update(str(a).lower() for a in c["aliases"])
    for r in records:
        w = r.get("worker")
        if not w or str(w).lower() in alias_set or r.get("kind") not in ("attempt", "run"):
            continue
        tool = _guess_tool(w, disc_tools)
        installed = any(t["name"] == tool and t.get("installed", True) for t in disc_tools) if tool else False
        c = add(tool, r.get("model") or str(w),
                usable=installed, reason=None if installed else "known from the record, but no tool for it was found here")
        if c is not None:
            c["aliases"].append(str(w))
            alias_set.add(str(w).lower())
    return cands


def resolve_worker(name, candidates):
    target = str(name or "").lower()
    for c in candidates:
        if target in {str(a).lower() for a in c.get("aliases") or [c["worker"]]}:
            return c
    if "/" in str(name or ""):
        tool, model = str(name).split("/", 1)
        if tool in DRIVER_BY_NAME:
            return {"worker": str(name), "tool": tool, "model": model,
                    "maker": routing.maker_of(model), "plan": None, "cost": None,
                    "allowance_pct_left": None, "usable": shutil.which(DRIVER_BY_NAME[tool]["exe"]) is not None,
                    "reason": None, "aliases": [str(name), model]}
    return None


# ---------------------------------------------------------------- running


def build_command(driver, cand, prompt, cwd, difficulty):
    effort = EFFORTS.get(difficulty)
    cmd = []
    for token in driver["run"]:
        if token == "{prompt}":
            cmd.append(prompt)
        elif token == "{model_flag}":
            if cand.get("model") and driver.get("model_flag"):
                cmd += [driver["model_flag"], str(cand["model"])]
        elif token == "{effort_flag}":
            if effort and driver.get("effort_flag"):
                cmd += [driver["effort_flag"], effort]
        elif token == "{cwd_flag}":
            if driver.get("cwd_flag"):
                cmd += [driver["cwd_flag"], cwd]
        elif token == "{cwd}":
            cmd.append(cwd)
        else:
            cmd.append(token)
    allow = workers_cfg().get("allow_bypass")
    if isinstance(allow, dict) and allow.get(driver["name"]):
        cmd += list(driver.get("bypass_args") or [])
    return cmd


def extract_usage(text):
    """Tokens and cost where a tool's output reports them as JSON events; (None, None) otherwise."""
    tokens = cost = None
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                u = x.get("usage") if isinstance(x.get("usage"), dict) else x
                for k in ("total_tokens", "totalTokens", "tokens"):
                    if isinstance(u.get(k), (int, float)):
                        tokens = u[k]
                parts = [u.get(k) for k in ("input_tokens", "output_tokens", "inputTokens", "outputTokens")
                         if isinstance(u.get(k), (int, float))]
                if parts and tokens is None:
                    tokens = sum(parts)
                for k in ("cost", "total_cost_usd", "cost_usd", "totalCostUsd"):
                    if isinstance(x.get(k), (int, float)):
                        cost = x[k]
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return tokens, cost


def _transcript_path(run_id):
    d = os.path.join(paths.state(), "delegate")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, run_id + ".log")


def _append_transcript(path, heading, cmd, out, err, rc):
    with open(path, "a", encoding="utf-8") as f:
        f.write("=== %s\n$ %s\nexit: %s\n--- stdout ---\n%s\n--- stderr ---\n%s\n"
                % (heading, " ".join(str(c)[:200] for c in cmd), rc, out or "", err or ""))


def _down_keys(cand, reason):
    keys = [cand["worker"]]
    model = str(cand.get("model") or "")
    if reason == "auth" and cand.get("tool"):
        keys.append(cand["tool"])
    if reason == "limit" and "/" in model:
        keys.append(model.split("/", 1)[0])
    return keys


def run_delegation(candidates, kind, difficulty, prompt, cwd, explicit=None, review_of=None, brief_path=None):
    """Run the brief on the chosen worker, falling through to the next choice on unavailability.
    Returns (run_record, final_text, notes) or (None, None, notes)."""
    notes = []
    run_id = uuid.uuid4().hex[:8]
    transcript = _transcript_path(run_id)
    cfg = workers_cfg()
    try:
        timeout = float(cfg.get("timeout_s", DEFAULT_RUN_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = DEFAULT_RUN_TIMEOUT_S
    tried = []
    cand = explicit
    while True:
        if cand is None:
            result = routing.choose(candidates, read_records(), read_availability(), kind, difficulty,
                                    review_of=review_of, now=time.time(), exclude=tried)
            cand = result["choice"]
            if cand is None:
                notes.append("sisi: no usable worker remains for kind %s at difficulty %s" % (kind, difficulty))
                return None, None, notes
        tried.append(cand["worker"])
        if "contributor" in str(cand.get("model") or cand["worker"]).lower():
            notes.append("sisi: refusing %s: its id contains 'contributor', a tier that trains on prompts"
                         % cand["worker"])
            return None, None, notes
        driver = DRIVER_BY_NAME.get(cand.get("tool") or "")
        if driver is None or shutil.which(driver["exe"]) is None:
            record_down(_down_keys(cand, "missing"), "missing",
                        "no command-line tool found for %s" % cand["worker"])
            mark_discovery_stale()
            notes.append("%s is unavailable (missing: no command-line tool found); trying the next choice"
                         % cand["worker"])
            cand = None
            continue
        cmd = build_command(driver, cand, prompt, cwd, difficulty)
        env = dict(os.environ, SISI_WORKER_RUN="1")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
            rc, out, err = r.returncode, r.stdout or "", r.stderr or ""
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            _append_transcript(transcript, cand["worker"], cmd, out, err, "timeout")
            notes.append("%s did not finish within %gs and was stopped. It may be stalled waiting for an "
                         "approval or sandbox decision: sisi never switches those off unless config "
                         "workers.allow_bypass names the tool. Transcript: %s"
                         % (cand["worker"], timeout, transcript))
            return None, None, notes
        _append_transcript(transcript, cand["worker"], cmd, out, err, rc)
        failure = classify_failure(out + "\n" + err, rc)
        if failure is not None:
            reason, note, retry = failure
            record_down(_down_keys(cand, reason), reason, note, retry_after_s=retry)
            mark_discovery_stale()
            notes.append("%s is unavailable (%s: %s); trying the next choice" % (cand["worker"], reason, note))
            cand = None
            continue
        tokens, cost = extract_usage(out + "\n" + err)
        rec = {"kind": "run", "id": run_id, "ts": round(time.time()), "type": kind,
               "difficulty": difficulty, "worker": cand["worker"], "model": cand.get("model"),
               "tool": cand.get("tool"), "cwd": cwd, "brief": brief_path,
               "transcript": transcript, "exit": rc, "tokens": tokens, "cost": cost,
               "status": "waiting" if rc == 0 else "failed"}
        append_record(rec)
        if rc == 0:
            clear_down(cand["worker"])
        return rec, (out.strip() or err.strip()), notes


# ---------------------------------------------------------------- strength and session lines


def strength_scores(candidates, records):
    """{worker: (score, how)} from the judged record where it is thick enough, else from the
    stored prior (model-strength.json, each figure with its source and date). No shipped ranking:
    a model with neither is simply absent here, and its strength is unknown."""
    prior = load_strength_prior()
    stats = routing.candidate_stats(candidates, records)
    out = {}
    for c in candidates:
        cells = stats.get(c["worker"], {}).get("by_cell", {})
        n = sum(v["n"] for v in cells.values())
        good = sum(v["good"] for v in cells.values())
        if n >= routing.MIN_ATTEMPTS:
            out[c["worker"]] = (100.0 * good / n, "measured from %d judged delegations" % n)
            continue
        entry = None
        for key in [c["worker"], c.get("model")] + list(c.get("aliases") or []):
            if key and isinstance(prior.get(key), dict):
                entry = prior[key]
                break
        if entry and isinstance(entry.get("score"), (int, float)):
            how = "stored prior (%s, %s)" % (entry.get("source") or "no source stated",
                                             entry.get("date") or "no date stated")
            out[c["worker"]] = (float(entry["score"]), how)
    return out


def _cached_candidates(records=None):
    """Candidates from the discovery cache only: session start must stay fast and run no tool."""
    cached = load_discovery()
    if not cached.get("tools"):
        return [], []
    return build_candidates(cached, read_records() if records is None else records), cached["tools"]


def is_subagent_payload(payload):
    if os.environ.get("SISI_WORKER_RUN"):
        return True
    if not isinstance(payload, dict):
        return False
    if payload.get("agent_id") or payload.get("agentId") or payload.get("agent_transcript_path"):
        return True
    tp = str(payload.get("transcript_path") or "")
    return "/subagents/" in tp or tp.endswith("/subagents")


def session_lines(model, payload=None):
    """One or two plain lines at session start about delegating, or nothing for a session another
    agent started. Uses only cached discovery and the record."""
    if not model or is_subagent_payload(payload or {}):
        return []
    records = read_records()
    candidates, _tools = _cached_candidates(records)
    waiting = len(unjudged_runs(records))
    suffix = ""
    if waiting:
        suffix = " %d delegation%s waiting for a judgement: run `sisi workers` to see, then `sisi delegate judge`." \
                 % (waiting, " is" if waiting == 1 else "s are")
        if waiting == 1:
            suffix = " One delegation is waiting for a judgement: run `sisi workers`, then `sisi delegate judge`."
    if not candidates:
        return ["sisi: the strength of this session's model (%s) is unknown here: no workers have been "
                "discovered yet (`sisi workers` finds them), so do the work yourself for now.%s" % (model, suffix)]
    cand = resolve_worker(model, candidates)
    scores = strength_scores(candidates, records)
    own = scores.get(cand["worker"]) if cand else None
    if own is None and cand is None:
        prior = load_strength_prior().get(model)
        if isinstance(prior, dict) and isinstance(prior.get("score"), (int, float)):
            own = (float(prior["score"]), "stored prior (%s, %s)" % (prior.get("source") or "no source stated",
                                                                     prior.get("date") or "no date stated"))
    if own is None:
        return ["sisi: the strength of this session's model (%s) is unknown here (no stored prior and no "
                "measured record yet), so do the work yourself rather than delegating on a guess.%s"
                % (model, suffix)]
    best_worker, (best_score, _how) = max(scores.items(), key=lambda kv: kv[1][0]) if scores else (None, (own[0], ""))
    if own[0] >= best_score - routing.STRONG_BAND:
        return ["sisi: this session's model (%s) is among the strongest available here (%s): plan, ask `sisi route` who "
                "should do each piece, start that worker with this tool's own subagents (use `sisi delegate` "
                "only if it has none), and judge what comes back.%s" % (model, own[1], suffix)]
    return ["sisi: this session's model (%s) is not among the strongest available here (%s): do the work "
            "yourself rather than delegating. Stronger models are available here, strongest first: %s.%s"
            % (model, own[1], ", ".join(w for w, _s in sorted(scores.items(), key=lambda kv: -kv[1][0])[:3]
                                         if scores[w][0] > own[0]), suffix)]


# ---------------------------------------------------------------- commands


def _opt(args, name, default=None):
    args = list(args)
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else default
    for a in args:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _when(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "unknown time"


def _price_lines(tool_name, models, prices):
    lines = []
    tool_price = _price_for(prices, tool_name, None, None)
    shown = set()
    for m in models or [None]:
        p = _price_for(prices, tool_name, m, _canonical(tool_name, m)) or tool_price
        if not p:
            continue
        key = json.dumps(p, sort_keys=True)
        if key in shown:
            continue
        shown.add(key)
        bits = []
        if p.get("plan"):
            bits.append("%s plan" % ("flat-rate" if p["plan"] == "flat" else "per-use"))
        cost = p.get("cost_per_million_tokens", p.get("cost"))
        if isinstance(cost, (int, float)):
            bits.append("%g per million tokens" % cost)
        if p.get("source"):
            bits.append("from %s, %s" % (p["source"], p.get("date") or "no date stated"))
        if bits:
            lines.append("  price%s: %s" % ((" for %s" % m) if m and len(models) > 1 else "", "; ".join(bits)))
    return lines


def cmd_workers(args=()):
    imported = ensure_imported()
    disc = discover(force="--refresh" in args)
    records = read_records()
    avail = read_availability()
    prices = load_prices()
    print("Workers found on this machine (checked %s):" % _when(disc.get("checked")))
    missing = []
    for t in disc.get("tools") or []:
        if not t.get("installed"):
            missing.append(t["name"])
            continue
        down = avail.get(t["name"])
        if not t.get("usable"):
            state = "not usable now: %s" % (t.get("reason") or "unknown reason")
        elif down and float(down.get("retry_at") or 0) > time.time():
            state = "not usable now: %s until %s%s" % (down.get("reason") or "down", _when(down.get("retry_at")),
                                                       (" (%s)" % down["note"]) if down.get("note") else "")
        else:
            state = "usable now"
        print("%s - %s" % (t["name"], state))
        models = t.get("models") or []
        if models:
            shown = models if len(models) <= 24 else models[:24] + ["... and %d more" % (len(models) - 24)]
            print("  models: %s" % ", ".join(shown))
        elif t.get("learned_by_use"):
            print("  models: models learned by use (this tool has no listing command; the record names them)")
        else:
            print("  models: none listed")
        if t.get("allowance_text"):
            print("  allowance left: %s" % t["allowance_text"])
        elif t.get("allowance_pct_left") is not None:
            print("  allowance left: %g%%" % t["allowance_pct_left"])
        for line in _price_lines(t["name"], models, prices):
            print(line)
        if t.get("plan") == "flat" and not _price_lines(t["name"], models, prices):
            print("  price: flat-rate plan (the tool reports an allowance, so one more task costs nothing extra)")
    if missing:
        print("Not found on PATH: %s" % ", ".join(missing))
    down_now = [(k, v) for k, v in sorted(avail.items()) if isinstance(v, dict)]
    for k, v in down_now:
        if k in {t["name"] for t in disc.get("tools") or []}:
            continue
        print("Unavailable: %s - %s, next try %s%s" % (k, v.get("reason") or "down", _when(v.get("retry_at")),
                                                       (" (%s)" % v["note"]) if v.get("note") else ""))
    if imported is not None:
        print("Imported the existing delegation ledger: imported %d rows, once, without changing the original."
              % imported)
    waiting = unjudged_runs(records)
    if waiting:
        print("%d delegation%s waiting for a judgement (%s). Judge with `sisi delegate judge ID "
              "--outcome accepted|rejected --check none|diffstat|tests|read|review`."
              % (len(waiting), "" if len(waiting) == 1 else "s", ", ".join(r["id"] for r in waiting)))
    return 0


def _route_setup(args):
    ensure_imported()
    kind = _opt(args, "--kind")
    difficulty = _opt(args, "--difficulty")
    if not kind or difficulty is None:
        return None
    try:
        difficulty = int(difficulty)
    except ValueError:
        return None
    if difficulty not in (1, 2, 3):
        return None
    return kind, difficulty


def cmd_route(args=()):
    setup = _route_setup(args)
    if setup is None:
        print("usage: sisi route --kind K --difficulty 1|2|3 [--review-of WORKER] [--explain]")
        return 1
    kind, difficulty = setup
    candidates = build_candidates()
    result = routing.choose(candidates, read_records(), read_availability(), kind, difficulty,
                            review_of=_opt(args, "--review-of"), now=time.time())
    if result["choice"] is None:
        print("no usable worker for kind %s at difficulty %d" % (kind, difficulty))
        if "--explain" in args:
            for line in routing.explain_choice(result, kind, difficulty)[1:]:
                print(line)
        return 1
    print(result["choice"]["worker"])
    if "--explain" in args:
        for line in routing.explain_choice(result, kind, difficulty):
            print(line)
    return 0


def cmd_delegate(args=()):
    args = list(args)
    if args[:1] == ["judge"]:
        return _cmd_judge(args[1:])
    if args[:1] == ["amend"]:
        return _cmd_amend(args[1:])
    setup = _route_setup(args)
    brief = _opt(args, "--brief")
    if setup is None or not brief:
        print("usage: sisi delegate --kind K --difficulty 1|2|3 --brief FILE [--worker W] [--review-of W] [--cwd DIR]")
        return 1
    kind, difficulty = setup
    try:
        with open(brief, encoding="utf-8") as f:
            prompt = f.read()
    except OSError as e:
        print("sisi delegate: cannot read the brief %s: %s" % (brief, e), file=sys.stderr)
        return 1
    cwd = _opt(args, "--cwd") or os.getcwd()
    if not os.path.isdir(cwd):
        print("sisi delegate: not a folder: %s" % cwd, file=sys.stderr)
        return 1
    candidates = build_candidates()
    explicit = None
    worker = _opt(args, "--worker")
    if worker:
        explicit = resolve_worker(worker, candidates)
        if explicit is None:
            print("sisi delegate: no such worker found here: %s (see `sisi workers`)" % worker, file=sys.stderr)
            return 1
    rec, final, notes = run_delegation(candidates, kind, difficulty, prompt, cwd,
                                       explicit=explicit, review_of=_opt(args, "--review-of"),
                                       brief_path=os.path.abspath(brief))
    for n in notes:
        print(n)
    if rec is None:
        return 1
    if final:
        print(final)
    print("worker: %s" % rec["worker"])
    print("transcript: %s" % rec["transcript"])
    print("record your judgement: sisi delegate judge %s --outcome accepted|rejected "
          "--check none|diffstat|tests|read|review [--minutes N]" % rec["id"])
    return 0 if rec.get("exit") == 0 else 1


def _cmd_judge(args):
    if not args:
        print("usage: sisi delegate judge ID --outcome accepted|rejected --check CHECK [--minutes N] [--retry-of ID] [--note TEXT]")
        return 1
    run_id, outcome, check = args[0], _opt(args, "--outcome"), _opt(args, "--check")
    if outcome not in OUTCOMES or check not in CHECKS:
        print("usage: sisi delegate judge ID --outcome accepted|rejected --check none|diffstat|tests|read|review [--minutes N]")
        return 1
    records = read_records()
    run = next((r for r in records if r.get("kind") == "run" and r.get("id") == run_id), None)
    if run is None:
        print("sisi delegate: no delegation run with id %s" % run_id, file=sys.stderr)
        return 1
    if any(r.get("kind") == "attempt" and r.get("run_id") == run_id for r in records):
        print("sisi delegate: run %s was already judged" % run_id, file=sys.stderr)
        return 1
    minutes = _opt(args, "--minutes")
    try:
        minutes = float(minutes) if minutes is not None else None
    except ValueError:
        print("sisi delegate: --minutes wants a number", file=sys.stderr)
        return 1
    rec = {"kind": "attempt", "id": uuid.uuid4().hex[:6], "run_id": run_id, "ts": round(time.time()),
           "project": os.path.basename(str(run.get("cwd") or "").rstrip("/")) or None,
           "type": run.get("type"), "difficulty": run.get("difficulty"), "worker": run.get("worker"),
           "model": run.get("model"), "tool": run.get("tool"), "outcome": outcome, "check": check,
           "minutes": minutes, "tokens": run.get("tokens"), "cost": run.get("cost"),
           "retry_of": _opt(args, "--retry-of") or run.get("retry_of"), "note": _opt(args, "--note")}
    append_record(rec)
    clear_down(rec["worker"])
    print(rec["id"])
    return 0


def _cmd_amend(args):
    if not args:
        print("usage: sisi delegate amend ATTEMPT_ID [--note TEXT]")
        return 1
    records = read_records()
    target = args[0]
    attempt = next((r for r in records if r.get("kind") == "attempt" and r.get("id") == target), None)
    if attempt is None:
        attempt = next((r for r in records if r.get("kind") == "attempt" and r.get("run_id") == target), None)
    if attempt is None:
        print("sisi delegate: no judged delegation with id %s" % target, file=sys.stderr)
        return 1
    append_record({"kind": "amend", "id": attempt["id"], "ts": round(time.time()), "note": _opt(args, "--note")})
    print("%s marked as later wrong" % attempt["id"])
    return 0
