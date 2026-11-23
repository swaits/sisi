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
                           {"plan": "flat"|"per-use", "price_in": number, "price_out": number (as
                           published; ranked by a blend, `route.price_blend_input_parts` input to one
                           output) or "cost_per_million_tokens": one blended figure,
                           "maker": name, "source": text, "date": "YYYY-MM-DD"}},
                           "tools": {"<tool>": same shape}}, written by `sisi workers fact`
  model-strength.json      worker facts (benchmark standing, a published figure; never the measured
                           accepted rate): {"models": {"<model or worker>":
                           {"standing": 0..100, "source": text, "date": "YYYY-MM-DD"}}}
  worker-prefs.json        the user's own routing constraints: {"avoid": [{"pattern", "why"}],
                           "prefer": [...], "only": [{"provider", "patterns", "why"}]}, written by
                           `sisi workers avoid|prefer|only`
  worker-notes.json        standing operational facts about workers: {"notes": [{"pattern", "text",
                           "why", "date"}]}, written by `sisi workers note`; shown to the agent as
                           information, never applied by sisi itself
The fact tables start empty; unknown simply means unknown, and session start asks for them to be
researched when they are missing or old. No price, score or model name ships in the product.
"""
import datetime, json, os, re, shutil, statistics, subprocess, sys, time, uuid

from . import brief as brief_contract
from . import discovery as _D
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
    "no models available", "401 unauthorized", "http 401", "api error 401", "api error 403", "http 403",
    "403 forbidden", "not logged in", "login required", "please log in", "invalid api key",
)
LIMIT_SIGNATURES = (
    "provider.go-limit", "monthly usage limit reached", "usage limit reached", "usage limit",
    "rate limit", "you've hit the rate limit", "you've hit your session rate limit",
    "you've reached your weekly rate limit", "quota exceeded", "insufficient credits",
    "out of credits", "http 429", '"status":429', '"status": 429',
    "api error 429", "error 429", "too many requests", "quota exhausted", "out of quota", "subscription quota",
    "insufficient quota", "credit balance", "billing", "payment required", "http 402",
)
MISSING_SIGNATURES = (
    "tool not found", "command not found", "provider not connected", "not connected", "provider not found",
    "model not found", "unknown model",
)
ERROR_SIGNATURES = (
    "http 500", "http 502", "http 503", "http 529", "service unavailable", "bad gateway",
    "connection refused", "network error", "temporarily unavailable",
)


def classify_failure(text, returncode=0, extra=None):
    """(reason, note, retry_after_s) for a run or listing that never got to do the work, else None.
    reason is one of auth, limit, missing, error. Text decides even when the exit status is 0.
    `extra` is {"auth": [...], "limit": [...]}: phrases a learned driver adds to the built-in ones."""
    low = (text or "").lower()
    retry = None
    m = re.search(r"retryafterms\D{0,4}(\d+)", low)
    if m:
        retry = int(m.group(1)) / 1000.0
    elif "reset" in low:
        until = parse_reset(text)
        if until is not None:
            retry = until - time.time()
    extra = extra or {}
    for sig in AUTH_SIGNATURES + tuple(extra.get("auth") or ()):
        if sig in low:
            return "auth", "not logged in (%s)" % _phrase(text, sig), retry
    for sig in LIMIT_SIGNATURES + tuple(extra.get("limit") or ()):
        if sig in low:
            return "limit", _phrase(text, sig), retry
    for sig in MISSING_SIGNATURES:
        if sig in low:
            return "missing", _phrase(text, sig), retry
    for sig in ERROR_SIGNATURES:
        if sig in low:
            return "error", _phrase(text, sig), retry
    return None


_ISO_TIME = r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"


def failure_for(text, cand=None, returncode=0):
    """classify_failure with what is known of the worker: its provider's own recorded phrases first (a provider's
    error code can be a login problem and not a limit), then the built-in phrases and a learned driver's own."""
    driver = _D.driver_for(cand.get("tool")) if cand else None
    return (_D.provider_failure(cand, text) if cand else None) or classify_failure(text, returncode, _D.extra_signatures(driver))


def parse_reset(text, now=None):
    """The epoch second a limit message says the worker is back at (an ISO date-time or date, best after the
    word "reset"), or None when it names none or only a past one."""
    now = time.time() if now is None else now
    t = text or ""
    for pat in (r"reset\w*\s*(?:at|on|in|:)?\s*[:=]?\s*(%s)" % _ISO_TIME, r"(%s)" % _ISO_TIME):
        for m in re.finditer(pat, t, re.I):
            ts = _parse_time(m.group(1))
            if ts is not None and ts > now:
                return ts
        if re.search(r"reset", t, re.I) is None:
            break  # without the word, only the first (keyword) pattern was worth trying
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
    if cached.get("tools"):  # models the previous discovery did not have wait for the next session start to be named
        here = _model_names(data)
        kept = [w for w in cached.get("new_unannounced") or [] if w in here]
        data["new_unannounced"] = kept + sorted(w for w in here - _model_names(cached) if w not in kept)
    write_json(discovery_path(), data)
    return data


def _model_names(disc):
    return {_canonical(t["name"], m) for t in disc.get("tools") or [] for m in t.get("models") or []
            if "contributor" not in str(m).lower()}  # a tier that trains on its prompts is never offered


def new_worker_line():
    """One line naming up to three models discovery found that the previous discovery did not have, once; they
    are unproven, so low-stakes work first and a closer look at what they return, until their record is no longer
    thin. None when there is nothing new (or it was said already)."""
    disc = load_discovery()
    records = read_records()
    judged = {}
    for r in records:
        if r.get("kind") == "attempt":
            judged[str(r.get("worker") or "").lower()] = judged.get(str(r.get("worker") or "").lower(), 0) + 1
    new = [w for w in disc.get("new_unannounced") or []
           if "contributor" not in w.lower() and judged.get(w.lower(), 0) < routing.MIN_ATTEMPTS]
    if not disc.get("new_unannounced"):
        return None
    disc["new_unannounced"] = []
    write_json(discovery_path(), disc)
    if not new:
        return None
    more = " (and %d more)" % (len(new) - 3) if len(new) > 3 else ""
    return ("sisi: new worker model(s) found since the last discovery: %s%s. They are unproven (no judged record): give them "
            "low-stakes work first and check what they return one level more carefully, until their record is no longer "
            "thin (%d judged attempts)." % (", ".join(new[:3]), more, routing.MIN_ATTEMPTS))


