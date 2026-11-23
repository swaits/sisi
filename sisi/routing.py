"""Choosing a worker: pure arithmetic over the delegation record. No model call, no file access.

A candidate is a plain dict: worker (canonical id), tool, model, maker, plan ("flat", "per-use" or
None), cost (a comparable per-use price or None), allowance_pct_left (0..100 or None), usable,
reason (why not usable), and aliases (every spelling the record may use for this worker).

The rule, in order:
  1. Never a model whose id contains "contributor" (those tiers train on prompts).
  2. Never a worker marked unavailable whose retry time is still ahead, nor one whose flat
     allowance is known to be spent.
  3. For a review, never the author's maker while another maker is available.
  4. Among the rest, a worker is proven for a kind and difficulty with MIN_ATTEMPTS judged attempts
     and an accepted rate of at least MIN_ACCEPTED_RATE (accepted and not later found wrong). Above
     difficulty 1, proven workers are preferred; at difficulty 1, workers with a thin record stay in
     the pool so they gather attempts on low-stakes work. A worker proven bad (enough attempts, rate
     below the bar) is passed over whenever anything else remains.
  5. Cheapest first: a flat-rate plan with allowance left costs nothing more per task, so it comes
     before anything billed per use; per-use workers order by their known price; an unknown price is
     treated as the most expensive until learned.
  6. Load balancing: within the same price tier and price, the worker that has taken the least work
     relative to its remaining allowance goes first (recorded uses divided by allowance left, an
     unknown allowance counting as half). Because every delegation is recorded, the choice rotates
     as work is done, yet stays deterministic for one fixed record. Ties break on the worker id.

On a fresh install the record is empty and no prices are known, so every candidate is thin and
priced unknown: the first in worker-id order among the usable ones is chosen, and each judged
result from then on shapes the next choice.
"""
import re

MIN_ATTEMPTS = 8          # below this, a worker's record for a kind and difficulty is thin
MIN_ACCEPTED_RATE = 0.6   # "good enough" among workers with at least MIN_ATTEMPTS attempts
UNKNOWN_ALLOWANCE = 50.0  # allowance weight when a tool reports none
STRONG_BAND = 10.0        # strength points from the best still counts as among the strongest

_MAKER_ALIASES = {"haiku": "claude", "sonnet": "claude", "opus": "claude", "fable": "claude"}


def maker_of(name):
    """A best-effort maker from a worker or model id: the first word of the model part.
    Stored tables may state a maker explicitly; those win wherever a candidate carries one."""
    s = str(name or "").strip().lower()
    if not s:
        return ""
    model = s.rsplit("/", 1)[-1]
    token = re.split(r"[-_:. ]", model)[0] or model
    return _MAKER_ALIASES.get(token, token)


def _alias_map(candidates):
    m = {}
    for c in candidates:
        for a in [c.get("worker"), c.get("model")] + list(c.get("aliases") or []):
            if a:
                m.setdefault(str(a).lower(), c["worker"])
    return m


def _availability_keys(c):
    keys = {str(x).lower() for x in [c.get("worker"), c.get("tool"), c.get("model")] + list(c.get("aliases") or []) if x}
    for v in (c.get("worker") or "", c.get("model") or ""):
        if "/" in v:
            keys.add(v.split("/", 1)[0].lower())
    return keys


def _down_entry(c, availability, now):
    keys = _availability_keys(c)
    for k, e in (availability or {}).items():
        if not isinstance(e, dict):
            continue
        if str(k).lower() in keys and float(e.get("retry_at") or 0) > now:
            return e
    return None


