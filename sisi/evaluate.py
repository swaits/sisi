"""The evaluation harness: benchmark cases, isolated replay, policy comparison, independent judging.

Cases live in the user store under ``benchmarks/<id>.json``; run results are appended to
``eval-results.jsonl`` there. Nothing here replays in the user's working tree: every replay
checks the named commit out into a temporary git worktree and removes it afterwards.

Seams for the other parts of sisi (plain functions, see docs/evaluation.md):
  capture_case(unit_record)          called when a work unit closes
  validate_check(case)               called by the learning cycle before it promotes a command check
  compare_for_candidate(dir, sample) called for a consequential policy change before the owner is asked

Standard library only. Replay of ``task`` cases goes through the existing delegation runner
(``sisi.workers.run_delegation``) unless a caller injects ``worker_runner`` or names a
``--worker-cmd``; tests always inject a fake, so no test calls a real AI tool.
"""
import hashlib, json, math, os, re, shutil, statistics, subprocess, sys, tempfile, time, uuid

from . import paths, store

KINDS = ("check", "task")
SPLITS = ("dev", "holdout", "counterexample")
PASS_OUTCOMES = ("validated", "passed")
FAIL_OUTCOMES = ("failed", "failed-to-fail", "failed-to-pass")
DIFF_LIMIT = 8000
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


# ---------------------------------------------------------------- store and cases

def _store(store_dir=None):
    return store_dir or paths.data()


def benchmarks_dir(store_dir=None):
    return os.path.join(_store(store_dir), "benchmarks")


def results_path(store_dir=None):
    return os.path.join(_store(store_dir), "eval-results.jsonl")


def _eval_config(store_dir=None):
    cfg = {"timeout_s": 60, "worker_timeout_s": 600, "max_cost_per_run": None}
    try:
        over = store.config().get("eval") or {}
        if isinstance(over, dict):
            cfg.update(over)
    except Exception:
        pass
    try:
        with open(os.path.join(_store(store_dir), "config.json"), encoding="utf-8") as f:
            over = (json.load(f) or {}).get("eval") or {}
        if isinstance(over, dict):
            cfg.update(over)
    except (OSError, ValueError):
        pass
    return cfg


def policy_version(store_dir=None):
    """A short hash naming the policy in a store: the product rulebook plus that store's
    generated rulebook, overlay and config. The same policy content hashes the same."""
    d = _store(store_dir)
    h = hashlib.sha256()
    files = [paths.canon("core.md"),
             os.path.join(d, "generated", "core.md"),
             os.path.join(d, "config.json")]
    overlay = os.path.join(d, "overlay")
    if os.path.isdir(overlay):
        for base, dirs, names in os.walk(overlay):
            dirs.sort()
            for n in sorted(names):
                files.append(os.path.join(base, n))
    for p in files:
        try:
            with open(p, "rb") as f:
                h.update(os.path.relpath(p, d).encode() + b"\0" + f.read() + b"\0")
        except OSError:
            h.update(os.path.relpath(p, d).encode() + b"\0missing\0")
    return "p-" + h.hexdigest()[:12]


def validate_case(case):
    """Error strings for a case dict (empty when valid). The seam for command checks is validate_check."""
    errs = []
    if not isinstance(case, dict):
        return ["a case must be a JSON object"]
    cid = case.get("id")
    if not isinstance(cid, str) or not _SAFE_ID.match(cid) or cid in (".", ".."):
        errs.append("id must be a plain name (letters, digits, ._-)")
    if case.get("kind") not in KINDS:
        errs.append("kind must be one of: " + ", ".join(KINDS))
    if case.get("split") not in SPLITS:
        errs.append("split must be one of: " + ", ".join(SPLITS))
    proj = case.get("project") or {}
    if not isinstance(proj, dict) or not proj.get("repo"):
        errs.append("project.repo is required (a path or a remote)")
    if not proj.get("start_commit"):
        errs.append("project.start_commit is required")
    if case.get("kind") == "check" and not proj.get("fix_commit"):
        errs.append("a check case needs project.fix_commit")
    checks = case.get("checks")
    if not isinstance(checks, list) or not checks:
        errs.append("checks must be a non-empty list")
    else:
        for c in checks:
            if not isinstance(c, dict) or not c.get("id") or not c.get("cmd"):
                errs.append("every check needs an id and a cmd")
                break
    if case.get("kind") == "task" and not (case.get("request") or "").strip():
        errs.append("a task case needs the request (the human's words)")
    return errs


def save_case(case, store_dir=None):
    """Write a case to benchmarks/<id>.json in the store. Raises ValueError when invalid."""
    errs = validate_case(case)
    if errs:
        raise ValueError("; ".join(errs))
    d = benchmarks_dir(store_dir)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, case["id"] + ".json")
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)
    return p


def load_cases(store_dir=None, kind=None, split=None):
    """Every stored case, sorted by id, optionally filtered by kind and/or split."""
    d = benchmarks_dir(store_dir)
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, n), encoding="utf-8") as f:
                case = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(case, dict):
            continue
        if kind and case.get("kind") != kind:
            continue
        if split and case.get("split") != split:
            continue
        out.append(case)
    return sorted(out, key=lambda c: str(c.get("id")))


def get_case(case_id, store_dir=None):
    for case in load_cases(store_dir=store_dir):
        if case.get("id") == case_id:
            return case
    hits = [c for c in load_cases(store_dir=store_dir) if str(c.get("id", "")).startswith(str(case_id))]
    return hits[0] if len(hits) == 1 else None


def _safe_part(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "-", str(s or "")).strip("-.")[:60] or "unit"


def capture_case(unit_record, store_dir=None):
    """Turn a closed work-unit record into a stored benchmark case, or None when it cannot be one.

    A unit becomes a case only when it has a repository, a start commit and at least one
    command check (plus a fix commit when there is no request to replay). The case id and its
    dev/holdout split are deterministic, and capturing the same unit twice returns the stored
    case unchanged. This is the seam the unit-close path calls.
    """
    from . import taskset
    if not isinstance(unit_record, dict):
        return None
    u = unit_record.get("unit") if isinstance(unit_record.get("unit"), dict) else unit_record
    uid = u.get("id") or unit_record.get("id")
    if not uid:
        return None
    proj = u.get("project") or {}
    repo = proj.get("repo") if isinstance(proj, dict) else proj
    repo = repo or u.get("repo") or u.get("cwd")
    commits = u.get("commits") or []
    shas = [c.get("sha") if isinstance(c, dict) else c for c in commits]
    start = (u.get("start_commit") or u.get("head_before") or u.get("base_commit")
             or (proj.get("start_commit") if isinstance(proj, dict) else None))
    fix = (u.get("fix_commit") or u.get("head_after") or u.get("head")
           or (proj.get("fix_commit") if isinstance(proj, dict) else None)
           or (shas[-1] if shas else None))
    checks = []
    for c in u.get("checks") or []:
        if isinstance(c, dict) and c.get("cmd"):
            checks.append({"id": c.get("id") or "check", "cmd": c["cmd"],
                           "expect": c.get("expect") or {"exit": 0}})
    request = u.get("request") or u.get("goal") or u.get("title") or ""
    if not repo or not start or not checks:
        return None
    if not request and not fix:
        return None
    cid = "case-" + _safe_part(uid)
    existing = get_case(cid, store_dir=store_dir)
    if existing:
        return existing
    tags = u.get("tags") or ([u["task_class"]] if u.get("task_class") else [])
    if not tags and isinstance(u.get("risk"), dict) and u["risk"].get("profile"):
        tags = [u["risk"]["profile"]]
    split = u.get("split") if u.get("split") in SPLITS else taskset.split_of(cid)
    case = {"id": cid, "kind": "task" if request else "check",
            "source": {"unit": str(uid), "learning": str(u.get("learning") or u.get("learning_id") or "")},
            "project": {"repo": str(repo), "start_commit": str(start), "fix_commit": str(fix or "")},
            "request": request, "checks": checks, "tags": [str(t) for t in tags],
            "split": split, "added": time.strftime("%Y-%m-%d", time.gmtime())}
    if validate_case(case):
        return None
    save_case(case, store_dir=store_dir)
    return case