def override_line(records=None):
    """How often the router's pick was overridden and how the overrides turned out against the recommendations
    that were followed; None when nothing was routed. Under five judged on either side it says too few."""
    records = read_records() if records is None else records
    routed = [r for r in merged_runs(records) if r.get("chosen_against_route") is not None]
    if not routed:
        return None
    attempts = [r for r in records if r.get("kind") == "attempt" and r.get("chosen_against_route") is not None]

    def rate(rows):
        n = len(rows)
        return "too few to say (%d judged, need 5)" % n if n < 5 else "%d%% accepted (%d judged)" % (
            round(100.0 * sum(1 for r in rows if r.get("outcome") == "accepted") / n), n)
    over = [r for r in attempts if r["chosen_against_route"]]
    followed = [r for r in attempts if not r["chosen_against_route"]]
    return ("Router overridden in %d of %d routed delegations. Overrides: %s. Recommendations followed: %s."
            % (sum(1 for r in routed if r["chosen_against_route"]), len(routed), rate(over), rate(followed)))


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
    # a trailing Z (UTC) and a +HHMM offset are accepted on every Python version; a time with no
    # zone is read as local time, a bare date as the start of that day
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    elif re.search(r"[+-]\d{4}$", text) and "T" in text.upper().replace(" ", "T"):
        text = text[:-2] + ":" + text[-2:]
    try:
        return datetime.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def record_down(keys, reason, note=None, now=None, retry_after_s=None, until_ts=None, provider=None):
    """Record unavailability under one or more keys (a worker, its tool, its plan prefix).
    Unavailability is kept apart from judged work: it never counts against quality. Without an
    explicit `until_ts`, the wait before the next try widens with each repeat failure. The key equal to
    `provider` is marked as a provider's: it reaches that provider's workers only (routing.provider_of)."""
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
        if provider and key == str(provider).strip().lower():
            entry["scope"] = "provider"
        if until_ts is not None:
            entry["retry_at"] = float(until_ts)
        else:
            entry["retry_at"] = now + (retry_after_s if retry_after_s else _wait_s(reason, entry["fails"]))
        avail[key] = entry
    write_json(availability_path(), avail)
    return avail


_MODEL_ONLY = re.compile(r"\bmodel\b.{0,80}(not found|not available|unavailable|not supported|overloaded|does not exist|"
                         r"deprecated)|(unknown|invalid|unsupported) model", re.I | re.S)


def identify_worker(text, candidates=None):
    """The one candidate worker a message names (by worker id, model or alias, longest spelling first), or
    None when it names none or more than one."""
    low = (text or "").lower()
    cands = _cached_candidates()[0] if candidates is None else candidates
    found = {}
    for c in cands:
        names = [c.get("worker"), c.get("model")] + list(c.get("aliases") or [])
        hits = [str(n).lower() for n in names if n and len(str(n)) >= 3 and str(n).lower() in low]
        if hits:
            found[c["worker"]] = max(len(h) for h in hits)
    if not found:
        return None
    best = max(found.values())
    top = [w for w, n in found.items() if n == best]
    return top[0] if len(top) == 1 else None


def mark_unavailable(worker, text, now=None):
    """Record, without being asked, that the worker named failed for a reason that is not about its work
    (limit, login, missing, passing error): its provider when the whole provider is out, the single model
    when the text shows only the model is. The time it is back is parsed from the message when it gives one,
    else the usual widening wait. Returns {"worker", "keys", "reason", "note", "until"} or None when the text
    is no such failure. Never a quality judgement."""
    if not worker:
        return None
    cand = resolve_worker(worker, _cached_candidates()[0]) or {"worker": worker, "model": worker, "tool": None}
    failure = failure_for(text, cand)
    if failure is None:
        return None
    reason, note, retry = failure
    now = time.time() if now is None else now
    model = str(cand.get("model") or "")
    if _MODEL_ONLY.search(text or ""):
        keys = [cand["worker"]]
    elif "/" in model:
        keys = [cand["worker"], model.split("/", 1)[0]]
    elif cand.get("tool") and not cand.get("host_native"):
        keys = [cand["worker"], cand["tool"]]
    else:
        keys = [cand["worker"]]
    until = parse_reset(text, now)
    if until is None and reason == "limit":
        until = _D.limit_until(cand)  # the provider's own allowance probe says when it is back
    avail = record_down(keys, reason, note, now=now, retry_after_s=None if until else retry, until_ts=until,
                        provider=_provider_to_mark(cand))
    shown = avail.get(str(keys[-1]).lower()) or {}
    return {"worker": cand["worker"], "keys": keys, "reason": reason, "note": note,
            "until": until if until is not None else shown.get("retry_at")}


def earliest_due(now=None):
    """(key, epoch) of the worker or provider due for another try soonest, or None when nothing is down."""
    now = time.time() if now is None else now
    rows = [(float(e.get("retry_at") or 0), k) for k, e in read_availability().items()
            if isinstance(e, dict) and float(e.get("retry_at") or 0) > now]
    return (min(rows)[1], min(rows)[0]) if rows else None


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


def merged_runs(records=None):
    """The ledger's runs, each with the later `run-end` fact for its id applied (a delegation the
    host started: written when it begins, completed when it returns). A run still in flight keeps
    status "pending"."""
    records = read_records() if records is None else records
    ends = {}
    for r in records:
        if r.get("kind") == "run-end" and r.get("run_id"):
            ends[r["run_id"]] = r
    out = []
    for r in records:
        if r.get("kind") != "run":
            continue
        end = ends.get(r.get("id"))
        if end is not None:
            r = dict(r, **{k: v for k, v in end.items() if k not in ("kind", "run_id", "ts") and v is not None})
        out.append(r)
    return out


NOT_JUDGED_STATUSES = ("pending", "superseded")  # in flight, or replaced by a fallback: nothing to judge


def unjudged_runs(records=None):
    """Finished runs with no judgement. A run still in flight (status "pending") is not waiting yet, and one
    replaced by a fallback (status "superseded") is never asked for."""
    records = read_records() if records is None else records
    judged = {r.get("run_id") for r in records if r.get("kind") == "attempt" and r.get("run_id")}
    return [r for r in merged_runs(records) if r.get("id") not in judged and r.get("status") not in NOT_JUDGED_STATUSES]


# ---------------------------------------------------------------- candidates


def prices_path():
    return _data_file("worker-prices.json")


def strength_path():
    return _data_file("model-strength.json")


def load_prices():
    return read_json(prices_path())


def standing_of(entry):
    """The benchmark standing in a stored fact, or None. Facts recorded before standing had its own
    name carry it as "score": read the same way, with their source and date."""
    if not isinstance(entry, dict):
        return None
    for field in ("standing", "score"):
        v = entry.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def load_strength_prior():
    d = read_json(strength_path())
    models = d.get("models")
    return models if isinstance(models, dict) else {}


def migrate_standing_facts():
    """Facts recorded before standing had its own name store it as "score". Rename each to "standing",
    keeping its source, date and maker. Returns how many moved; repeating it moves none."""
    path = strength_path()
    data = read_json(path)
    models = data.get("models")
    if not isinstance(models, dict):
        return 0
    moved = 0
    for key, entry in list(models.items()):
        if isinstance(entry, dict) and "score" in entry:
            rest = {k: v for k, v in entry.items() if k not in ("score", "standing")}
            models[key] = dict({"standing": entry["standing"] if "standing" in entry else entry["score"]}, **rest)
            moved += 1
    if moved:
        try:
            write_json(path, data)
        except OSError:
            return 0
    return moved