def candidate_stats(candidates, records):
    """{canonical worker: counted facts} from judged attempts, amendments and runs."""
    aliases = _alias_map(candidates)
    amended = {r.get("id") for r in records if r.get("kind") == "amend"}
    stats = {}
    for c in candidates:
        stats[c["worker"]] = {"uses": 0, "by_cell": {}}
    for r in records:
        w = aliases.get(str(r.get("worker") or "").lower())
        if w is None:
            continue
        if r.get("kind") == "run":
            stats[w]["uses"] += 1
        elif r.get("kind") == "attempt":
            stats[w]["uses"] += 1
            cell = stats[w]["by_cell"].setdefault(
                (r.get("type") or r.get("task_kind"), r.get("difficulty")), {"n": 0, "good": 0})
            cell["n"] += 1
            if r.get("outcome") == "accepted" and r.get("id") not in amended:
                cell["good"] += 1
    return stats


def _price_tier(c):
    if c.get("plan") == "flat":
        return 0
    if c.get("plan") == "per-use" or c.get("cost") is not None:
        return 1
    return 2


def _cell(stats, worker, kind, difficulty):
    return stats.get(worker, {}).get("by_cell", {}).get((kind, difficulty), {"n": 0, "good": 0})


def choose(candidates, records, availability, kind, difficulty, review_of=None, now=0.0, exclude=()):
    """Pick one candidate, or none. Returns {"choice", "passed_over", "stats", "author_maker"}.
    `passed_over` is [(worker, plain reason)] covering every candidate not chosen."""
    now = float(now or 0)
    exclude = {str(x) for x in exclude}
    stats = candidate_stats(candidates, records)
    passed = []
    eligible = []

    for c in candidates:
        w = c["worker"]
        if w in exclude:
            passed.append((w, "already tried in this delegation"))
            continue
        if "contributor" in str(c.get("model") or w).lower():
            passed.append((w, "its id contains 'contributor', a tier that trains on prompts"))
            continue
        down = _down_entry(c, availability, now)
        if down is not None:
            passed.append((w, "unavailable (%s) until its retry time" % (down.get("reason") or "down")))
            continue
        if not c.get("usable", True):
            passed.append((w, c.get("reason") or "not usable now"))
            continue
        if c.get("plan") == "flat" and c.get("allowance_pct_left") == 0:
            passed.append((w, "its flat-rate allowance is spent"))
            continue
        eligible.append(c)

    author_maker = ""
    if review_of:
        target = str(review_of).lower()
        author = next((c for c in candidates
                       if target in {str(x).lower() for x in [c.get("worker"), c.get("model")] + list(c.get("aliases") or []) if x}), None)
        author_maker = (author.get("maker") if author else None) or maker_of(review_of)
        for c in eligible:
            c.setdefault("maker", maker_of(c.get("model") or c["worker"]))
        if any((c.get("maker") or maker_of(c.get("model") or c["worker"])) != author_maker for c in eligible):
            rest = []
            for c in eligible:
                if (c.get("maker") or maker_of(c.get("model") or c["worker"])) == author_maker:
                    passed.append((c["worker"], "same maker as the author (%s); a review needs another maker" % author_maker))
                else:
                    rest.append(c)
            eligible = rest

    def rate(c):
        cell = _cell(stats, c["worker"], kind, difficulty)
        return (cell["good"] / cell["n"]) if cell["n"] else None

    def proven_good(c):
        cell = _cell(stats, c["worker"], kind, difficulty)
        return cell["n"] >= MIN_ATTEMPTS and rate(c) is not None and rate(c) >= MIN_ACCEPTED_RATE

    def proven_bad(c):
        cell = _cell(stats, c["worker"], kind, difficulty)
        return cell["n"] >= MIN_ATTEMPTS and rate(c) is not None and rate(c) < MIN_ACCEPTED_RATE

    pool = list(eligible)
    if difficulty and difficulty > 1:
        good = [c for c in eligible if proven_good(c)]
        if good:
            for c in eligible:
                if c not in good:
                    cell = _cell(stats, c["worker"], kind, difficulty)
                    passed.append((c["worker"],
                                   "record too thin for this difficulty (%d of %d attempts) while a proven worker is available"
                                   % (cell["n"], MIN_ATTEMPTS) if cell["n"] < MIN_ATTEMPTS
                                   else "accepted rate below the bar for this kind and difficulty"))
            pool = good
    if pool:
        bad = [c for c in pool if proven_bad(c)]
        if bad and len(bad) < len(pool):
            for c in bad:
                passed.append((c["worker"], "accepted rate below the bar over %d attempts"
                               % _cell(stats, c["worker"], kind, difficulty)["n"]))
            pool = [c for c in pool if c not in bad]

    def load_ratio(c):
        left = c.get("allowance_pct_left")
        weight = float(left) if left else UNKNOWN_ALLOWANCE
        return stats.get(c["worker"], {}).get("uses", 0) / max(weight, 1.0)

    def key(c):
        r = rate(c)
        return (_price_tier(c),
                float(c["cost"]) if c.get("cost") is not None else float("inf"),
                load_ratio(c),
                -(r if r is not None else -1.0),
                c["worker"])

    pool.sort(key=key)
    choice = pool[0] if pool else None
    if choice is not None:
        for c in pool[1:]:
            if _price_tier(c) > _price_tier(choice) or (c.get("cost") is not None and choice.get("cost") is not None
                                                        and float(c["cost"]) > float(choice["cost"])):
                reason = "more expensive than the choice (per-use price or unknown price counts as most expensive)"
            elif load_ratio(c) > load_ratio(choice):
                reason = "load balancing: it has taken more work relative to the allowance it has left"
            else:
                r, cr = rate(c), rate(choice)
                reason = ("lower measured accepted rate for this kind and difficulty"
                          if r is not None and cr is not None and r < cr else
                          "equal on price and load; the choice came first in worker-id order")
            passed.append((c["worker"], reason))
    return {"choice": choice, "passed_over": passed, "stats": stats, "author_maker": author_maker,
            "load_ratios": {c["worker"]: load_ratio(c) for c in candidates}}


