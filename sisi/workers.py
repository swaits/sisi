"""Dynamic workers: discovery of the agent command-line tools on this machine, the delegation
ledger, and running one brief through whichever worker the record chooses.

The driver table below is data about each tool's command line (how to list its models, run one task
unattended, and read its allowance where it reports one). It names no preferred model: which model
is chosen comes only from discovery plus the judged record (see routing.py). Nothing here is
scheduled; discovery refreshes when a command runs and the cached result is older than the
configured age, or after a failure marks it stale.

Personal files (all in the personal data folder):
  workers.json             the discovery cache, with the time it was read
  delegations.jsonl        the ledger: judged attempts, runs awaiting judgement, amendments.
                           `sisi delegate judge` is the only way a result enters it.
  worker-availability.json unavailability (limit, login, missing, error) with retry times
  worker-prices.json       worker facts (prices): {"models": {"<model or worker>":
                           {"plan": "flat"|"per-use", "cost_per_million_tokens": number,
                           "maker": name, "source": text, "date": "YYYY-MM-DD"}},
                           "tools": {"<tool>": same shape}}, written by `sisi workers fact`
  model-strength.json      worker facts (benchmark standing): {"models": {"<model or worker>":
                           {"score": 0..100, "source": text, "date": "YYYY-MM-DD"}}}
  worker-prefs.json        the user's own routing constraints: {"avoid": [{"pattern", "why"}],
                           "prefer": [...]}, written by `sisi workers avoid|prefer`
The fact tables start empty; unknown simply means unknown, and session start asks for them to be
researched when they are missing or old. No price, score or model name ships in the product.
"""
import datetime, json, os, re, shutil, statistics, subprocess, sys, time, uuid

from . import brief as brief_contract
from . import paths, routing, store

LIST_TIMEOUT_S = 30
DEFAULT_REFRESH_AFTER_S = 24 * 3600
DEFAULT_RUN_TIMEOUT_S = 900
CHECKS = ("none", "diffstat", "tests", "read", "review")
STRONG_CHECKS = ("tests", "read", "review")  # a result checked one of these ways was checked well
OUTCOMES = ("accepted", "rejected")
REASONS = ("limit", "auth", "missing", "error")
EFFORTS = {1: "low", 2: "medium", 3: "high"}
DIGEST_DAYS = 45            # the judged-record tables cover this window; older evidence goes stale
MAX_DIGEST_ROWS = 40
FACTS_MAX_AGE_DAYS = 30     # older worker facts than this (config: workers.facts_max_age_days) are stale

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