def route_cfg():
    cfg = store.config().get("route")
    return cfg if isinstance(cfg, dict) else {}


def price_blend():
    """Parts of input price to one part of output price in the blended price used for ranking and
    cost estimates: `route.price_blend_input_parts`, default 3."""
    v = route_cfg().get("price_blend_input_parts")
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else routing.DEFAULT_PRICE_BLEND


def entry_cost(entry):
    """One per-million-token price from a stored price fact, or None: an input and output price pair is
    blended at the configured ratio, a single figure is taken as the blended figure it was recorded as."""
    if not isinstance(entry, dict):
        return None
    blended = routing.blended_price(entry.get("price_in"), entry.get("price_out"), price_blend())
    if blended is not None:
        return blended
    single = entry.get("cost_per_million_tokens", entry.get("cost"))
    return float(single) if isinstance(single, (int, float)) and not isinstance(single, bool) else None


def route_floors():
    """{difficulty: percent of the best usable standing needed} from `route.standing_floor`."""
    return routing.standing_floors(route_cfg().get("standing_floor"))


def explore_free_every():
    """`route.explore_free_one_in`: an unproven worker that costs nothing extra gets one routine task in this many."""
    v = route_cfg().get("explore_free_one_in")
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1 else routing.EXPLORE_FREE_EVERY


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
    disc_tools = _D.merge_tools(disc.get("tools") or [])
    cands, seen = [], set()

    def add(tool, model, usable=True, reason=None, allowance=None, tool_plan=None):
        worker = _canonical(tool, model) if tool else str(model)
        if worker.lower() in seen:
            return None
        seen.add(worker.lower())
        price = _price_for(prices, tool, model, worker)
        cost = entry_cost(price)
        prior_entry = next((prior[k] for k in (worker, model)
                            if k and isinstance(prior.get(k), dict)), {})
        standing = standing_of(prior_entry)
        c = {"worker": worker, "tool": tool, "model": model,
             "maker": price.get("maker") or prior_entry.get("maker") or routing.maker_of(model or worker),
             "plan": price.get("plan") or tool_plan,
             "cost": cost,
             "allowance_pct_left": allowance, "usable": usable, "reason": reason,
             "price_source": price.get("source"), "price_date": price.get("date"),
             "standing": standing,
             "standing_source": prior_entry.get("source"), "standing_date": prior_entry.get("date"),
             "aliases": [worker, model, ("%s/%s" % (tool, model)) if tool and model else None,
                         tool if model is None else None]}
        c["aliases"] = [a for a in c["aliases"] if a]
        cands.append(c)
        return c

    for t in disc_tools:
        if not t.get("installed", True):
            continue
        models = t.get("models") or []
        if t.get("with_default"):
            models = [None] + list(models)  # a learned tool's own default model is always a worker
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
    return _D.annotate(cands, records, disc_tools)