def explain_choice(result, kind, difficulty):
    """Plain lines for `--explain`, from a choose() result."""
    choice = result["choice"]
    lines = []
    if choice is None:
        lines.append("no usable worker for kind %s at difficulty %s" % (kind, difficulty))
    else:
        cell = _cell(result["stats"], choice["worker"], kind, difficulty)
        if choice.get("plan") == "flat":
            price = "a flat-rate plan with allowance left, so one more task costs nothing extra"
        elif choice.get("cost") is not None:
            price = "the cheapest known per-use price among the workers that are good enough"
        elif choice.get("plan") == "per-use":
            price = "billed per use; no cheaper flat-rate worker is usable"
        else:
            price = "price unknown, treated as most expensive until learned; nothing priced cheaper is usable"
        if cell["n"] >= MIN_ATTEMPTS:
            record = "%d judged attempts for this kind and difficulty, %d accepted" % (cell["n"], cell["good"])
        elif cell["n"]:
            record = "a thin record (%d of %d attempts for this kind and difficulty)" % (cell["n"], MIN_ATTEMPTS)
        else:
            record = "no judged attempts yet for this kind and difficulty"
        lines.append("chose %s: %s; %s; load so far is %s recorded use(s) against the allowance it has left, "
                     "the lowest in its price tier, so work spreads instead of draining one plan"
                     % (choice["worker"], price, record, result["stats"].get(choice["worker"], {}).get("uses", 0)))
        if result.get("author_maker"):
            lines.append("it is from a different maker than the author (%s)" % result["author_maker"])
    groups, order = {}, []
    for worker, reason in result["passed_over"]:
        if reason not in groups:
            groups[reason] = []
            order.append(reason)
        groups[reason].append(worker)
    for reason in order:
        names = groups[reason]
        shown = ", ".join(names[:12])
        if len(names) > 12:
            shown += " (and %d more)" % (len(names) - 12)
        lines.append("passed over %s: %s" % (shown, reason))
    return lines