def import_harvested(store_dir=None, con=None):
    """Create benchmark cases from the harvested task set (grades A/B with a test command).
    Existing case ids are kept. Returns counts."""
    from . import taskset
    if con is None:
        from . import harvest
        con = harvest.connect()
    created = kept = 0
    for case in taskset.benchmark_cases(con):
        if get_case(case["id"], store_dir=store_dir):
            kept += 1
        else:
            save_case(case, store_dir=store_dir)
            created += 1
    return {"created": created, "kept": kept}


def select_cases(cases, split=None, purpose="run", kind=None):
    """Cases for a run. Held-out discipline: a tuning or shadow selection must never include
    holdout cases; asking for the holdout split under either purpose raises ValueError.
    With split=None, tuning/shadow select dev only (callers add counterexamples explicitly)
    and a plain run selects dev plus counterexample, so holdout runs only when named."""
    if split is not None and split not in SPLITS + ("all",):
        raise ValueError("split must be dev, holdout, counterexample or all")
    if split == "holdout" and purpose in ("tuning", "shadow"):
        raise ValueError("held-out cases must not be used for %s" %
                         ("tuning" if purpose == "tuning" else "shadow evaluation"))
    if split == "all" and purpose in ("tuning", "shadow"):
        raise ValueError("held-out cases must not be used for tuning or shadow evaluation")
    out = []
    for case in cases:
        if kind and case.get("kind") != kind:
            continue
        sp = case.get("split")
        if purpose in ("tuning", "shadow") and sp == "holdout":
            continue
        if split and split != "all" and sp != split:
            continue
        if split is None and sp == "holdout":
            continue
        if split is None and purpose == "tuning" and sp != "dev":
            continue
        out.append(case)
    return out


# ---------------------------------------------------------------- results

def append_result(row, store_dir=None):
    """Append one row to eval-results.jsonl (one write call, so rows stay whole)."""
    p = results_path(store_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)
    return row