def resolve_worker(name, candidates):
    target = str(name or "").lower()
    for c in candidates:
        if target in {str(a).lower() for a in c.get("aliases") or [c["worker"]]}:
            return c
    if "/" in str(name or ""):
        tool, model = str(name).split("/", 1)
        driver = DRIVER_BY_NAME.get(tool) or _D.driver_for(tool)
        if driver is not None:
            return {"worker": str(name), "tool": tool, "model": model,
                    "maker": routing.maker_of(model), "plan": None, "cost": None,
                    "allowance_pct_left": None, "usable": shutil.which(driver["exe"]) is not None,
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
    rows = d.get("only")
    out["only"] = [r for r in rows if isinstance(r, dict) and r.get("provider") and isinstance(r.get("patterns"), list)
                   and r["patterns"]] if isinstance(rows, list) else []
    return out


def apply_limits(candidates, prefs):
    """(kept, excluded): `sisi workers only PROVIDER PATTERN...` leaves only the matching models of
    that provider routable; anything else from it is passed over with the reason."""
    limits = {str(e["provider"]).lower(): e for e in prefs.get("only") or []}
    if not limits:
        return candidates, []
    kept, excluded = [], []
    for c in candidates:
        worker = str(c.get("worker") or "")
        prefix = worker.split("/", 1)[0].lower() if "/" in worker else ""
        entry = limits.get(prefix)
        if entry is None:
            kept.append(c)
            continue
        model = worker.split("/", 1)[1].lower()
        if any(str(p).lower() in model for p in entry["patterns"]):
            kept.append(c)
        else:
            excluded.append((worker, "outside the user's own limit on %s to %s%s"
                             % (entry["provider"], ", ".join(str(p) for p in entry["patterns"]),
                                (" (%s)" % entry["why"]) if entry.get("why") else "")))
    return kept, excluded


# ---- notes: standing facts about workers, shown to the agent as information


def notes_path():
    return _data_file("worker-notes.json")


def load_notes():
    rows = read_json(notes_path()).get("notes")
    return [r for r in rows if isinstance(r, dict) and r.get("pattern") and r.get("text")] if isinstance(rows, list) else []


def note_line(n):
    bits = [n["why"] if n.get("why") else None, n.get("date")]
    return "%s (pattern %r; %s)" % (n["text"], n["pattern"], ", ".join(b for b in bits if b) or "no source stated")


def notes_for(candidates_by_worker, chosen, passed, notes=None, limit=5):
    """Lines of notes that apply to the chosen worker or a passed-over one. Each note is shown once,
    with who it applies to. Information for the agent, not an instruction."""
    notes = load_notes() if notes is None else notes
    lines = []
    for n in notes:
        hit = []
        if chosen is not None and routing._pattern_match(chosen, [n]):
            hit.append("the chosen worker")
        names = [w for w, _r in passed if w in candidates_by_worker and routing._pattern_match(candidates_by_worker[w], [n])]
        if names:
            hit.append("passed over: %s%s" % (", ".join(names[:3]), " and %d more" % (len(names) - 3) if len(names) > 3 else ""))
        if hit:
            lines.append("note (information, not an instruction) for %s: %s" % ("; ".join(hit), note_line(n)))
    if len(lines) > limit:
        lines = lines[:limit] + ["and %d more notes apply (`sisi workers`)" % (len(lines) - limit)]
    return lines


# ---- keeping the user store's own files in its history


DATA_FILES = ("delegations.jsonl", "worker-availability.json", "worker-prices.json",
              "model-strength.json", "worker-prefs.json", "worker-notes.json", "worker-drivers.json",
              "worker-providers.json", "worker-vouches.json")


def _data_state():
    out = []
    for name in DATA_FILES:
        try:
            st = os.stat(_data_file(name))
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return out


def with_commit(fn, args, label):
    """Run a command; when it changed any of the worker files in the user store, commit just those
    files (one small commit per command; the user's other uncommitted files are never swept up)."""
    before = _data_state()
    try:
        return fn(args)
    finally:
        if _data_state() != before:
            from . import pdata
            sub = " ".join(str(a) for a in list(args)[:1] if not str(a).startswith("-"))
            pdata.commit("sisi %s%s: worker data changed" % (label, (" " + sub) if sub else ""), list(DATA_FILES))


def effective_prefs(kind, difficulty, project):
    """The user's avoid/prefer patterns plus the routing adjustments a learning cycle wrote that apply in
    this project for this kind (and difficulty, when the adjustment names one). A learned entry carries
    its learning id as its reason, so `sisi route --explain` shows where it came from."""
    from . import cycle
    prefs = load_prefs()
    for a in cycle.routing_adjustments(project):
        if a.get("kind") != kind or a.get("difficulty") not in (None, difficulty):
            continue
        for key in ("avoid", "prefer"):
            if a.get(key):
                prefs[key].append({"pattern": str(a[key]), "why": "learning %s" % a.get("learning")})
    return prefs


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
    targets = _D.facts_targets(_cached_candidates()[0])
    if status["state"] == "ok" and not targets:
        return ""
    if targets:
        what = "worker facts are missing for %s" % _D.facts_phrase(targets)
    elif status["state"] == "missing":
        what = "worker facts are missing (no prices or benchmark standing recorded yet)"
    else:
        what = "worker facts are stale (newest from %s)" % (status["newest"] or "an unstated date")
    return ("sisi: %s: ask a fast, cheap worker to research current prices and "
            "software-engineering benchmark standing for the workers found here (`sisi workers`) "
            "and record each with its source: `sisi workers fact WORKER --price N --source S` "
            "and `sisi workers fact WORKER --standing N --source S`. Until then routing "
            "goes by the judged record alone." % what)


def estimate_cost(tokens, price_entry):
    """Estimated cost from a known per-million-token price, or None. The caller labels it estimated."""
    if not isinstance(tokens, (int, float)) or not isinstance(price_entry, dict):
        return None
    per_million = entry_cost(price_entry)
    if per_million is None:
        return None
    return float(tokens) / 1000000.0 * per_million


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
        if judged or c.get("price_source") or c.get("standing") is not None or c.get("unproven_ok"):
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
    if cand.get("host_mechanism"):
        return cand["host_mechanism"]
    if cand.get("host_native"):
        return "use the host's own subagent tool with model %s" % (cand.get("model") or cand["worker"])
    if host and cand.get("tool") == host:
        return "use the host's own subagent mechanism (the worker belongs to the host tool)"
    if host and workers_cfg().get("host_cross_provider"):
        return "use the host's cross-provider delegation"
    return "use `sisi delegate` (the host has no delegation of its own for this worker)"


def same_model(a, b):
    """Do two spellings name one model? Equal, or one an alias contained in the other's full name
    (a short name against a dated id). Neither side may be empty or shorter than three characters."""
    a, b = str(a or "").strip().lower(), str(b or "").strip().lower()
    if len(a) < 3 or len(b) < 3:
        return False
    a, b = a.rsplit("/", 1)[-1], b.rsplit("/", 1)[-1]
    return a == b or a in b or b in a


def same_worker(chosen, routed, provider_named=False):
    """Do a delegation's worker and the router's recommendation name one worker? As same_model, except that a
    model of the same name under another provider is another worker when the call names its provider."""
    if provider_named and "/" in str(routed) and "/" in str(chosen) \
            and str(chosen).split("/", 1)[0].lower() != str(routed).split("/", 1)[0].lower():
        return False
    return same_model(chosen, routed)


def _own_workers(candidates, own_model):
    return [c["worker"] for c in candidates
            if own_model and any(same_model(own_model, x) for x in
                                 [c.get("worker"), c.get("model")] + list(c.get("aliases") or []))]


def recommend(kind, difficulty, cwd=None, own_model=None):
    """The router's pick for a kind of task as (worker, mechanism line, usable_count), reading only
    the cached discovery and the record, never printing. The session's own model is not offered:
    delegating to the same model is what orchestration is meant to avoid. (None, None, 0) when no
    other worker is usable."""
    records = read_records()
    candidates, _tools = _cached_candidates(records)
    _D.apply_allowances(candidates, cached_only=True)  # a hook never asks a provider; the last reading stands
    candidates, _cold, _x = routable_candidates(candidates, records)
    prefs = effective_prefs(kind, difficulty, cwd or os.getcwd())
    candidates, _limited = apply_limits(candidates, prefs)
    result = routing.choose(candidates, records, read_availability(), kind, difficulty, now=time.time(),
                            exclude=_own_workers(candidates, own_model), avoid=prefs["avoid"], prefer=prefs["prefer"],
                            floors=route_floors(), explore_free_every=explore_free_every())
    choice = result["choice"]
    if choice is None:
        return None, None, 0
    return choice["worker"], mechanism_for(choice), 1


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
                     "until then routing goes on price and benchmark standing alone.")
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
              "Accepted rate counts results that passed the check and were not reported wrong later. "
              "Checked well is the share of those verified by tests, a read, or a second reviewer; "
              "the rest were accepted on a lighter check.", "",
              "| Type | Diff | Worker | Attempts | Accepted rate | Checked well | Later wrong | Median min |",
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


def _down_provider(cand):
    """The provider of a worker (the part of its id before the first slash) when it differs from its tool: a
    tool that carries several providers has a login, a plan and an allowance for each."""
    prov = routing.provider_of(cand.get("worker"))
    return prov if prov and prov != str(cand.get("tool") or "").lower() else None


def _provider_to_mark(cand):
    """The provider a failure of this worker marks down: its own (a tool that carries several, or a host's), or
    the part of its model before a slash."""
    model = str(cand.get("model") or "")
    return _down_provider(cand) or (model.split("/", 1)[0] if "/" in model else None)