def _parse_time(value):
    """Epoch seconds from a number, an epoch string, or an ISO date/datetime; None if unparsable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def record_down(keys, reason, note=None, now=None, retry_after_s=None, until_ts=None):
    """Record unavailability under one or more keys (a worker, its tool, its plan prefix).
    Unavailability is kept apart from judged work: it never counts against quality. Without an
    explicit `until_ts`, the wait before the next try widens with each repeat failure."""
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
        if until_ts is not None:
            entry["retry_at"] = float(until_ts)
        else:
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


def _row_signature(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def import_ledger(src, now=None):
    """Merge another ledger file into the delegation ledger, losslessly and idempotently.
    Returns (rows before, rows after, rows added). The source file is only read. Down/up rows
    are replayed into availability, so what was known to be down stays known."""
    now = time.time() if now is None else now
    existing = read_records()
    before = len(existing)
    seen = {_row_signature(r) for r in existing}
    seen_attempt_ids = {r.get("id") for r in existing if r.get("kind") == "attempt" and r.get("id")}
    added = 0
    new_rows = []
    for row in read_records(src):
        if _row_signature(row) in seen:
            continue
        if row.get("kind") == "attempt" and row.get("id") in seen_attempt_ids:
            continue
        append_record(dict(row))
        seen.add(_row_signature(row))
        if row.get("kind") == "attempt" and row.get("id"):
            seen_attempt_ids.add(row.get("id"))
        new_rows.append(row)
        added += 1
    avail = read_availability()
    changed = False
    for row in new_rows:
        ts = row.get("ts") if isinstance(row.get("ts"), (int, float)) else now
        if row.get("kind") == "down" and row.get("worker"):
            key = str(row["worker"]).lower()
            e = avail.get(key) or {"since": ts, "fails": 0}
            e["fails"] = int(e.get("fails") or 0) + 1
            e["reason"] = row.get("reason") or "error"
            if row.get("note"):
                e["note"] = row["note"]
            until = _parse_time(row.get("until"))
            e["retry_at"] = until if until is not None else ts + _wait_s(e["reason"], e["fails"])
            avail[key] = e
            changed = True
        elif row.get("kind") == "up" and row.get("worker"):
            if avail.pop(str(row["worker"]).lower(), None) is not None:
                changed = True
    if changed:
        write_json(availability_path(), avail)
    return before, before + added, added


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
    _before, _after, count = import_ledger(src, now=now)
    # Merge the availability file that sat beside the old ledger, so nothing is forgotten.
    sibling = os.path.join(os.path.dirname(src), "availability.json")
    if os.path.isfile(sibling):
        avail = read_availability()
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
    for name in DRIVER_BY_NAME:
        if model == name or model.startswith(name + "-") or model.startswith(name + "_"):
            return name
    return None


def build_candidates(disc=None, records=None):
    """Routing candidates from discovery, the stored price table, and workers the record
    already knows (models learned by use)."""
    disc = discover() if disc is None else disc
    records = read_records() if records is None else records
    prices = load_prices()
    prior = load_strength_prior()
    disc_tools = disc.get("tools") or []
    cands, seen = [], set()

    def add(tool, model, usable=True, reason=None, allowance=None, tool_plan=None):
        worker = _canonical(tool, model) if tool else str(model)
        if worker.lower() in seen:
            return None
        seen.add(worker.lower())
        price = _price_for(prices, tool, model, worker)
        cost = price.get("cost_per_million_tokens", price.get("cost"))
        prior_entry = next((prior[k] for k in (worker, model)
                            if k and isinstance(prior.get(k), dict)), {})
        score = prior_entry.get("score")
        c = {"worker": worker, "tool": tool, "model": model,
             "maker": price.get("maker") or prior_entry.get("maker") or routing.maker_of(model or worker),
             "plan": price.get("plan") or tool_plan,
             "cost": float(cost) if isinstance(cost, (int, float)) else None,
             "allowance_pct_left": allowance, "usable": usable, "reason": reason,
             "price_source": price.get("source"), "price_date": price.get("date"),
             "prior_score": float(score) if isinstance(score, (int, float)) else None,
             "prior_source": prior_entry.get("source"), "prior_date": prior_entry.get("date"),
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
        if "/" not in str(w):
            # No provider prefix: the host tool's own subagent model. It needs no discovered
            # command-line tool and is usable unless marked down (routing checks that).
            c = add(None, str(w), usable=True)
            if c is not None:
                c["host_native"] = True
                alias_set.add(str(w).lower())
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


# ---------------------------------------------------------------- facts, prefs, digest


def prefs_path():
    return _data_file("worker-prefs.json")


def load_prefs():
    d = read_json(prefs_path())
    out = {}
    for key in ("avoid", "prefer"):
        rows = d.get(key)
        out[key] = [r for r in rows if isinstance(r, dict) and r.get("pattern")] if isinstance(rows, list) else []
    return out


def _fact_dates():
    dates = []
    prices = load_prices()
    for table in ("models", "tools"):
        rows = prices.get(table)
        if isinstance(rows, dict):
            for entry in rows.values():
                if isinstance(entry, dict) and entry.get("date"):
                    dates.append(str(entry["date"]))
    for entry in load_strength_prior().values():
        if isinstance(entry, dict) and entry.get("date"):
            dates.append(str(entry["date"]))
    return sorted(dates)


def facts_status(now=None):
    """{"state": "missing"|"stale"|"ok", "newest": date or None, "max_age_days": n}.
    Missing means no price and no benchmark prior is recorded at all; stale means the newest
    recorded fact is older than the configured age (workers.facts_max_age_days)."""
    now = time.time() if now is None else now
    try:
        max_age = float(workers_cfg().get("facts_max_age_days", FACTS_MAX_AGE_DAYS))
    except (TypeError, ValueError):
        max_age = FACTS_MAX_AGE_DAYS
    prices = load_prices()
    has_price = any(isinstance(prices.get(t), dict) and prices[t] for t in ("models", "tools"))
    if not has_price and not load_strength_prior():
        return {"state": "missing", "newest": None, "max_age_days": max_age}
    dates = _fact_dates()
    newest = dates[-1] if dates else None
    newest_ts = _parse_time(newest) if newest else None
    if newest_ts is None or now - newest_ts > max_age * 86400:
        return {"state": "stale", "newest": newest, "max_age_days": max_age}
    return {"state": "ok", "newest": newest, "max_age_days": max_age}


def facts_line(now=None):
    """One session-start line asking for worker facts to be researched, or "" when they are fresh."""
    status = facts_status(now)
    if status["state"] == "ok":
        return ""
    if status["state"] == "missing":
        what = "worker facts are missing (no prices or benchmark standing recorded yet)"
    else:
        what = "worker facts are stale (newest from %s)" % (status["newest"] or "an unstated date")
    return ("sisi: %s: ask a fast, cheap worker to research current prices and "
            "software-engineering benchmark standing for the workers found here (`sisi workers`) "
            "and record each with its source: `sisi workers fact WORKER --price N --source S` "
            "and `sisi workers fact WORKER --score N --source S`. Until then routing has no "
            "price or prior to go on." % what)


def estimate_cost(tokens, price_entry):
    """Estimated cost from a known per-million-token price, or None. The caller labels it estimated."""
    if not isinstance(tokens, (int, float)) or not isinstance(price_entry, dict):
        return None
    per_million = price_entry.get("cost_per_million_tokens", price_entry.get("cost"))
    if not isinstance(per_million, (int, float)):
        return None
    return float(tokens) / 1000000.0 * float(per_million)


def routable_candidates(candidates, records):
    """(candidates, cold_start, excluded) for routing. Only a worker with a judged record, a
    known price or a benchmark prior is a candidate; discovered catalogue models with none of
    those are listed by `sisi workers` but never routed to. When nobody qualifies (a cold
    start), every candidate is returned and cold_start says so: the pick is a trial to judge,
    not a recommendation from evidence."""
    stats = routing.candidate_stats(candidates, records)
    keep = []
    for c in candidates:
        judged = sum(cell["n"] for cell in stats.get(c["worker"], {}).get("by_cell", {}).values())
        if judged or c.get("price_source") or c.get("prior_score") is not None:
            keep.append(c)
    if not keep:
        return list(candidates), True, 0
    return keep, False, len(candidates) - len(keep)


_HOST_TOOL = {"claude-code": "claude", "cursor": "cursor-agent"}


def host_tool():
    """The driver name of the tool hosting this session, or None when it is unknown."""
    host = (store.tool() or "").strip().lower()
    if not host:
        return None
    host = _HOST_TOOL.get(host, host)
    return host if host in DRIVER_BY_NAME else None


def mechanism_for(cand, host=None):
    """How to start the chosen worker: the host's own subagents first, its cross-provider
    delegation when the config says it has one (workers.host_cross_provider), else sisi itself."""
    host = host_tool() if host is None else host
    if cand.get("host_native"):
        return "use the host's own subagent tool with model %s" % (cand.get("model") or cand["worker"])
    if host and cand.get("tool") == host:
        return "use the host's own subagent mechanism (the worker belongs to the host tool)"
    if host and workers_cfg().get("host_cross_provider"):
        return "use the host's cross-provider delegation"
    return "use `sisi delegate` (the host has no delegation of its own for this worker)"


def _pct(ok, n):
    return ("%d%%" % round(100.0 * ok / n)) if n else "-"


def digest_lines(records=None, days=None, now=None):
    """The judged record as three tables: by task type and difficulty (attempts, accepted,
    checked well, later wrong, median minutes; thin rows marked), what fixed each rejection,
    and how good the difficulty guesses were. Accepted on a light check shows as such."""
    records = read_records() if records is None else records
    now = time.time() if now is None else now
    if days is None:
        try:
            days = float(workers_cfg().get("digest_days", DIGEST_DAYS))
        except (TypeError, ValueError):
            days = DIGEST_DAYS
    late = {r.get("id") for r in records if r.get("kind") == "amend"}
    attempts = [r for r in records if r.get("kind") == "attempt"
                and isinstance(r.get("ts"), (int, float)) and r["ts"] >= now - days * 86400]

    def good(a):
        return a.get("outcome") == "accepted" and a.get("id") not in late

    lines = ["Judged record (last %g days, %d delegations; rows under %d attempts are too thin to act on):"
             % (days, len(attempts), routing.MIN_ATTEMPTS)]
    if not attempts:
        lines.append("  No judged delegations yet. Judge each result with `sisi delegate judge`; "
                     "until then routing goes on price and benchmark prior alone.")
        return lines
    cells = {}
    for a in attempts:
        cells.setdefault((a.get("type"), a.get("difficulty"), a.get("worker")), []).append(a)
    rows = []
    for (typ, diff, worker), group in cells.items():
        ok = [a for a in group if good(a)]
        strong = [a for a in ok if a.get("check") in STRONG_CHECKS]
        minutes = [a["minutes"] for a in group if isinstance(a.get("minutes"), (int, float))]
        rows.append({"type": typ, "diff": diff, "worker": worker, "n": len(group), "ok": len(ok),
                     "strong": len(strong), "late": sum(1 for a in group if a.get("id") in late),
                     "mins": statistics.median(minutes) if minutes else None})
    rows.sort(key=lambda r: -r["n"])
    dropped = max(0, len(rows) - MAX_DIGEST_ROWS)
    rows = rows[:MAX_DIGEST_ROWS]
    rows.sort(key=lambda r: (str(r["type"]), r["diff"] or 0, -(r["ok"] / r["n"] if r["n"] else 0), -r["n"]))
    lines += ["", "Workers by task", "",
              "Accepted counts results that passed the check and were not reported wrong later. "
              "Checked well is the share of those verified by tests, a read, or a second reviewer; "
              "the rest were accepted on a lighter check.", "",
              "| Type | Diff | Worker | Attempts | Accepted | Checked well | Later wrong | Median min |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        thin = " (thin)" if r["n"] < routing.MIN_ATTEMPTS else ""
        mins = ("%g" % r["mins"]) if r["mins"] is not None else "-"
        lines.append("| %s | %s | %s | %d%s | %s | %s | %d | %s |"
                     % (r["type"], r["diff"], r["worker"], r["n"], thin,
                        _pct(r["ok"], r["n"]), _pct(r["strong"], r["ok"]), r["late"], mins))
    if dropped:
        lines.append("%d rows with the fewest attempts are not shown." % dropped)
    children = {}
    for a in attempts:
        if a.get("retry_of"):
            children.setdefault(a["retry_of"], []).append(a)

    def later(a):
        for b in children.get(a.get("id"), []):
            yield b
            yield from later(b)

    fixes = {}
    for a in attempts:
        if a.get("outcome") != "rejected":
            continue
        entry = fixes.setdefault(a.get("worker"), {"brief": 0, "stronger": 0, "open": 0})
        fixed_by = [b.get("worker") for b in later(a) if good(b)]
        if a.get("worker") in fixed_by:
            entry["brief"] += 1
        elif fixed_by:
            entry["stronger"] += 1
        else:
            entry["open"] += 1
    if fixes:
        lines += ["", "What fixed each rejection", "",
                  "A better brief points at the brief. A stronger worker points at that worker's "
                  "limit. Not fixed points at a task that was harder or vaguer than it looked.", "",
                  "| Worker | Rejected | Better brief | Stronger worker | Not fixed |",
                  "|---|---|---|---|---|"]
        for worker in sorted(fixes, key=str):
            f = fixes[worker]
            lines.append("| %s | %d | %d | %d | %d |"
                         % (worker, f["brief"] + f["stronger"] + f["open"], f["brief"], f["stronger"], f["open"]))

    def chain_size(a):
        return 1 + sum(chain_size(b) for b in children.get(a.get("id"), []))

    roots = {}
    for a in attempts:
        if not a.get("retry_of"):
            roots.setdefault(a.get("difficulty"), []).append(a)
    lines += ["", "Difficulty guesses", "",
              "If tasks guessed at 1 often need more than one attempt, guess higher or start one tier up.", "",
              "| Guess | Tasks | Done first try | Mean attempts |", "|---|---|---|---|"]
    for diff in sorted(roots, key=lambda d: d or 0):
        group = roots[diff]
        first = sum(1 for a in group if good(a))
        lines.append("| %s | %d | %s | %.1f |"
                     % (diff, len(group), _pct(first, len(group)),
                        statistics.mean(chain_size(a) for a in group)))
    return lines


def delegations_for_project(project, start_ts, end_ts, records=None):
    """Delegations for one project between two times, for the scorecard: the judged attempts in
    the window, worker minutes against wall time, and how many pairs overlapped (the parallelism
    measure). An attempt's interval is its recorded start/end when known, else its judgement
    time minus its recorded minutes."""
    records = read_records() if records is None else records
    rows, intervals = [], []
    for r in records:
        if r.get("kind") != "attempt" or r.get("project") != project:
            continue
        ts = r.get("ts")
        if not isinstance(ts, (int, float)) or not (start_ts <= ts <= end_ts):
            continue
        rows.append(r)
        end = _parse_time(r.get("ended")) or float(ts)
        start = _parse_time(r.get("started"))
        if start is None:
            minutes = r.get("minutes")
            start = end - float(minutes) * 60 if isinstance(minutes, (int, float)) else end
        intervals.append((start, end))
    pairs = 0
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            if intervals[i][0] < intervals[j][1] and intervals[j][0] < intervals[i][1]:
                pairs += 1
    worker_minutes = sum(e - s for s, e in intervals) / 60.0
    wall_minutes = ((max(e for _s, e in intervals) - min(s for s, _e in intervals)) / 60.0) if intervals else 0.0
    return {"project": project, "delegations": rows, "count": len(rows),
            "worker_minutes": worker_minutes, "wall_minutes": wall_minutes,
            "overlapping_pairs": pairs}


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
    prefs = load_prefs()
    while True:
        if cand is None:
            result = routing.choose(candidates, read_records(), read_availability(), kind, difficulty,
                                    review_of=review_of, now=time.time(), exclude=tried,
                                    avoid=prefs["avoid"], prefer=prefs["prefer"])
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
        started = time.time()
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
        cost_class = "measured" if cost is not None else "unavailable"
        if cost is None:
            estimated = estimate_cost(tokens, _price_for(load_prices(), cand.get("tool"),
                                                          cand.get("model"), cand["worker"]))
            if estimated is not None:
                cost, cost_class = estimated, "estimated"
        rec = {"kind": "run", "id": run_id, "ts": round(time.time()), "type": kind,
               "difficulty": difficulty, "worker": cand["worker"], "model": cand.get("model"),
               "tool": cand.get("tool"), "cwd": cwd, "brief": brief_path,
               "started": round(started), "ended": round(time.time()),
               "transcript": transcript, "exit": rc, "tokens": tokens,
               "tokens_class": "measured" if tokens is not None else "unavailable",
               "cost": cost, "cost_class": cost_class,
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


def _with_facts(lines):
    line = facts_line()
    return lines + [line] if line else lines


def session_lines(model, payload=None):
    """One or two plain lines at session start about delegating (plus one asking for worker
    facts when they are missing or stale), or nothing for a session another agent started.
    Uses only cached discovery and the record."""
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
        return _with_facts(["sisi: the strength of this session's model (%s) is unknown here: no workers have been "
                "discovered yet (`sisi workers` finds them), so do the work yourself for now.%s" % (model, suffix)])
    cand = resolve_worker(model, candidates)
    scores = strength_scores(candidates, records)
    own = scores.get(cand["worker"]) if cand else None
    if own is None and cand is None:
        prior = load_strength_prior().get(model)
        if isinstance(prior, dict) and isinstance(prior.get("score"), (int, float)):
            own = (float(prior["score"]), "stored prior (%s, %s)" % (prior.get("source") or "no source stated",
                                                                     prior.get("date") or "no date stated"))
    if own is None:
        return _with_facts(["sisi: the strength of this session's model (%s) is unknown here (no stored prior and no "
                "measured record yet), so do the work yourself rather than delegating on a guess.%s"
                % (model, suffix)])
    best_worker, (best_score, _how) = max(scores.items(), key=lambda kv: kv[1][0]) if scores else (None, (own[0], ""))
    if own[0] >= best_score - routing.STRONG_BAND:
        return _with_facts(["sisi: this session's model (%s) is among the strongest available here (%s): plan, ask `sisi route` who "
                "should do each piece, start that worker with this tool's own subagents (use `sisi delegate` "
                "only if it has none), and judge what comes back.%s" % (model, own[1], suffix)])
    return _with_facts(["sisi: this session's model (%s) is not among the strongest available here (%s): do the work "
            "yourself rather than delegating. Stronger models are available here, strongest first: %s.%s"
            % (model, own[1], ", ".join(w for w, _s in sorted(scores.items(), key=lambda kv: -kv[1][0])[:3]
                                         if scores[w][0] > own[0]), suffix)])


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
    args = list(args)
    if args[:1] == ["fact"]:
        return _cmd_fact(args[1:])
    if args[:1] in (["avoid"], ["prefer"]):
        return _cmd_pref(args[0], args[1:])
    if args[:1] == ["down"]:
        return _cmd_down(args[1:])
    if args[:1] == ["up"]:
        return _cmd_up(args[1:])
    if args[:1] == ["import"]:
        return _cmd_import(args[1:])
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
    prefs = load_prefs()
    for key in ("avoid", "prefer"):
        for entry in prefs[key]:
            print("%s: %s%s" % (key.capitalize(), entry["pattern"],
                                (" (%s)" % entry["why"]) if entry.get("why") else ""))
    line = facts_line()
    if line:
        print(line)
    for ln in digest_lines(records):
        print(ln)
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
    records = read_records()
    candidates, cold, excluded = routable_candidates(build_candidates(), records)
    prefs = load_prefs()
    result = routing.choose(candidates, records, read_availability(), kind, difficulty,
                            review_of=_opt(args, "--review-of"), now=time.time(),
                            avoid=prefs["avoid"], prefer=prefs["prefer"])
    if result["choice"] is None:
        print("no usable worker for kind %s at difficulty %d" % (kind, difficulty))
        if "--explain" in args:
            for line in routing.explain_choice(result, kind, difficulty)[1:]:
                print(line)
        return 1
    print(result["choice"]["worker"])
    print("mechanism: %s" % mechanism_for(result["choice"]))
    if "--explain" in args:
        for line in routing.explain_choice(result, kind, difficulty):
            print(line)
        if excluded:
            print("%d discovered model(s) with no judged record, known price or benchmark prior "
                  "are not candidates" % excluded)
        if cold:
            print("cold start: no worker here has a judged record, a known price or a benchmark "
                  "prior yet, so this pick is a trial, not a recommendation from evidence. "
                  "Judge its result (`sisi delegate judge`) and record worker facts "
                  "(`sisi workers fact`) so the next choice has something to go on.")
            line = facts_line()
            if line:
                print(line)
    return 0


def cmd_delegate(args=()):
    args = list(args)
    if args[:1] == ["judge"]:
        return _cmd_judge(args[1:])
    if args[:1] == ["amend"]:
        return _cmd_amend(args[1:])
    if args[:1] == ["recent"]:
        return _cmd_recent(args[1:])
    if args[:1] == ["brief"]:
        sys.stdout.write(brief_contract.template())
        return 0
    if args[:1] == ["check"]:
        return _cmd_brief_check(args[1:])
    if args[:1] == ["guide"]:
        try:
            with open(paths.canon("orchestration.md"), encoding="utf-8") as f:
                sys.stdout.write(f.read())
            return 0
        except OSError as e:
            print("sisi delegate: cannot read the orchestration playbook: %s" % e, file=sys.stderr)
            return 1
    if args[:1] == ["down"]:
        return _cmd_down(args[1:])
    if args[:1] == ["up"]:
        return _cmd_up(args[1:])
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
    missing = brief_contract.missing_required(prompt)
    if missing:
        print("sisi delegate: refusing to run this brief; it lacks %s. "
              "`sisi delegate brief` prints the template; `sisi delegate check FILE` lists every missing part."
              % ", ".join(missing), file=sys.stderr)
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
    else:
        candidates, _cold, _excluded = routable_candidates(candidates, read_records())
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


def _number_opt(args, name):
    value = _opt(args, name)
    if value is None:
        return None, True
    try:
        return float(value), True
    except ValueError:
        return None, False


def _judge_extras(args, base):
    """Shared optional fields for both judge forms. Returns an error string or None."""
    minutes, ok = _number_opt(args, "--minutes")
    if not ok:
        return "--minutes wants a number"
    if minutes is not None:
        base["minutes"] = minutes
    tokens = _opt(args, "--tokens")
    if tokens is not None:
        try:
            base["tokens"] = int(float(tokens))
        except ValueError:
            return "--tokens wants a number"
    cost, ok = _number_opt(args, "--cost")
    if not ok:
        return "--cost wants a number"
    if cost is not None:
        base["cost"], base["cost_class"] = cost, "measured"
    for opt, key in (("--started", "started"), ("--ended", "ended")):
        value = _opt(args, opt)
        if value is not None:
            parsed = _parse_time(value)
            if parsed is None:
                return "%s wants an epoch number or an ISO date like 2026-12-01T09:00" % opt
            base[key] = round(parsed)
    project = _opt(args, "--project")
    if project:
        base["project"] = project
    session = _opt(args, "--session") or os.environ.get("SISI_SESSION_ID")
    if session:
        base["session"] = session
    retry_of = _opt(args, "--retry-of")
    if retry_of:
        base["retry_of"] = retry_of
    note = _opt(args, "--note")
    if note is not None:
        base["note"] = note
    return None


def _cmd_judge(args):
    """The only way a result enters the ledger. Two forms: judge a `sisi delegate` run by its
    id, or judge work run any other way (the host's own subagents, a shell-launched worker)
    by naming the worker, kind and difficulty directly."""
    usage = ("usage: sisi delegate judge ID --outcome accepted|rejected --check CHECK [--minutes N]\n"
             "       sisi delegate judge --worker W --type K --difficulty 1|2|3 --outcome accepted|rejected "
             "--check CHECK [--minutes N] [--tokens N] [--cost N] [--retry-of ID] [--project P] "
             "[--session S] [--started T] [--ended T] [--note TEXT]")
    outcome, check = _opt(args, "--outcome"), _opt(args, "--check")
    if outcome not in OUTCOMES or check not in CHECKS:
        print(usage)
        return 1
    records = read_records()
    run_id = args[0] if args and not args[0].startswith("--") else None
    if run_id is not None:
        run = next((r for r in records if r.get("kind") == "run" and r.get("id") == run_id), None)
        if run is None:
            print("sisi delegate: no delegation run with id %s" % run_id, file=sys.stderr)
            return 1
        if any(r.get("kind") == "attempt" and r.get("run_id") == run_id for r in records):
            print("sisi delegate: run %s was already judged" % run_id, file=sys.stderr)
            return 1
        rec = {"kind": "attempt", "id": uuid.uuid4().hex[:6], "run_id": run_id, "ts": round(time.time()),
               "project": os.path.basename(str(run.get("cwd") or "").rstrip("/")) or None,
               "type": run.get("type"), "difficulty": run.get("difficulty"), "worker": run.get("worker"),
               "model": run.get("model"), "tool": run.get("tool"), "outcome": outcome, "check": check,
               "minutes": None, "tokens": run.get("tokens"), "tokens_class": run.get("tokens_class"),
               "cost": run.get("cost"), "cost_class": run.get("cost_class"),
               "started": run.get("started"), "ended": run.get("ended"),
               "retry_of": run.get("retry_of"), "note": None}
    else:
        worker = _opt(args, "--worker")
        kind = _opt(args, "--type") or _opt(args, "--kind")
        difficulty = _opt(args, "--difficulty")
        try:
            difficulty = int(difficulty) if difficulty is not None else None
        except ValueError:
            difficulty = None
        if not worker or not kind or difficulty not in (1, 2, 3):
            print(usage)
            return 1
        rec = {"kind": "attempt", "id": uuid.uuid4().hex[:6], "run_id": None, "ts": round(time.time()),
               "project": os.path.basename(os.getcwd().rstrip("/")) or None,
               "type": kind, "difficulty": difficulty, "worker": worker.strip().lower(),
               "model": _opt(args, "--model"), "tool": _opt(args, "--tool"),
               "outcome": outcome, "check": check, "minutes": None, "tokens": None,
               "cost": None, "cost_class": "unavailable", "retry_of": None, "note": None}
    error = _judge_extras(args, rec)
    if error:
        print("sisi delegate: %s" % error, file=sys.stderr)
        return 1
    if rec.get("retry_of") and rec["retry_of"] not in {r.get("id") for r in records if r.get("kind") == "attempt"}:
        print("sisi delegate: no judged delegation with id %s (see `sisi delegate recent`)" % rec["retry_of"],
              file=sys.stderr)
        return 1
    if rec.get("cost") is None and rec.get("tokens") is not None:
        estimated = estimate_cost(rec["tokens"], _price_for(load_prices(), rec.get("tool"),
                                                            rec.get("model"), rec.get("worker")))
        if estimated is not None:
            rec["cost"], rec["cost_class"] = estimated, "estimated"
    if rec.get("tokens") is not None and not rec.get("tokens_class"):
        rec["tokens_class"] = "measured"
    append_record(rec)
    # A worker that returned a result, good or bad, is reachable. A rejection judges the work;
    # it never marks the worker unavailable.
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


def _cmd_recent(args):
    count = _opt(args, "-n") or _opt(args, "--count") or _opt(args, "--limit")
    try:
        count = int(count) if count is not None else 10
    except ValueError:
        print("usage: sisi delegate recent [-n N] [--project P]")
        return 1
    records = read_records()
    late = {r.get("id") for r in records if r.get("kind") == "amend"}
    attempts = [r for r in records if r.get("kind") == "attempt"]
    project = _opt(args, "--project")
    if project:
        attempts = [r for r in attempts if r.get("project") == project]
    for r in attempts[-count:] if count > 0 else attempts:
        try:
            day = time.strftime("%Y-%m-%d", time.localtime(float(r.get("ts") or 0)))
        except (TypeError, ValueError, OSError):
            day = "unknown date"
        outcome = "later wrong" if r.get("id") in late else (r.get("outcome") or "?")
        checked = r.get("check") or "?"
        suffix = " (checked well)" if checked in STRONG_CHECKS else " (light check)"
        note = ("  %s" % r["note"]) if r.get("note") else ""
        print("%s  %s  %s  %s/%s  %s  %s, check %s%s%s"
              % (r.get("id"), day, r.get("project"), r.get("type"), r.get("difficulty"),
                 r.get("worker"), outcome, checked, suffix, note))
    return 0


def _cmd_brief_check(args):
    if not args:
        print("usage: sisi delegate check FILE")
        return 1
    try:
        with open(args[0], encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print("sisi delegate: cannot read %s: %s" % (args[0], e), file=sys.stderr)
        return 1
    missing = brief_contract.missing_parts(text)
    if not missing:
        print("brief ok: all %d parts present" % len(brief_contract.PARTS))
        return 0
    print("brief lacks:")
    for title in missing:
        print("  - %s" % title)
    print("`sisi delegate brief` prints the template.")
    return 1


def _cmd_down(args):
    if not args:
        print("usage: sisi workers down WORKER --reason limit|auth|missing|error [--until DATE] [--note TEXT]")
        return 1
    worker = str(args[0]).strip().lower().rstrip("/")
    reason = _opt(args, "--reason")
    if reason not in REASONS:
        print("usage: sisi workers down WORKER --reason limit|auth|missing|error [--until DATE] [--note TEXT]")
        return 1
    until = _opt(args, "--until")
    until_ts = _parse_time(until) if until is not None else None
    if until is not None and until_ts is None:
        print("sisi: --until wants a date like 2026-12-01 or 2026-12-01T09:00", file=sys.stderr)
        return 1
    note = _opt(args, "--note")
    record_down([worker], reason, note, until_ts=until_ts)
    append_record({"kind": "down", "worker": worker, "ts": round(time.time()),
                   "reason": reason, "note": note, "until": until})
    entry = read_availability()[worker]
    print("%s down (%s), next try %s" % (worker, reason, _when(entry.get("retry_at"))))
    return 0


def _cmd_up(args):
    if not args:
        print("usage: sisi workers up WORKER")
        return 1
    worker = str(args[0]).strip().lower().rstrip("/")
    before = read_availability()
    clear_down(worker)
    after = read_availability()
    back = sorted(set(before) - set(after))
    for key in back:
        append_record({"kind": "up", "worker": key, "ts": round(time.time())})
    print("available again: %s" % ", ".join(back) if back else "%s was not marked down" % worker)
    return 0


def _cmd_import(args):
    if not args:
        print("usage: sisi workers import FILE")
        return 1
    if not os.path.isfile(args[0]):
        print("sisi: no such ledger file: %s" % args[0], file=sys.stderr)
        return 1
    before, after, added = import_ledger(args[0])
    print("imported %d rows from %s (before: %d, after: %d); the original file is unchanged"
          % (added, args[0], before, after))
    return 0


def _cmd_fact(args):
    usage = ("usage: sisi workers fact WORKER --price N [--plan flat|per-use] [--maker M] --source S [--date YYYY-MM-DD]\n"
             "       sisi workers fact WORKER --score 0..100 --source S [--date YYYY-MM-DD]")
    if not args:
        print(usage)
        return 1
    worker = args[0]
    source = _opt(args, "--source")
    date = _opt(args, "--date") or time.strftime("%Y-%m-%d", time.localtime())
    price, price_ok = _number_opt(args, "--price")
    score, score_ok = _number_opt(args, "--score")
    if not price_ok or not score_ok or (price is None and score is None):
        print(usage)
        return 1
    if not source:
        print("sisi: a fact needs its --source (where the figure came from); nothing recorded", file=sys.stderr)
        return 1
    if price is not None:
        plan = _opt(args, "--plan")
        if plan is not None and plan not in ("flat", "per-use"):
            print("sisi: --plan wants flat or per-use", file=sys.stderr)
            return 1
        prices = load_prices()
        models = prices.get("models") if isinstance(prices.get("models"), dict) else {}
        entry = dict(models.get(worker) or {})
        entry.update({"cost_per_million_tokens": price, "source": source, "date": date})
        if plan:
            entry["plan"] = plan
        maker = _opt(args, "--maker")
        if maker:
            entry["maker"] = maker
        models[worker] = entry
        prices["models"] = models
        write_json(prices_path(), prices)
        print("recorded price for %s: %g per million tokens (from %s, %s)" % (worker, price, source, date))
    if score is not None:
        if not (0 <= score <= 100):
            print("sisi: --score wants a number from 0 to 100", file=sys.stderr)
            return 1
        data = read_json(strength_path())
        models = data.get("models") if isinstance(data.get("models"), dict) else {}
        entry = dict(models.get(worker) or {})
        entry.update({"score": score, "source": source, "date": date})
        maker = _opt(args, "--maker")
        if maker:
            entry["maker"] = maker
        models[worker] = entry
        data["models"] = models
        write_json(strength_path(), data)
        print("recorded benchmark standing for %s: %g (from %s, %s)" % (worker, score, source, date))
    return 0


def _cmd_pref(kind, args):
    prefs = load_prefs()
    if not args:
        for entry in prefs[kind]:
            print("%s: %s%s" % (kind, entry["pattern"], (" (%s)" % entry["why"]) if entry.get("why") else ""))
        if not prefs[kind]:
            print("no %s patterns recorded" % kind)
        return 0
    pattern = args[0]
    why = _opt(args, "--why")
    prefs[kind] = [e for e in prefs[kind] if e.get("pattern") != pattern]
    prefs[kind].append({"pattern": pattern, "why": why})
    write_json(prefs_path(), prefs)
    print("%s %s recorded%s" % (kind, pattern, (" (%s)" % why) if why else ""))
    return 0