def read_raw_results(store_dir=None):
    out = []
    try:
        with open(results_path(store_dir), encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except OSError:
        pass
    return out


def read_results(store_dir=None):
    """Run rows in order, with any later independent judgement merged on (judged_by, judge_items)."""
    runs, order = {}, []
    for rec in read_raw_results(store_dir):
        if rec.get("kind") == "run":
            runs[rec.get("id")] = rec
            order.append(rec.get("id"))
        elif rec.get("kind") == "judgement" and rec.get("result_id") in runs:
            runs[rec["result_id"]]["judged_by"] = rec.get("judged_by")
            runs[rec["result_id"]]["judge_items"] = rec.get("items") or []
    return [runs[i] for i in order if i in runs]


# ---------------------------------------------------------------- isolated replay

def _git(cwd, *args, timeout=60):
    try:
        r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or "", r.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def _is_remote(repo):
    return "://" in str(repo) or str(repo).startswith("git@")


def _prepare_repo(case):
    """(repo_path, cleanup, reason). Local paths are used read-only as worktree sources;
    a remote is cloned into a temp dir. ``reason`` explains a not-run outcome."""
    repo = str((case.get("project") or {}).get("repo") or "")
    if not repo:
        return None, (lambda: None), "repository not recorded on the case"
    if _is_remote(repo):
        tmp = tempfile.mkdtemp(prefix="sisi-eval-clone-")
        dest = os.path.join(tmp, "repo")
        r = subprocess.run(["git", "clone", "--quiet", repo, dest], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return None, (lambda: None), "repository could not be cloned: %s" % repo
        return dest, (lambda: shutil.rmtree(tmp, ignore_errors=True)), None
    if not os.path.isdir(repo):
        return None, (lambda: None), "repository gone: %s" % repo
    rc, top, _err = _git(repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        return None, (lambda: None), "repository gone or not a git repository: %s" % repo
    rc, common, _err = _git(top.strip(), "rev-parse", "--path-format=absolute", "--git-common-dir")
    root = top.strip()
    if rc == 0 and common.strip().endswith("/.git"):
        root = common.strip()[:-5] or root
    return root, (lambda: None), None


def _commit_exists(repo, sha):
    if not sha:
        return False
    rc, _o, _e = _git(repo, "cat-file", "-e", str(sha) + "^{commit}")
    return rc == 0


class _Worktree:
    """A detached worktree at one commit inside a temp dir; removed on exit, even on error."""

    def __init__(self, repo, commit):
        self.repo, self.commit = repo, str(commit)
        self.tmp = tempfile.mkdtemp(prefix="sisi-eval-")
        self.path = os.path.join(self.tmp, "wt")
        self.added = False

    def __enter__(self):
        rc, _o, err = _git(self.repo, "worktree", "add", "--detach", "--force", self.path, self.commit,
                           timeout=120)
        if rc == 0:
            self.added = True
            return self.path
        # Fall back to a shared clone checkout when worktrees are unavailable.
        shutil.rmtree(self.path, ignore_errors=True)
        rc2, _o, err2 = _git(self.repo, "clone", "--shared", "--quiet", "--no-checkout",
                             self.repo, self.path, timeout=120)
        if rc2 == 0:
            rc3, _o, err3 = _git(self.path, "checkout", "--quiet", "--detach", self.commit, timeout=120)
            if rc3 == 0:
                return self.path
            err = err3
        else:
            err = err2 or err
        raise RuntimeError("cannot check out %s in a temporary copy: %s" % (self.commit, (err or "").strip()[-300:]))

    def __exit__(self, *exc):
        try:
            if self.added:
                _git(self.repo, "worktree", "remove", "--force", self.path, timeout=60)
                _git(self.repo, "worktree", "prune", timeout=60)
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _run_checks(case, cwd, timeout_s):
    """Run the case's checks in ``cwd``. Returns (rows, timed_out); rows carry exit/passed."""
    rows, timed_out = [], False
    for c in case.get("checks") or []:
        expect = (c.get("expect") or {})
        want = expect.get("exit", 0)
        try:
            want = int(want)
        except (TypeError, ValueError):
            want = 0
        try:
            r = subprocess.run(str(c.get("cmd")), shell=True, cwd=cwd, capture_output=True,
                               text=True, timeout=timeout_s)
            rows.append({"id": c.get("id"), "cmd": c.get("cmd"), "exit": r.returncode,
                         "expected_exit": want, "passed": r.returncode == want})
        except subprocess.TimeoutExpired:
            timed_out = True
            rows.append({"id": c.get("id"), "cmd": c.get("cmd"), "exit": None,
                         "expected_exit": want, "passed": False, "timed_out": True})
        except OSError as e:
            rows.append({"id": c.get("id"), "cmd": c.get("cmd"), "exit": None,
                         "expected_exit": want, "passed": False, "error": str(e)})
    return rows, timed_out


def _checks_at(case, repo, commit, timeout_s):
    """(all_passed, rows, timed_out) for the case's checks at one commit, in a temp worktree."""
    with _Worktree(repo, commit) as wt:
        rows, timed_out = _run_checks(case, wt, timeout_s)
    return (bool(rows) and all(r["passed"] for r in rows)), rows, timed_out


def _replay_check(case, timeout_s):
    """Outcome for a check (or counterexample) case, without recording anything."""
    proj = case.get("project") or {}
    start, fix = proj.get("start_commit"), proj.get("fix_commit")
    repo, cleanup, reason = _prepare_repo(case)
    if repo is None:
        return {"outcome": "not-run", "reason": reason, "check_results": []}
    try:
        for label, sha in (("start_commit", start), ("fix_commit", fix)):
            if case.get("split") == "counterexample" and not sha:
                continue
            if not sha:
                return {"outcome": "not-run", "reason": "commit not recorded: %s" % label, "check_results": []}
            if not _commit_exists(repo, sha):
                return {"outcome": "not-run", "reason": "commit missing: %s (%s)" % (label, sha),
                        "check_results": []}
        results, seen = [], {}
        try:
            for label, sha in (("start", start), ("fix", fix)):
                if not sha:
                    continue
                passed, rows, timed_out = _checks_at(case, repo, sha, timeout_s)
                if timed_out:
                    return {"outcome": "not-run", "reason": "check timed out at the %s commit" % label,
                            "check_results": results + [dict(r, at=label) for r in rows]}
                seen[label] = passed
                results += [dict(r, at=label) for r in rows]
        except RuntimeError as e:
            return {"outcome": "not-run", "reason": str(e), "check_results": results}
        if case.get("split") == "counterexample":
            ok = bool(seen) and all(seen.values())
            return {"outcome": "validated" if ok else "failed",
                    "reason": "" if ok else "counterexample: the check did not still pass",
                    "check_results": results, "at_start": seen.get("start"), "at_fix": seen.get("fix")}
        if seen.get("start"):
            return {"outcome": "failed-to-fail", "reason": "check already passes at the start commit",
                    "check_results": results, "at_start": True, "at_fix": seen.get("fix")}
        if not seen.get("fix"):
            return {"outcome": "failed-to-pass", "reason": "check still fails at the fix commit",
                    "check_results": results, "at_start": False, "at_fix": False}
        return {"outcome": "validated", "reason": "", "check_results": results,
                "at_start": False, "at_fix": True}
    finally:
        cleanup()


def validate_check(case, store_dir=None, timeout_s=None, record=False):
    """Replay a (proposed) command check against the case it came from: it is ``validated``
    only when seen to fail at start_commit and to pass at fix_commit (for a counterexample,
    when it still passes). Accepts a case dict or a stored case id. The learning cycle calls
    this before it promotes a command check. Nothing is recorded unless record=True."""
    resolved = case if isinstance(case, dict) else get_case(case, store_dir=store_dir)
    if resolved is None:
        return {"outcome": "not-run", "reason": "no such case: %s" % case, "check_results": []}
    timeout_s = float(timeout_s or _eval_config(store_dir)["timeout_s"])
    out = _replay_check(resolved, timeout_s)
    out = dict({"case": resolved.get("id")}, **out)
    if record:
        row = _result_row(resolved, out["outcome"], out.get("reason", ""), store_dir,
                          check_results=out.get("check_results") or [])
        append_result(row, store_dir=store_dir)
        out["result_id"] = row["id"]
    return out


def _rulebook_text(policy_dir):
    for p in (os.path.join(policy_dir, "generated", "core.md"), paths.canon("core.md")):
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            continue
    return ""


def _brief_text(case, policy_dir):
    """The worker brief for a task replay: the policy under test, then a full delegation
    contract, so the same text serves an injected runner, a --worker-cmd and `sisi delegate`."""
    checks = "; ".join("%s: %s" % (c.get("id"), c.get("cmd")) for c in case.get("checks") or [])
    return "\n".join([
        "You are a worker. Do this task yourself; do not delegate it further.", "",
        "## Outcome and scope", case.get("request") or "", "",
        "## Context and sources of truth",
        "You work in a temporary copy checked out at the case's start commit. "
        "The rules of the policy under test follow:", "", _rulebook_text(policy_dir), "",
        "## Constraints and interfaces", "Change only what the request needs. Commit nothing.", "",
        "## Acceptance", "These checks must pass on your tree: " + checks, "",
        "## Deliverables and report format", "End with a short report: what changed and the checks you ran.", "",
        "## Files you may change", "Any file in this temporary copy except .sisi-eval-brief.md.", "",
        "## Verification", "Run the acceptance checks above before reporting.", "",
        "## Budget and escalation", "One task, one attempt; stop and say so if blocked.", ""])


def _worker_via_cmd(cmd, brief_text, case, cwd, policy_dir, timeout_s):
    brief_path = os.path.join(cwd, ".sisi-eval-brief.md")
    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(brief_text)
    env = dict(os.environ, SISI_DATA=policy_dir, SISI_EVAL_BRIEF=brief_path,
               SISI_EVAL_REQUEST=case.get("request") or "", SISI_EVAL_POLICY_DIR=policy_dir,
               SISI_EVAL_CASE=case.get("id") or "", SISI_WORKER_RUN="1")
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                       timeout=timeout_s, env=env)
    try:
        os.unlink(brief_path)
    except OSError:
        pass
    return {"worker": None, "text": (r.stdout or r.stderr or "").strip(), "exit": r.returncode}


def _worker_via_delegate(brief_text, case, cwd, policy_dir, worker=None, review_of=None, kind=None):
    """Default task runner: the existing delegate runner, with the policy under test as the
    store its records land in (so a candidate policy never writes to the real store)."""
    from . import workers as W
    candidates = W.build_candidates()
    explicit = W.resolve_worker(worker, candidates) if worker else None
    if worker and explicit is None:
        return None, "no such worker found here: %s" % worker
    if not explicit:
        candidates, _cold, _excluded = W.routable_candidates(candidates, W.read_records())
    kind = kind or ((case.get("tags") or ["impl"])[0])
    try:
        difficulty = int(case.get("difficulty") or 2)
    except (TypeError, ValueError):
        difficulty = 2
    old = os.environ.get("SISI_DATA")
    os.environ["SISI_DATA"] = policy_dir
    try:
        rec, final, notes = W.run_delegation(candidates, kind, difficulty, brief_text, cwd,
                                             explicit=explicit, review_of=review_of, brief_path=None)
    finally:
        if old is None:
            os.environ.pop("SISI_DATA", None)
        else:
            os.environ["SISI_DATA"] = old
    if rec is None:
        return None, "; ".join(notes) or "no usable worker"
    return {"worker": rec.get("worker"), "text": final or "", "exit": rec.get("exit"),
            "tokens": rec.get("tokens"), "tokens_class": rec.get("tokens_class"),
            "cost": rec.get("cost"), "cost_class": rec.get("cost_class")}, None


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _result_row(case, outcome, reason, store_dir, policy_label=None, policy_dir=None,
                worker=None, check_results=(), minutes=None, minutes_class=None, tokens=None,
                tokens_class=None, cost=None, cost_class=None, diff=""):
    policy_dir = policy_dir or _store(store_dir)
    ph = policy_version(policy_dir)
    return {"id": "r-" + uuid.uuid4().hex[:10], "kind": "run", "ts": store.now(),
            "case": case.get("id"), "case_kind": case.get("kind"), "split": case.get("split"),
            "tags": list(case.get("tags") or []),
            "policy": policy_label or ph, "policy_hash": ph,
            "worker": worker, "outcome": outcome, "reason": reason or "",
            "minutes": minutes, "minutes_class": minutes_class or ("measured" if minutes is not None else "unavailable"),
            "tokens": tokens, "tokens_class": tokens_class or ("measured" if tokens is not None else "unavailable"),
            "cost": cost, "cost_class": cost_class or ("measured" if cost is not None else "unavailable"),
            "check_results": list(check_results), "diff": (diff or "")[:DIFF_LIMIT]}


def _replay_task(case, policy_dir, timeout_s, worker_timeout_s, worker_runner, worker_cmd, worker):
    proj = case.get("project") or {}
    start = proj.get("start_commit")
    repo, cleanup, reason = _prepare_repo(case)
    if repo is None:
        return {"outcome": "not-run", "reason": reason}
    try:
        if not start or not _commit_exists(repo, start):
            return {"outcome": "not-run",
                    "reason": "commit missing: start_commit (%s)" % (start or "not recorded")}
        if not case.get("checks"):
            return {"outcome": "not-run", "reason": "case has no checks"}
        brief = _brief_text(case, policy_dir)
        t0 = time.time()
        try:
            with _Worktree(repo, start) as wt:
                err = None
                if worker_runner is not None:
                    try:
                        # Injected runners take (brief_text, cwd, policy_dir=..., case=...).
                        got = worker_runner(brief, wt, policy_dir=policy_dir, case=case)
                    except Exception as e:
                        return {"outcome": "not-run", "reason": "worker failed to run: %s" % e}
                    if got is None:
                        return {"outcome": "not-run", "reason": "no worker available for this task"}
                elif worker_cmd or os.environ.get("SISI_EVAL_WORKER_CMD"):
                    try:
                        got = _worker_via_cmd(worker_cmd or os.environ["SISI_EVAL_WORKER_CMD"],
                                              brief, case, wt, policy_dir, worker_timeout_s)
                    except subprocess.TimeoutExpired:
                        return {"outcome": "not-run", "reason": "worker timed out"}
                    got = dict(got, worker=worker or "worker-cmd")
                else:
                    got, err = _worker_via_delegate(brief, case, wt, policy_dir, worker=worker)
                    if got is None:
                        return {"outcome": "not-run", "reason": err or "no worker available for this task"}
                got = dict(got) if isinstance(got, dict) else {"text": str(got)}
                minutes = _num(got.get("minutes"))
                if minutes is None:
                    minutes = round((time.time() - t0) / 60.0, 4)
                _rc, diff, _e = _git(wt, "diff", "--no-ext-diff", "--no-color", str(start), timeout=60)
                rows, timed_out = _run_checks(case, wt, timeout_s)
                if timed_out:
                    outcome, why = "not-run", "check timed out on the worker's tree"
                elif got.get("exit") not in (None, 0) and not all(r["passed"] for r in rows):
                    outcome, why = "failed", "worker exited %s and its checks do not pass" % got.get("exit")
                elif all(r["passed"] for r in rows):
                    outcome, why = "passed", ""
                else:
                    outcome, why = "failed", "checks do not pass on the worker's tree"
                return {"outcome": outcome, "reason": why, "check_results": rows, "diff": diff,
                        "worker": got.get("worker") or worker, "minutes": minutes,
                        "minutes_class": got.get("minutes_class"),
                        "tokens": got.get("tokens"), "tokens_class": got.get("tokens_class"),
                        "cost": _num(got.get("cost")), "cost_class": got.get("cost_class"),
                        "worker_text": str(got.get("text") or "")[:2000]}
        except RuntimeError as e:
            return {"outcome": "not-run", "reason": str(e)}
    finally:
        cleanup()


def run_case(case, store_dir=None, policy_dir=None, policy_label=None, worker_runner=None,
             worker_cmd=None, worker=None, timeout_s=None, worker_timeout_s=None, record=True):
    """Replay one case (dict or stored id) under one policy and record the result row.
    ``policy_dir`` is the store whose policy is under test (default: the result store)."""
    resolved = case if isinstance(case, dict) else get_case(case, store_dir=store_dir)
    if resolved is None:
        row = {"id": "r-" + uuid.uuid4().hex[:10], "kind": "run", "ts": store.now(), "case": str(case),
               "outcome": "not-run", "reason": "no such case"}
        return append_result(row, store_dir=store_dir) if record else row
    cfg = _eval_config(store_dir)
    timeout_s = float(timeout_s or cfg["timeout_s"])
    worker_timeout_s = float(worker_timeout_s or cfg["worker_timeout_s"])
    policy_dir = policy_dir or _store(store_dir)
    t0 = time.time()
    if resolved.get("kind") == "task":
        out = _replay_task(resolved, policy_dir, timeout_s, worker_timeout_s, worker_runner, worker_cmd, worker)
        row = _result_row(resolved, out["outcome"], out.get("reason", ""), store_dir,
                          policy_label=policy_label, policy_dir=policy_dir,
                          worker=out.get("worker"), check_results=out.get("check_results") or (),
                          minutes=out.get("minutes"), minutes_class=out.get("minutes_class"),
                          tokens=out.get("tokens"), tokens_class=out.get("tokens_class"),
                          cost=out.get("cost"), cost_class=out.get("cost_class"), diff=out.get("diff", ""))
        if out.get("worker_text"):
            row["worker_text"] = out["worker_text"]
    else:
        out = _replay_check(resolved, timeout_s)
        row = _result_row(resolved, out["outcome"], out.get("reason", ""), store_dir,
                          policy_label=policy_label, policy_dir=policy_dir,
                          check_results=out.get("check_results") or (),
                          minutes=round((time.time() - t0) / 60.0, 4))
    return append_result(row, store_dir=store_dir) if record else row


def run_cases(cases, tasks_limit=0, cost_cap=None, **kw):
    """Replay cases in order: at most ``tasks_limit`` task cases, and stop starting task cases
    once the known cost so far reaches ``cost_cap`` (the rest are recorded not-run)."""
    results, tasks_done, spent = [], 0, 0.0
    for case in cases:
        if case.get("kind") == "task":
            if tasks_done >= (tasks_limit or 0):
                continue
            if cost_cap is not None and spent >= float(cost_cap):
                row = _result_row(case, "not-run", "cost cap for this invocation reached",
                                  kw.get("store_dir"), policy_label=kw.get("policy_label"),
                                  policy_dir=kw.get("policy_dir"))
                results.append(append_result(row, store_dir=kw.get("store_dir")))
                continue
            tasks_done += 1
        row = run_case(case, **kw)
        results.append(row)
        if _num(row.get("cost")) is not None:
            spent += float(row["cost"])
    return results


def estimate_task_cost(n_tasks, store_dir=None):
    """Estimated cost of ``n_tasks`` task replays from recorded task-run facts (the median
    known task cost), or unknown when nothing has been recorded. Unavailable is never zero."""
    costs = [float(r["cost"]) for r in read_results(store_dir=store_dir)
             if r.get("case_kind") == "task" and _num(r.get("cost")) is not None]
    if not costs or not n_tasks:
        return {"value": None, "class": "unavailable", "based_on": len(costs),
                "text": "unknown"}
    value = statistics.median(costs) * int(n_tasks)
    return {"value": value, "class": "estimated", "based_on": len(costs),
            "text": "%g (estimated from %d earlier task run(s))" % (value, len(costs))}


# ---------------------------------------------------------------- comparison

def _p95(values):
    if not values:
        return None
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]


def _metrics(rows, ids):
    picked = [rows[i] for i in ids if i in rows]
    passed = sum(1 for r in picked if r.get("outcome") in PASS_OUTCOMES)
    failed = sum(1 for r in picked if r.get("outcome") in FAIL_OUTCOMES)
    not_run = sum(1 for r in picked if r.get("outcome") == "not-run")
    minutes = [float(r["minutes"]) for r in picked if _num(r.get("minutes")) is not None]
    costs = [float(r["cost"]) for r in picked if _num(r.get("cost")) is not None]
    return {"n": len(picked), "passed": passed, "failed": failed, "not_run": not_run,
            "pass_rate": (passed / float(passed + failed)) if (passed + failed) else None,
            "minutes_median": statistics.median(minutes) if minutes else None,
            "minutes_p95": _p95(minutes),
            "cost_median": statistics.median(costs) if costs else None,
            "cost_total": sum(costs) if costs else None,
            "cost_unknown": len(picked) - len(costs)}


def compare_versions(a, b, store_dir=None, split=None, case_ids=None):
    """Compare policy ``a`` (baseline) with ``b`` (candidate) over the cases both ran.
    Cases only one side ran are reported, unavailable cost is never zero, and no single
    score is produced. The verdict says ``not an improvement`` in words when the candidate
    fails cases the baseline passed (SPEC 13.5), and refuses improvement claims on thin data."""
    cases = {c.get("id"): c for c in load_cases(store_dir=store_dir)}
    by_policy = {a: {}, b: {}}
    for r in read_results(store_dir=store_dir):
        pol = r.get("policy")
        if pol not in by_policy:
            continue
        cid = r.get("case")
        if split:
            cs = (cases.get(cid) or {}).get("split", r.get("split"))
            if cs != split:
                continue
        if case_ids is not None and cid not in case_ids:
            continue
        by_policy[pol][cid] = r  # later rows are newer: the latest run per case wins
    ids_a, ids_b = set(by_policy[a]), set(by_policy[b])
    common = sorted(ids_a & ids_b)
    metrics = {a: _metrics(by_policy[a], common), b: _metrics(by_policy[b], common)}
    regressions = [c for c in common if by_policy[a][c].get("outcome") in PASS_OUTCOMES
                   and by_policy[b][c].get("outcome") in FAIL_OUTCOMES]
    gains = [c for c in common if by_policy[a][c].get("outcome") in FAIL_OUTCOMES
             and by_policy[b][c].get("outcome") in PASS_OUTCOMES]
    too_few = len(common) < 5
    ma, mb = metrics[a], metrics[b]
    faster = (ma["minutes_median"] is not None and mb["minutes_median"] is not None
              and mb["minutes_median"] < ma["minutes_median"])
    cheaper = (ma["cost_median"] is not None and mb["cost_median"] is not None
               and mb["cost_median"] < ma["cost_median"])
    if regressions:
        how = " (it is %s, but) " % (" and ".join(x for x, y in
                (("faster", faster), ("cheaper", cheaper)) if y) or "no better on time or cost")
        verdict = ("not an improvement: %s%sfails %d case(s) the baseline passed (%s)"
                   % (b, how if (faster or cheaper) else " ",
                      len(regressions), ", ".join(regressions[:8])))
        if too_few:
            verdict += "; too few common cases to say more"
    elif too_few:
        verdict = "too few common cases (%d, need at least 5): no improvement can be claimed" % len(common)
    elif gains or faster or cheaper:
        bits = []
        if gains:
            bits.append("passes %d case(s) the baseline failed" % len(gains))
        if faster:
            bits.append("is faster (median minutes)")
        if cheaper:
            bits.append("is cheaper (median cost)")
        verdict = "improvement on these cases: %s %s, with no case the baseline passed now failing" % (b, "; ".join(bits))
    else:
        verdict = "no improvement shown on these cases"
    by_class = {}
    for cid in common:
        tags = (cases.get(cid) or {}).get("tags") or by_policy[a][cid].get("tags") or ["untagged"]
        for t in tags:
            by_class.setdefault(str(t), []).append(cid)
    classes = {}
    for t, ids in sorted(by_class.items()):
        classes[t] = {"n": len(ids), "too_few": len(ids) < 5,
                      a: _metrics(by_policy[a], ids), b: _metrics(by_policy[b], ids)}
    return {"a": a, "b": b, "split": split, "common": common,
            "only_a": sorted(ids_a - ids_b), "only_b": sorted(ids_b - ids_a),
            "metrics": metrics, "by_class": classes, "regressions": regressions,
            "gains": gains, "too_few": too_few, "faster": faster, "cheaper": cheaper,
            "verdict": verdict}


def _fmt(v, suffix=""):
    return "unknown" if v is None else ("%g%s" % (v, suffix))


def _rate(m):
    return "unknown" if m["pass_rate"] is None else "%.0f%% (%d/%d)" % (
        100 * m["pass_rate"], m["passed"], m["passed"] + m["failed"])


def format_comparison(comp):
    """The comparison as short text: each speed/cost figure sits beside its counter-metric
    (pass rate), per task class, with missing data named. There is no single score."""
    a, b = comp["a"], comp["b"]
    ma, mb = comp["metrics"][a], comp["metrics"][b]
    lines = ["compare %s (baseline) vs %s (candidate)" % (a, b),
             "common cases: %d%s; only %s ran: %d%s; only %s ran: %d%s" % (
                 len(comp["common"]), " (too few)" if comp["too_few"] else "",
                 a, len(comp["only_a"]), (" (%s)" % ", ".join(comp["only_a"][:8])) if comp["only_a"] else "",
                 b, len(comp["only_b"]), (" (%s)" % ", ".join(comp["only_b"][:8])) if comp["only_b"] else ""),
             "%-18s %-16s %-16s" % ("metric", a, b),
             "%-18s %-16s %-16s" % ("pass rate", _rate(ma), _rate(mb)),
             "%-18s %-16s %-16s" % ("not-run", ma["not_run"], mb["not_run"]),
             "%-18s %-16s %-16s" % ("median minutes", _fmt(ma["minutes_median"]), _fmt(mb["minutes_median"])),
             "%-18s %-16s %-16s" % ("p95 minutes", _fmt(ma["minutes_p95"]), _fmt(mb["minutes_p95"])),
             "%-18s %-16s %-16s" % ("median cost", _fmt(ma["cost_median"]), _fmt(mb["cost_median"])),
             "%-18s %-16s %-16s" % ("cost unknown (n)", ma["cost_unknown"], mb["cost_unknown"])]
    for t, c in list(comp["by_class"].items())[:20]:
        lines.append("class %-14s n=%d%s pass %s -> %s, median min %s -> %s" % (
            t, c["n"], " too few;" if c["too_few"] else ";",
            _rate(c[a]), _rate(c[b]), _fmt(c[a]["minutes_median"]), _fmt(c[b]["minutes_median"])))
    if comp["regressions"]:
        lines.append("now failing, passed before: %s" % ", ".join(comp["regressions"][:10]))
    if comp["gains"]:
        lines.append("now passing, failed before: %s" % ", ".join(comp["gains"][:10]))
    lines.append("verdict: " + comp["verdict"])
    return "\n".join(lines)


def compare_for_candidate(candidate_store_dir, sample=None, store_dir=None, worker_runner=None,
                          worker_cmd=None, worker=None, timeout_s=None, tasks_limit=0):
    """Shadow evaluation: run a sample of dev cases plus every counterexample case under the
    current policy and under the candidate policy in ``candidate_store_dir`` (a copy of the
    user store with the change applied), then return their comparison. Holdout cases are
    never run: any named in ``sample`` are returned under ``excluded_holdout``. Results are
    recorded in the real store under each policy's version; the candidate store is not written
    to except by a worker run under its policy. This is the seam the approval path calls."""
    store_dir = _store(store_dir)
    all_cases = load_cases(store_dir=store_dir)
    by_id = {c["id"]: c for c in all_cases}
    excluded = []
    if isinstance(sample, (list, tuple)):
        chosen = []
        for item in sample:
            case = item if isinstance(item, dict) else by_id.get(item)
            if case is None:
                continue
            if case.get("split") == "holdout":
                excluded.append(case["id"])
            elif case.get("split") == "dev":
                chosen.append(case)
    elif isinstance(sample, int):
        chosen = select_cases(all_cases, split="dev", purpose="shadow")[:sample]
    else:
        chosen = select_cases(all_cases, split="dev", purpose="shadow")
    seen = {c["id"] for c in chosen}
    chosen += [c for c in all_cases if c.get("split") == "counterexample" and c["id"] not in seen]
    picked, tasks_done = [], 0
    for case in chosen:
        if case.get("kind") == "task":
            if tasks_done >= (tasks_limit or 0):
                continue
            tasks_done += 1
        picked.append(case)
    current = policy_version(store_dir)
    candidate = policy_version(candidate_store_dir)
    kw = dict(store_dir=store_dir, worker_runner=worker_runner, worker_cmd=worker_cmd,
              worker=worker, timeout_s=timeout_s)
    for case in picked:
        run_case(case, policy_dir=store_dir, policy_label=current, **kw)
    for case in picked:
        run_case(case, policy_dir=candidate_store_dir, policy_label=candidate, **kw)
    comp = compare_versions(current, candidate, store_dir=store_dir,
                            case_ids={c["id"] for c in picked})
    comp["excluded_holdout"] = excluded
    comp["candidate_dir"] = candidate_store_dir
    comp["sample"] = [c["id"] for c in picked]
    return comp


# ---------------------------------------------------------------- independent judging

def _judge_prompt(case, result):
    items = "\n".join("- %s: %s" % (c.get("id"), c.get("cmd")) for c in (case or {}).get("checks") or [])
    checks = "\n".join("- %s: exit %s (%s)" % (r.get("id"), r.get("exit"),
                                               "passed" if r.get("passed") else "did not pass")
                       for r in result.get("check_results") or [])
    return "\n".join([
        "You are an independent judge. You did not do this work.", "",
        "The human's request:", (case or {}).get("request") or "(not recorded)", "",
        "Acceptance items (the case's checks):", items or "(none recorded)", "",
        "Check results on the worker's tree:", checks or "(none recorded)", "",
        "The worker's diff against the start commit:", result.get("diff") or "(no diff recorded)", "",
        "Answer as JSON only, one item per acceptance item:",
        '{"items": [{"id": "<check id>", "verdict": "met" or "not met", "reason": "<one line>"}]}', ""])


def _parse_judge_items(got, case):
    """(worker, items) from a judge result: a dict, a JSON text, or 'id: met - reason' lines."""
    worker, raw = None, None
    if isinstance(got, dict):
        worker = got.get("worker") or got.get("judged_by")
        raw = got.get("items")
        if raw is None and got.get("text"):
            return worker, _parse_judge_items(str(got["text"]), case)[1]
    elif isinstance(got, str):
        text = got.strip()
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return _parse_judge_items(json.loads(m.group(0)), case)
            except ValueError:
                pass
        raw = []
        for line in text.splitlines():
            mm = re.match(r"\s*[-*]?\s*([A-Za-z0-9_.-]+)\s*[:=-]\s*(not met|met)\b\s*[-: ]*\s*(.*)", line, re.I)
            if mm:
                raw.append({"id": mm.group(1), "verdict": mm.group(2).lower(), "reason": mm.group(3).strip()})
    items = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        verdict = str(it.get("verdict") or "").strip().lower()
        if verdict in ("met", "not met") and it.get("id"):
            items.append({"id": str(it["id"]), "verdict": verdict,
                          "reason": str(it.get("reason") or "").split("\n")[0][:300]})
    return worker, items


def judge_result(result_id, store_dir=None, judge_runner=None, judge_cmd=None, judge_worker=None,
                 timeout_s=None):
    """Independent judging of one recorded run: a worker from a different maker than the one
    that did the run reads the request, the diff and the check results and answers met / not
    met per acceptance item. The judgement is appended and merged as ``judged_by``. A judge
    from the same maker is refused, so self-assessment is never recorded as independent."""
    from . import routing
    runs = read_results(store_dir=store_dir)
    result = next((r for r in runs if r.get("id") == result_id), None)
    if result is None:
        hits = [r for r in runs if str(r.get("id", "")).startswith(str(result_id))]
        result = hits[0] if len(hits) == 1 else None
    if result is None:
        return {"outcome": "not-run", "reason": "no single result matches %s" % result_id}
    case = get_case(result.get("case"), store_dir=store_dir) or {}
    author = result.get("worker")
    prompt = _judge_prompt(case, result)
    got, judged_by = None, judge_worker
    if judge_runner is not None:
        try:
            got = judge_runner(prompt, case=case, result=result)
        except TypeError:
            got = judge_runner(prompt)
        except Exception as e:
            return {"outcome": "not-run", "reason": "judge failed to run: %s" % e, "result_id": result["id"]}
    elif judge_cmd or os.environ.get("SISI_EVAL_JUDGE_CMD"):
        judged_by = judged_by or os.environ.get("SISI_EVAL_JUDGE_WORKER") or "judge-cmd"
        try:
            r = subprocess.run(judge_cmd or os.environ["SISI_EVAL_JUDGE_CMD"], shell=True,
                               input=prompt, capture_output=True, text=True,
                               timeout=float(timeout_s or _eval_config(store_dir)["worker_timeout_s"]))
            got = r.stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return {"outcome": "not-run", "reason": "judge timed out or could not start",
                    "result_id": result["id"]}
    else:
        try:
            got, err = _worker_via_delegate(prompt, case or {"tags": ["review"]}, os.getcwd(),
                                            _store(store_dir), worker=judge_worker,
                                            review_of=author, kind="review")
        except Exception as e:
            return {"outcome": "not-run", "reason": "judge failed to run: %s" % e, "result_id": result["id"]}
        if got is None:
            return {"outcome": "not-run", "reason": err or "no judge available", "result_id": result["id"]}
    worker_from, items = _parse_judge_items(got, case)
    judged_by = judged_by or worker_from
    if not judged_by:
        return {"outcome": "not-run", "reason": "the judge did not say who it is", "result_id": result["id"]}
    if author and routing.maker_of(judged_by) and routing.maker_of(judged_by) == routing.maker_of(author):
        return {"outcome": "not-run", "result_id": result["id"],
                "reason": "judge %s is from the same maker as the worker (%s); not independent"
                          % (judged_by, routing.maker_of(author))}
    if not items:
        return {"outcome": "not-run", "reason": "judge output named no met/not-met items",
                "result_id": result["id"]}
    row = {"id": "j-" + uuid.uuid4().hex[:10], "kind": "judgement", "ts": store.now(),
           "result_id": result["id"], "case": result.get("case"), "judged_by": str(judged_by),
           "items": items}
    append_result(row, store_dir=store_dir)
    return dict({"outcome": "judged"}, **row)


# ---------------------------------------------------------------- status

def status_summary(store_dir=None):
    """Counts by kind and split, the last run per split, and the latest comparison."""
    cases = load_cases(store_dir=store_dir)
    counts = {}
    for c in cases:
        counts.setdefault(c.get("kind"), {})[c.get("split")] = \
            counts.setdefault(c.get("kind"), {}).get(c.get("split"), 0) + 1
    results = read_results(store_dir=store_dir)
    last, policies = {}, []
    for r in results:
        if r.get("split"):
            last[r["split"]] = r.get("ts") or last.get(r["split"])
        if r.get("policy") and r["policy"] not in policies:
            policies.append(r["policy"])
    latest = None
    if len(policies) >= 2:
        latest = compare_versions(policies[-2], policies[-1], store_dir=store_dir)
    return {"cases": len(cases), "counts": counts, "last_run": last,
            "runs": len(results), "policies": policies, "latest_comparison": latest}


def format_status(st):
    lines = ["benchmark cases: %d" % st["cases"]]
    for kind in KINDS:
        parts = ", ".join("%s %d" % (sp, st["counts"].get(kind, {}).get(sp, 0)) for sp in SPLITS)
        lines.append("  %-6s %s" % (kind, parts))
    for sp in SPLITS:
        lines.append("last %s run: %s" % (sp, st["last_run"].get(sp) or "never"))
    lines.append("recorded runs: %d under %d policy version(s)" % (st["runs"], len(st["policies"])))
    if st["latest_comparison"]:
        lines.append("latest comparison (%s vs %s): %s" % (
            st["latest_comparison"]["a"], st["latest_comparison"]["b"],
            st["latest_comparison"]["verdict"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- command line

USAGE = """usage:
  sisi eval list [--kind check|task] [--split dev|holdout|counterexample] [--json]
  sisi eval add FILE.json | add --id ID --kind check|task --repo P --start C [--fix C] [--request TEXT] --check CMD [--tag T] [--split S]
  sisi eval run [--tasks N] [--split S] [--case ID] [--policy LABEL] [--policy-dir DIR] [--worker W] [--worker-cmd CMD] [--timeout S] [--json]
  sisi eval compare A B [--split S] [--json]
  sisi eval shadow DIR [--sample N] [--tasks N] [--worker W] [--worker-cmd CMD] [--json]
  sisi eval judge RESULT_ID [--judge-worker W] [--judge-cmd CMD] [--json]
  sisi eval status [--json]
  sisi eval import           create cases from the harvested task set"""


def _opt(args, name, default=None):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else default
    for a in args:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return default


def _opts(args, name):
    out, i = [], 0
    while i < len(args):
        if args[i] == name and i + 1 < len(args):
            out.append(args[i + 1])
            i += 1
        elif args[i].startswith(name + "="):
            out.append(args[i].split("=", 1)[1])
        i += 1
    return out


def _int_opt(args, name, default=None):
    v = _opt(args, name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _show(obj, as_json, text=None):
    print(json.dumps(obj) if as_json else text)


def _cmd_add(args, store_dir):
    plain = [a for a in args if not a.startswith("--")]
    if plain and os.path.isfile(plain[0]):
        try:
            data = json.load(open(plain[0], encoding="utf-8"))
        except (OSError, ValueError) as e:
            print("sisi eval add: cannot read %s: %s" % (plain[0], e), file=sys.stderr)
            return 1
        cases = data if isinstance(data, list) else [data]
    else:
        checks = [{"id": "c%d" % (i + 1), "cmd": c, "expect": {"exit": 0}}
                  for i, c in enumerate(_opts(args, "--check"))]
        cases = [{"id": _opt(args, "--id"), "kind": _opt(args, "--kind", "check"),
                  "source": {"unit": _opt(args, "--unit", "by-hand"), "learning": _opt(args, "--learning", "")},
                  "project": {"repo": _opt(args, "--repo"), "start_commit": _opt(args, "--start"),
                              "fix_commit": _opt(args, "--fix", "")},
                  "request": _opt(args, "--request", ""), "checks": checks,
                  "tags": _opts(args, "--tag"), "split": _opt(args, "--split", "dev"),
                  "added": time.strftime("%Y-%m-%d", time.gmtime())}]
    n = 0
    for case in cases:
        errs = validate_case(case)
        if errs:
            print("sisi eval add: %s" % "; ".join(errs), file=sys.stderr)
            return 1
        save_case(case, store_dir=store_dir)
        print("case %s (%s, %s)" % (case["id"], case["kind"], case["split"]))
        n += 1
    return 0 if n else 1


def _cmd_list(args, store_dir):
    cases = load_cases(store_dir=store_dir, kind=_opt(args, "--kind"), split=_opt(args, "--split"))
    if "--json" in args:
        print(json.dumps(cases))
        return 0
    print("%-24s %-6s %-14s tags" % ("case", "kind", "split"))
    for c in cases:
        print("%-24s %-6s %-14s %s" % (c.get("id"), c.get("kind"), c.get("split"),
                                       ",".join(c.get("tags") or [])))
    print("%d case(s)" % len(cases))
    return 0


def _select_for_run(args, store_dir, purpose="run"):
    cases = load_cases(store_dir=store_dir, kind=_opt(args, "--kind"))
    split = _opt(args, "--split")
    picked = select_cases(cases, split=split, purpose=purpose)
    wanted = _opts(args, "--case")
    if wanted:
        picked = [c for c in picked if c["id"] in wanted]
    return picked


def _cmd_run(args, store_dir):
    try:
        picked = _select_for_run(args, store_dir, purpose="tuning" if _opt(args, "--split") == "dev" else "run")
    except ValueError as e:
        print("sisi eval run: %s" % e, file=sys.stderr)
        return 1
    tasks_limit = _int_opt(args, "--tasks", 0)
    task_cases = [c for c in picked if c.get("kind") == "task"][:tasks_limit]
    as_json = "--json" in args
    cfg = _eval_config(store_dir)
    cap = cfg.get("max_cost_per_run")
    if task_cases:
        est = estimate_task_cost(len(task_cases), store_dir=store_dir)
        print("estimated cost: %s" % est["text"])
        if cap is not None and est["value"] is not None and est["value"] > float(cap):
            print("sisi eval run: estimated cost %g exceeds the per-invocation cap %g "
                  "from config (eval.max_cost_per_run); nothing run" % (est["value"], float(cap)),
                  file=sys.stderr)
            return 2
    results = run_cases(picked, tasks_limit=tasks_limit,
                        cost_cap=float(cap) if cap is not None else None,
                        store_dir=store_dir, policy_dir=_opt(args, "--policy-dir"),
                        policy_label=_opt(args, "--policy"),
                        worker=_opt(args, "--worker"), worker_cmd=_opt(args, "--worker-cmd"),
                        timeout_s=_int_opt(args, "--timeout"))
    if as_json:
        print(json.dumps(results))
        return 0
    for r in results[:38]:
        print("%-24s %-14s policy %s%s%s" % (r.get("case"), r.get("outcome"), r.get("policy"),
              (" worker " + str(r["worker"])) if r.get("worker") else "",
              (" - " + r["reason"]) if r.get("reason") else ""))
    if len(results) > 38:
        print("... and %d more" % (len(results) - 38))
    skipped_tasks = len([c for c in picked if c.get("kind") == "task"]) - len(task_cases)
    print("%d run(s) recorded%s" % (len(results),
          ("; %d task case(s) not run (task replay needs --tasks N)" % skipped_tasks) if skipped_tasks else ""))
    return 0


def cmd_folded(cmd, args):
    """The former hidden `sisi tasks` and `sisi checks`, now served by the evaluator."""
    args = list(args)
    if cmd == "tasks":
        sub = args[0] if args else "list"
        if sub == "build":
            try:
                from . import harvest, taskset
                con = harvest.connect()
                taskset.build(con)
                n = import_harvested(con=con)
            except Exception as e:
                print("sisi eval import: %s" % e, file=sys.stderr)
                return 1
            print("cases from harvested tasks: %(created)d created, %(kept)d kept" % n)
            return 0
        if sub == "show" and len(args) > 1:
            case = get_case(args[1])
            if not case:
                print("sisi: no single case matches %r" % args[1], file=sys.stderr)
                return 1
            print(json.dumps(case, indent=2))
            return 0
        return _cmd_list(args[1:] if sub == "list" else [], _store())
    latest = {}
    for r in read_results():
        if r.get("case_kind") == "check":
            latest[r.get("case")] = r
    cases = load_cases(kind="check")
    print("%-24s %-14s %s" % ("check case", "last outcome", "policy"))
    for c in cases[:38]:
        r = latest.get(c["id"]) or {}
        print("%-24s %-14s %s" % (c["id"], r.get("outcome") or "not-run", r.get("policy") or "-"))
    print("%d check case(s)" % len(cases))
    return 0


def cmd_eval(args=(), store_dir=None):
    args = list(args)
    store_dir = _store(store_dir)
    sub = args.pop(0) if args else "status"
    as_json = "--json" in args
    if sub in ("help", "-h", "--help"):
        print(USAGE)
        return 0
    try:
        if sub == "add":
            return _cmd_add(args, store_dir)
        if sub == "list":
            return _cmd_list(args, store_dir)
        if sub == "run":
            return _cmd_run(args, store_dir)
        if sub == "status":
            st = status_summary(store_dir=store_dir)
            _show(st, as_json, format_status(st))
            return 0
        if sub == "compare":
            plain = []
            for a in args:
                if a.startswith("--"):
                    break
                plain.append(a)
            if len(plain) != 2:
                print(USAGE, file=sys.stderr)
                return 1
            comp = compare_versions(plain[0], plain[1], store_dir=store_dir,
                                    split=_opt(args, "--split"))
            _show(comp, as_json, format_comparison(comp))
            return 0
        if sub == "shadow":
            plain = [a for a in args[:1] if not a.startswith("--")]
            if len(plain) != 1 or not os.path.isdir(plain[0]):
                print("usage: sisi eval shadow DIR (a candidate copy of the user store)", file=sys.stderr)
                return 1
            tasks_limit = _int_opt(args, "--tasks", 0)
            picked_cases = select_cases(load_cases(store_dir=store_dir), split="dev", purpose="shadow")
            task_cases = [c for c in picked_cases if c.get("kind") == "task"][:tasks_limit]
            if task_cases:
                print("estimated cost: %s" % estimate_task_cost(len(task_cases) * 2, store_dir=store_dir)["text"])
            comp = compare_for_candidate(plain[0], sample=_int_opt(args, "--sample"),
                                         store_dir=store_dir, worker=_opt(args, "--worker"),
                                         worker_cmd=_opt(args, "--worker-cmd"),
                                         timeout_s=_int_opt(args, "--timeout"),
                                         tasks_limit=tasks_limit)
            if comp["excluded_holdout"]:
                print("held out, not run: %s" % ", ".join(comp["excluded_holdout"]))
            _show(comp, as_json, format_comparison(comp))
            return 0
        if sub == "judge":
            plain = [a for a in args[:1] if not a.startswith("--")]
            if len(plain) != 1:
                print(USAGE, file=sys.stderr)
                return 1
            j = judge_result(plain[0], store_dir=store_dir,
                             judge_cmd=_opt(args, "--judge-cmd"),
                             judge_worker=_opt(args, "--judge-worker"))
            if as_json:
                print(json.dumps(j))
            elif j.get("outcome") == "judged":
                print("judged by %s" % j["judged_by"])
                for it in j["items"]:
                    print("  %s: %s - %s" % (it["id"], it["verdict"], it["reason"]))
            else:
                print("not judged: %s" % j.get("reason"))
            return 0 if j.get("outcome") == "judged" else 1
        if sub == "import":
            n = import_harvested(store_dir=store_dir)
            print("cases from harvested tasks: %(created)d created, %(kept)d kept" % n)
            return 0
    except ValueError as e:
        print("sisi eval %s: %s" % (sub, e), file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 1