def _down_keys(cand, reason):
    keys = [cand["worker"]]
    model = str(cand.get("model") or "")
    prov = _down_provider(cand)
    if reason == "auth" and cand.get("tool"):
        keys.append(prov or cand["tool"])  # one provider's login, or the tool's own when it has no providers
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
    prefs = effective_prefs(kind, difficulty, cwd)
    if cand is not None and cand.get("host_native"):
        notes.append("sisi: %s is a host-native worker; start it with the host's own subagent tool "
                     "(`sisi delegate` runs only command-line tools)" % cand["worker"] if not cand.get("host_mechanism") else
                     "sisi: %s is reached through the host, not by `sisi delegate`: %s" % (cand["worker"], cand["host_mechanism"]))
        return None, None, notes
    limited = apply_limits(candidates, prefs)[0]
    candidates = [c for c in limited if not c.get("host_native")]
    while True:
        if cand is None:
            prefs = effective_prefs(kind, difficulty, cwd)
            result = routing.choose(candidates, read_records(), read_availability(), kind, difficulty,
                                    review_of=review_of, now=time.time(), exclude=tried,
                                    avoid=prefs["avoid"], prefer=prefs["prefer"], floors=route_floors(),
                                    explore_free_every=explore_free_every())
            cand = result["choice"]
            if cand is None:
                native = routing.choose([c for c in limited if c.get("host_native")], read_records(), read_availability(),
                                        kind, difficulty, now=time.time(), exclude=tried,
                                        avoid=prefs["avoid"], prefer=prefs["prefer"])["choice"]
                if native is not None:  # every command-line worker is out: the host's own subagents take it, at once
                    notes.append("sisi: no command-line worker remains for kind %s at difficulty %s. Fall back now with the "
                                 "same brief: %s (model %s). Do not ask the person and do not report this to them: "
                                 "which worker is out is internal." % (kind, difficulty, mechanism_for(native), native.get("model") or native["worker"]))
                else:
                    notes.append("sisi: no usable worker remains for kind %s at difficulty %s" % (kind, difficulty))
                return None, None, notes
        tried.append(cand["worker"])
        if "contributor" in str(cand.get("model") or cand["worker"]).lower():
            notes.append("sisi: refusing %s: its id contains 'contributor', a tier that trains on prompts"
                         % cand["worker"])
            return None, None, notes
        driver = DRIVER_BY_NAME.get(cand.get("tool") or "") or _D.driver_for(cand.get("tool"))
        held = _D.held_note(cand) if driver is None else None
        if held:  # a learned driver not yet proved or approved: not a missing tool, and never run
            notes.append(held)
            cand = None
            continue
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
        failure = failure_for(out + "\n" + err, cand, rc)
        if failure is not None:
            reason, note, retry = failure
            until = parse_reset(out + "\n" + err)  # the time the message itself names, when it names one
            if until is None and reason == "limit":
                until = _D.limit_until(cand)  # else the provider's allowance probe, when one is defined
            record_down(_down_keys(cand, reason), reason, note, retry_after_s=None if until else retry, until_ts=until,
                        provider=_provider_to_mark(cand))
            mark_discovery_stale()
            notes.append("%s is unavailable (%s: %s); trying the next choice" % (cand["worker"], reason, note))
            cand = None
            continue
        tokens, cost = extract_usage(out + "\n" + err)
        tokens = _D.tokens_from(driver, out + "\n" + err) if tokens is None else tokens
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


def strength_scores(candidates):
    """{worker: (standing, how)} from the stored benchmark standing (model-strength.json, each figure with
    its source and date). Only standings are here: the accepted rate measured from judged delegations is a
    different scale and is never mixed in. No shipped ranking: a model with no stored standing is simply
    absent, and its strength is unknown."""
    prior = load_strength_prior()
    out = {}
    for c in candidates:
        for key in [c["worker"], c.get("model")] + list(c.get("aliases") or []):
            standing = standing_of(prior.get(key)) if key else None
            if standing is not None:
                entry = prior[key]
                out[c["worker"]] = (standing, "benchmark standing (%s, %s)" % (entry.get("source") or "no source stated",
                                                                            entry.get("date") or "no date stated"))
                break
    return out


def _cached_candidates(records=None):
    """Candidates from the discovery cache only: session start must stay fast and run no tool."""
    cached = load_discovery()
    return build_candidates(cached, read_records() if records is None else records), cached.get("tools") or []


def is_subagent_payload(payload):
    return store.is_subagent_payload(payload)


def _with_facts(lines):
    line = facts_line()
    return lines + [line] if line else lines


def session_lines(model, payload=None):
    """Plain lines at session start about delegating, or nothing for a session another agent
    started. When the main model's standing is unknown it says nothing about whether to delegate:
    a missing number never argues against orchestrating. At most one extra line asks for worker
    facts to be researched when they are missing or stale (the caller shows these lines once per
    session). Uses only cached discovery and the record."""
    if not model or is_subagent_payload(payload or {}):
        return []
    records = read_records()
    candidates, _tools = _cached_candidates(records)
    waiting = len(unjudged_runs(records))
    suffix = ""
    if waiting == 1:
        suffix = " One delegation is waiting for a judgement: run `sisi workers`, then `sisi delegate judge`."
    elif waiting:
        suffix = " %d delegations are waiting for a judgement: run `sisi workers` to see, then `sisi delegate judge`." % waiting
    scores = strength_scores(candidates) if candidates else {}
    cand = resolve_worker(model, candidates) if candidates else None
    own = scores.get(cand["worker"]) if cand else None
    if own is None:
        prior = load_strength_prior().get(model)
        if standing_of(prior) is not None:
            own = (standing_of(prior), "benchmark standing (%s, %s)" % (prior.get("source") or "no source stated",
                                                                       prior.get("date") or "no date stated"))
    lines = []
    if own is not None:
        best_score = max([s for s, _h in scores.values()] + [own[0]])
        if own[0] >= best_score - routing.STRONG_BAND:
            lines.append("sisi: this session's model (%s) is among the strongest available here (%s): plan, ask `sisi route` who "
                         "should do each piece, start that worker with this tool's own subagents (use `sisi delegate` "
                         "only if it has none), and judge what comes back.%s" % (model, own[1], suffix))
        else:
            stronger = [w for w, _s in sorted(scores.items(), key=lambda kv: -kv[1][0])[:3] if scores[w][0] > own[0]]
            lines.append("sisi: this session's model (%s) stands at %g (%s)%s. Ask `sisi route` who should do each piece, "
                         "start that worker with this tool's own subagents (use `sisi delegate` only if it has none), "
                         "and judge what comes back.%s"
                         % (model, own[0], own[1],
                            ("; stronger models available here, strongest first: %s" % ", ".join(stronger)) if stronger else "",
                            suffix))
    elif suffix:
        lines.append("sisi:" + suffix)
    return _with_facts(lines)


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


def _price_bits(p):
    bits = []
    if p.get("plan"):
        bits.append("%s plan" % ("flat-rate" if p["plan"] == "flat" else "per-use"))
    if isinstance(p.get("price_in"), (int, float)) and isinstance(p.get("price_out"), (int, float)):
        bits.append("%g in / %g out per million tokens (blended %g at %g:1 input to output)"
                    % (p["price_in"], p["price_out"], entry_cost(p), price_blend()))
    elif entry_cost(p) is not None:
        bits.append("%g per million tokens (one blended figure)" % entry_cost(p))
    if p.get("source"):
        bits.append("from %s, %s" % (p["source"], p.get("date") or "no date stated"))
    return bits


def _price_lines(tool_name, models, prices, shown_keys=None):
    lines = []
    tool_price = _price_for(prices, tool_name, None, None)
    shown = set()
    for m in models or [None]:
        p = _price_for(prices, tool_name, m, _canonical(tool_name, m)) or tool_price
        if not p:
            continue
        if shown_keys is not None:
            shown_keys.update(k for k in (m, _canonical(tool_name, m)) if k)
        key = json.dumps(p, sort_keys=True)
        if key in shown:
            continue
        shown.add(key)
        bits = _price_bits(p)
        if bits:
            lines.append("  price%s: %s" % ((" for %s" % m) if m and len(models) > 1 else "", "; ".join(bits)))
    return lines


def cmd_workers(args=()):
    args = list(args)
    if args[:1] == ["fact"]:
        return _cmd_fact(args[1:])
    if args[:1] in (["avoid"], ["prefer"]):
        return _cmd_pref(args[0], args[1:])
    if args[:1] == ["only"]:
        return _cmd_only(args[1:])
    if args[:1] == ["note"]:
        return _cmd_note(args[1:])
    if args[:1] == ["down"]:
        return _cmd_down(args[1:])
    if args[:1] == ["up"]:
        return _cmd_up(args[1:])
    if args[:1] == ["import"]:
        return _cmd_import(args[1:])
    if args[:1] in (["plan"], ["vouch"], ["allowance"], ["signature"]):
        return _D.cmd_provider(args)
    if args[:1] == ["learn"]:
        return _D.cmd_learn(args[1:])
    if args[:1] == ["forget"]:
        return _D.cmd_forget(args[1:])
    migrate_standing_facts()
    disc = discover(force="--refresh" in args)
    disc = dict(disc, tools=_D.merge_tools(disc.get("tools") or []))
    _D.refresh_allowances(force=True)  # a defined allowance probe is read now: `sisi workers` was asked
    records = read_records()
    avail = read_availability()
    prices = load_prices()
    shown_keys = set()
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
        for line in _D.tool_lines(t):
            print(line)
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
        for line in _price_lines(t["name"], models, prices, shown_keys):
            print(line)
        if t.get("plan") == "flat" and not _price_lines(t["name"], models, prices):
            print("  price: flat-rate plan (the tool reports an allowance, so one more task costs nothing extra)")
    if missing:
        print("Not found on PATH: %s" % ", ".join(missing))
    own_prices = prices.get("models") if isinstance(prices.get("models"), dict) else {}
    for worker, entry in sorted(own_prices.items()):
        bits = _price_bits(entry) if isinstance(entry, dict) and worker not in shown_keys else []
        if bits:
            print("price for %s: %s" % (worker, "; ".join(bits)))
    standings = sorted(((standing_of(e), k, e) for k, e in load_strength_prior().items() if standing_of(e) is not None),
                       key=lambda t: (-t[0], t[1]))
    if standings:
        print("Benchmark standing (a published figure; routing compares it only with other workers' standing, "
              "never with the accepted rate measured below):")
        for standing, worker, entry in standings:
            print("  benchmark standing %g - %s: %s (%s)" % (standing, worker, entry.get("source") or "no source stated",
                                                          entry.get("date") or "no date stated"))
    down_now = [(k, v) for k, v in sorted(avail.items()) if isinstance(v, dict)]
    for k, v in down_now:
        if k in {t["name"] for t in disc.get("tools") or []}:
            continue
        print("Unavailable: %s - %s, next try %s%s" % (k, v.get("reason") or "down", _when(v.get("retry_at")),
                                                       (" (%s)" % v["note"]) if v.get("note") else ""))
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
    for entry in prefs["only"]:
        print("Only on %s: %s%s" % (entry["provider"], ", ".join(str(p) for p in entry["patterns"]),
                                    (" (%s)" % entry["why"]) if entry.get("why") else ""))
    for n in load_notes():
        print("Note (information for the agent): %s" % note_line(n))
    for ln in _D.vouch_lines():
        print(ln)
    line = facts_line()
    if line:
        print(line)
    for ln in digest_lines(records):
        print(ln)
    line = override_line(records)
    if line:
        print(line)
    return 0


def _down_now(avail, now):
    """[(key, entry)] for every provider or worker marked down whose retry time is still ahead."""
    return [(k, v) for k, v in sorted((avail or {}).items())
            if isinstance(v, dict) and float(v.get("retry_at") or 0) > now]


def _down_lines(down, limit=3):
    """One line naming what is down and when each is due for another try, or nothing."""
    if not down:
        return []
    shown = ["%s (%s, next try %s)" % (k, v.get("reason") or "down", _when(v.get("retry_at")))
             for k, v in down[:limit]]
    more = " and %d more" % (len(down) - limit) if len(down) > limit else ""
    return ["down now: %s%s" % ("; ".join(shown), more)]


def _route_setup(args, derived=None):
    kind = _opt(args, "--kind") or (derived or {}).get("kind")
    if kind and not derived:
        from . import unitguard
        known = unitguard.ledger_kinds()
        if known and kind not in known:
            print("sisi route: kind %r is not one the ledger knows. Kinds: %s (building: %s)."
                  % (kind, ", ".join(known), ", ".join(unitguard._list("build_kinds"))), file=sys.stderr)
            return None
    difficulty = _opt(args, "--difficulty")
    if difficulty is None and derived:
        difficulty = derived.get("difficulty")
    if not kind or difficulty is None:
        return None
    try:
        difficulty = int(difficulty)
    except ValueError:
        return None
    if difficulty not in (1, 2, 3):
        return None
    return kind, difficulty


def retry_context(retry_id, records=None):
    """What `sisi route --retry-of ID` needs from the judged record: the attempt (ID is an attempt id, or the
    id of a run that was judged), its kind and difficulty, and how many results in the retry chain behind it
    were rejected in a row, newest first, with the workers that produced them. None when ID is unknown or
    its run is not judged yet."""
    records = read_records() if records is None else records
    attempts = {r["id"]: r for r in records if r.get("kind") == "attempt" and r.get("id")}
    by_run = {r["run_id"]: r for r in attempts.values() if r.get("run_id")}
    a = attempts.get(retry_id) or by_run.get(retry_id)
    if a is None:
        return None
    rejected, seen, cur = [], set(), a
    while cur is not None and cur["id"] not in seen:
        seen.add(cur["id"])
        if cur.get("outcome") != "rejected":
            break
        rejected.append(cur.get("worker"))
        cur = attempts.get(cur.get("retry_of"))
    return {"attempt": a, "kind": a.get("type"), "difficulty": a.get("difficulty"), "rejected": rejected}


RETRY_BRIEF_LINE = ("retry: most failures are brief failures. Improve the brief (what was missing, what is known now, "
                    "the exact failure) and check it with `sisi delegate check`, then give it to this same worker once more.")


def _route_retry(args, ctx, kind, difficulty, candidates, records, prefs):
    """Print the pick for a retry and return it (or None). The ladder is routing.retry_choice: the same worker
    with a better brief after the first rejection, then a worker whose evidence is strictly better, then the
    strongest known."""
    rejected = ctx["rejected"]
    res = routing.retry_choice(candidates, records, read_availability(), kind, difficulty, rejected[0], len(rejected),
                               now=time.time(), avoid=prefs["avoid"], prefer=prefs["prefer"], floors=route_floors())
    pick = res["choice"]
    if pick is None:
        print("no usable worker for kind %s at difficulty %d after a rejection by %s"
              % (kind, difficulty, ", ".join(sorted(set(rejected)))))
        return None
    print(pick["worker"])
    print("mechanism: %s" % mechanism_for(pick))
    for line in _D.unproven_lines(pick):
        print(line)
    if res["step"] == "same":
        print(RETRY_BRIEF_LINE)
    else:
        print("retry after %d rejection(s) by %s: %s" % (len(rejected), ", ".join(sorted(set(rejected))), {
            "better": "a worker with strictly better evidence than the rejected one",
            "strongest": "nobody has better evidence, so the strongest known usable worker",
            "only": "nobody else is usable, so the same worker once more"}[res["step"]]))
    return pick


def route_decision(kind, difficulty, worker, retry_of=None):
    """Write the routing decision for the session this command runs in (see orchestration.record_route)."""
    try:
        from . import orchestration
        orchestration.record_route(kind, difficulty, worker, os.getcwd(), retry_of)
    except Exception as e:
        store.log_error("route-decision", e)


def cmd_route(args=()):
    retry_id = _opt(args, "--retry-of")
    ctx = None
    if retry_id:
        ctx = retry_context(retry_id)
        if ctx is None:
            print("sisi route: no judged delegation with id %s (judge the run first: `sisi delegate judge`)" % retry_id,
                  file=sys.stderr)
            return 1
    setup = _route_setup(args, ctx)
    if setup is None:
        print("usage: sisi route --kind K --difficulty 1|2|3 [--review-of WORKER] [--explain] | --retry-of ID")
        return 1
    kind, difficulty = setup
    records = read_records()
    everything = build_candidates()
    _D.apply_allowances(everything)  # a defined allowance probe older than a few minutes is read again
    candidates, cold, excluded = routable_candidates(everything, records)
    prefs = effective_prefs(kind, difficulty, os.getcwd())
    everyone = candidates
    candidates, limited = apply_limits(candidates, prefs)
    if ctx is not None and ctx["rejected"]:
        pick = _route_retry(args, ctx, kind, difficulty, candidates, records, prefs)
        route_decision(kind, difficulty, pick["worker"] if pick else None, ctx["attempt"]["id"])
        return 0 if pick else 1
    result = routing.choose(candidates, records, read_availability(), kind, difficulty,
                            review_of=_opt(args, "--review-of"), now=time.time(),
                            avoid=prefs["avoid"], prefer=prefs["prefer"], floors=route_floors(),
                            explore_free_every=explore_free_every())
    result["passed_over"] = list(result["passed_over"]) + limited
    by_worker = {c["worker"]: c for c in everyone}
    down = _down_now(read_availability(), time.time())
    if result["choice"] is None:
        route_decision(kind, difficulty, None, ctx["attempt"]["id"] if ctx else None)
        print("no usable worker for kind %s at difficulty %d" % (kind, difficulty))
        for line in _down_lines(down):
            print(line)
        print("nothing is usable right now: the main agent does this task itself meanwhile, "
              "and tries `sisi route` again after the next-try time above%s."
              % ("" if down else " or once a worker is recorded or fixed (`sisi workers`)"))
        if "--explain" in args:
            for line in routing.explain_choice(result, kind, difficulty)[1:]:
                print(line)
        return 1
    route_decision(kind, difficulty, result["choice"]["worker"], ctx["attempt"]["id"] if ctx else None)
    print(result["choice"]["worker"])
    print("mechanism: %s" % mechanism_for(result["choice"]))
    for line in _D.unproven_lines(result["choice"]):
        print(line)
    for line in _down_lines(down):
        print(line)
    head = 2 + len(_D.unproven_lines(result["choice"])) + len(_down_lines(down))
    explain = "--explain" in args
    # Notes for the chosen worker always print; notes for workers passed over only with --explain.
    # Plain output stays within 6 lines: the worker, the mechanism, what is down, then the notes.
    for line in notes_for(by_worker, result["choice"], result["passed_over"] if explain else [],
                          limit=5 if explain else max(1, 5 - head)):
        print(line)
    if explain:
        for line in routing.explain_choice(result, kind, difficulty):
            print(line)
        if excluded:
            print("%d discovered model(s) with no judged record, known price or benchmark prior "
                  "are not candidates" % excluded)
        if cold:
            print("cold start: no worker here has a judged record, a known price or a benchmark "
                  "prior yet, so nothing is known yet about this pick. "
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
    spent = _D.apply_allowances(candidates)
    explicit = None
    worker = _opt(args, "--worker")
    if worker:
        explicit = resolve_worker(worker, candidates)
        if explicit is None:
            print("sisi delegate: no such worker found here: %s (see `sisi workers`)" % worker, file=sys.stderr)
            return 1
        if routing.provider_of(explicit["worker"]) in spent:  # its allowance is read as spent: another worker, as after a limit
            print("sisi: %s has no allowance left until its reset; choosing another worker" % explicit["worker"])
            explicit = None
    if explicit is None:
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
    for line in _D.unproven_lines(next((c for c in candidates if c["worker"] == rec["worker"]), None)):
        print(line)
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
        run = next((r for r in merged_runs(records) if r.get("id") == run_id), None)
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
               "minutes": run.get("minutes"), "tokens": run.get("tokens"), "tokens_class": run.get("tokens_class"),
               "cost": run.get("cost"), "cost_class": run.get("cost_class"),
               "started": run.get("started"), "ended": run.get("ended"),
               "retry_of": run.get("retry_of"), "note": None,
               "route_worker": run.get("route_worker"), "chosen_against_route": run.get("chosen_against_route")}
        if _opt(args, "--type") or _opt(args, "--kind"):  # a run the host started carries no kind until judged
            rec["type"] = _opt(args, "--type") or _opt(args, "--kind")
        if _opt(args, "--difficulty") in ("1", "2", "3"):
            rec["difficulty"] = int(_opt(args, "--difficulty"))
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
    if rec["outcome"] == "rejected":
        print("next: `sisi route --retry-of %s` names the worker for the retry (the same one with a better brief first, "
              "a stronger one after a second rejection)" % rec["id"])
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
    else:
        print("brief lacks:")
        for title in missing:
            print("  - %s" % title)
        print("`sisi delegate brief` prints the template.")
    advice = brief_contract.advice(text)
    if advice:
        print("advice (does not block):")
        for line in advice:
            print("  - %s" % line)
    return 1 if missing else 0


def _cmd_down(args):
    if not args:
        print("usage: sisi workers down WORKER --reason limit|auth|missing|error [--until DATE|DATETIME] [--note TEXT]")
        return 1
    worker = str(args[0]).strip().lower().rstrip("/")
    reason = _opt(args, "--reason")
    if reason not in REASONS:
        print("usage: sisi workers down WORKER --reason limit|auth|missing|error [--until DATE|DATETIME] [--note TEXT]")
        return 1
    until = _opt(args, "--until")
    until_ts = _parse_time(until) if until is not None else None
    if until is not None and until_ts is None:
        print("sisi: --until wants a date like 2026-12-01 or a time like 2026-12-01T09:00 (add Z or an offset such as +02:00 for a zone)", file=sys.stderr)
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
    if not any(r.get("kind") in ("attempt", "run", "amend", "down", "up") for r in read_records(args[0])):
        print("sisi: warning: %s contains no ledger rows (no line with a kind of attempt, run, amend, "
              "down or up); is it the right file?" % args[0], file=sys.stderr)
    before, after, added = import_ledger(args[0])
    print("imported %d rows from %s (before: %d, after: %d); the original file is unchanged"
          % (added, args[0], before, after))
    return 0


def _cmd_fact(args):
    usage = ("usage: sisi workers fact WORKER --price-in N --price-out N [--plan flat|per-use] [--maker M] --source S [--date YYYY-MM-DD]\n"
             "       sisi workers fact WORKER --price N (one blended figure) [--plan ...] [--maker M] --source S\n"
             "       sisi workers fact WORKER --standing 0..100 --source S [--date YYYY-MM-DD]   (--score is the old name)")
    if not args:
        print(usage)
        return 1
    worker = args[0]
    source = _opt(args, "--source")
    date = _opt(args, "--date") or time.strftime("%Y-%m-%d", time.localtime())
    price, price_ok = _number_opt(args, "--price")
    price_in, in_ok = _number_opt(args, "--price-in")
    price_out, out_ok = _number_opt(args, "--price-out")
    standing, standing_ok = _number_opt(args, "--standing")
    old_name, old_ok = _number_opt(args, "--score")
    if standing is None:
        standing = old_name
    if not (price_ok and in_ok and out_ok and standing_ok and old_ok):
        print(usage)
        return 1
    if (price_in is None) != (price_out is None) or (price is not None and price_in is not None):
        print("sisi: record either --price-in with --price-out, or one blended --price, not a mix", file=sys.stderr)
        return 1
    if price is None and price_in is None and standing is None:
        print(usage)
        return 1
    if min([v for v in (price, price_in, price_out) if v is not None] or [0]) < 0:
        print("sisi: a price cannot be negative", file=sys.stderr)
        return 1
    if not source:
        print("sisi: a fact needs its --source (where the figure came from); nothing recorded", file=sys.stderr)
        return 1
    if standing is not None and not (0 <= standing <= 100):
        print("sisi: --standing wants a number from 0 to 100", file=sys.stderr)
        return 1
    if price is not None or price_in is not None:
        plan = _opt(args, "--plan")
        if plan is not None and plan not in ("flat", "per-use"):
            print("sisi: --plan wants flat or per-use", file=sys.stderr)
            return 1
        prices = load_prices()
        models = prices.get("models") if isinstance(prices.get("models"), dict) else {}
        entry = dict(models.get(worker) or {})
        entry.pop("cost", None)
        if price_in is not None:
            entry.pop("cost_per_million_tokens", None)
            entry.update({"price_in": price_in, "price_out": price_out, "source": source, "date": date})
        else:
            entry.pop("price_in", None)
            entry.pop("price_out", None)
            entry.update({"cost_per_million_tokens": price, "source": source, "date": date})
        if plan:
            entry["plan"] = plan
        maker = _opt(args, "--maker")
        if maker:
            entry["maker"] = maker
        models[worker] = entry
        prices["models"] = models
        write_json(prices_path(), prices)
        if price_in is not None:
            print("recorded price for %s: %g in / %g out per million tokens, blended %g for ranking (from %s, %s)"
                  % (worker, price_in, price_out, entry_cost(entry), source, date))
        else:
            print("recorded price for %s: %g per million tokens (from %s, %s)" % (worker, price, source, date))
    if standing is not None:
        migrate_standing_facts()
        data = read_json(strength_path())
        models = data.get("models") if isinstance(data.get("models"), dict) else {}
        entry = dict(models.get(worker) or {})
        entry.pop("score", None)
        entry.update({"standing": standing, "source": source, "date": date})
        maker = _opt(args, "--maker")
        if maker:
            entry["maker"] = maker
        models[worker] = entry
        data["models"] = models
        write_json(strength_path(), data)
        print("recorded benchmark standing for %s: %g (from %s, %s)" % (worker, standing, source, date))
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


def _cmd_only(args):
    usage = "usage: sisi workers only PROVIDER PATTERN [PATTERN...] --why TEXT | only PROVIDER --remove"
    plain = _positional(args, ("--why",))
    if not plain:
        print(usage)
        return 1
    provider, patterns = plain[0].strip().lower().rstrip("/"), plain[1:]
    prefs = load_prefs()
    rows = [e for e in prefs["only"] if str(e["provider"]).lower() != provider]
    if "--remove" in args:
        removed = len(rows) != len(prefs["only"])
        _store_only(rows)
        print("limit on %s removed" % provider if removed else "no limit was recorded for %s" % provider)
        return 0
    if not patterns:
        print(usage)
        return 1
    why = _opt(args, "--why")
    rows.append({"provider": provider, "patterns": patterns, "why": why})
    _store_only(rows)
    print("only %s routable from %s%s" % (", ".join(patterns), provider, (" (%s)" % why) if why else ""))
    return 0


def _store_only(rows):
    d = read_json(prefs_path())
    d["only"] = rows
    write_json(prefs_path(), d)


def _positional(args, value_opts):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in value_opts:
            skip = True
        elif not a.startswith("--"):
            out.append(a)
    return out


def _cmd_note(args):
    usage = ('usage: sisi workers note PATTERN "TEXT" --why SOURCE | note PATTERN --remove | note (lists)')
    plain = _positional(args, ("--why",))
    notes = load_notes()
    if not plain:
        for n in notes:
            print("note: %s" % note_line(n))
        if not notes:
            print("no worker notes recorded")
        return 0
    pattern = plain[0]
    if "--remove" in args:
        keep = [n for n in notes if n["pattern"] != pattern]
        write_json(notes_path(), {"notes": keep})
        print("removed %d note(s) for %r" % (len(notes) - len(keep), pattern))
        return 0
    if len(plain) < 2:
        print(usage)
        return 1
    why = _opt(args, "--why")
    if not why:
        print("sisi: a note needs its --why (where the fact came from); nothing recorded", file=sys.stderr)
        return 1
    notes = [n for n in notes if not (n["pattern"] == pattern and n["text"] == plain[1])]
    notes.append({"pattern": pattern, "text": plain[1], "why": why, "date": time.strftime("%Y-%m-%d", time.localtime())})
    write_json(notes_path(), {"notes": notes})
    print("note recorded for %r (from %s)" % (pattern, why))
    return 0
