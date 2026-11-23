"""Choosing a worker: pure arithmetic over the delegation record. No model call, no file access.

A candidate is a plain dict: worker (canonical id), tool, model, maker, plan ("flat", "per-use" or
None), cost (a comparable per-use price or None), allowance_pct_left (0..100 or None), usable,
reason (why not usable), and aliases (every spelling the record may use for this worker).

The rule, in order:
  1. Never a model whose id contains "contributor" (those tiers train on prompts).
  2. Never a worker marked unavailable whose retry time is still ahead, nor one whose flat
     allowance is known to be spent. A user's own `avoid` patterns also remove a worker, unless
     that would leave nobody.
  3. For a review, never the author's maker while another maker is available. A stored `maker`
     fact wins; otherwise the maker is derived from the model id (see maker_of).
  4. Among the rest, a worker is proven for a kind and difficulty with MIN_ATTEMPTS judged attempts
     and an accepted rate of at least MIN_ACCEPTED_RATE (accepted and not later found wrong). Above
     difficulty 1, proven workers are preferred; at difficulty 1, workers with a thin record stay in
     the pool so they gather attempts on low-stakes work. A worker proven bad (enough attempts, rate
     below the bar) is passed over whenever anything else remains.
  5. Cheapest first: a flat-rate plan with allowance left costs nothing more per task, so it comes
     before anything billed per use; per-use workers order by their known price; an unknown price is
     treated as the most expensive until learned. A stored benchmark prior (`prior_score`) ranks
     within the same price, so a thin record is ordered by price and prior, never arbitrarily.
     A user's `prefer` patterns put a worker first within the eligible pool.
  6. About one low-stakes task in ten (difficulty 1, every tenth judged attempt for that kind and
     difficulty) goes to a cheaper worker with a thin record instead, so cheaper options keep
     gathering evidence. The slot is a function of the record, so the choice stays deterministic
     for one fixed record.
  7. Load balancing: within the same price tier and price, the worker that has taken the least work
     relative to its remaining allowance goes first (recorded uses divided by allowance left, an
     unknown allowance counting as half). Because every delegation is recorded, the choice rotates
     as work is done, yet stays deterministic for one fixed record. Ties break on the worker id.

Candidates reach here already restricted to workers with a judged record, a known price or a
benchmark prior (see workers.routable_candidates); on a cold start none qualifies and every usable
worker is offered, with the explanation saying so.
"""
import re

MIN_ATTEMPTS = 8          # below this, a worker's record for a kind and difficulty is thin
MIN_ACCEPTED_RATE = 0.6   # "good enough" among workers with at least MIN_ATTEMPTS attempts
UNKNOWN_ALLOWANCE = 50.0  # allowance weight when a tool reports none
STRONG_BAND = 10.0        # strength points from the best still counts as among the strongest
EXPLORE_EVERY = 10        # about one low-stakes task in ten tries a cheaper thin-record worker


def maker_of(name):
    """A best-effort maker derived from a worker or model id: the first word of the model part.
    A stored `maker` fact wins wherever a candidate carries one; no table of names ships here."""
    s = str(name or "").strip().lower()
    if not s:
        return ""
    model = s.rsplit("/", 1)[-1]
    return re.split(r"[-_:. ]", model)[0] or model


def _pattern_match(c, patterns):
    """The (pattern, why) a candidate matches, or None. A pattern matches as a substring of the
    worker, model or tool name, case aside."""
    hay = " ".join(str(x or "").lower() for x in (c.get("worker"), c.get("model"), c.get("tool")))
    for entry in patterns or []:
        if isinstance(entry, dict):
            pat, why = str(entry.get("pattern") or ""), str(entry.get("why") or "")
        else:
            pat, why = str(entry), ""
        if pat and pat.lower() in hay:
            return pat, why
    return None


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


def choose(candidates, records, availability, kind, difficulty, review_of=None, now=0.0, exclude=(),
           avoid=None, prefer=None):
    """Pick one candidate, or none. Returns {"choice", "passed_over", "stats", "author_maker"}.
    `passed_over` is [(worker, plain reason)] covering every candidate not chosen. `avoid` and
    `prefer` are the user's own [{"pattern", "why"}] constraints."""
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

    avoided = [(c, _pattern_match(c, avoid)) for c in eligible]
    kept = [c for c, m in avoided if m is None]
    if kept:
        for c, m in avoided:
            if m is not None:
                pat, why = m
                passed.append((c["worker"], "avoided by the user's own pattern %r%s"
                               % (pat, (" (%s)" % why) if why else "")))
        eligible = kept

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

    def prior_key(c):
        score = c.get("prior_score")
        return -float(score) if isinstance(score, (int, float)) else 1.0

    def key(c):
        r = rate(c)
        return (0 if _pattern_match(c, prefer) else 1,
                _price_tier(c),
                float(c["cost"]) if c.get("cost") is not None else float("inf"),
                prior_key(c),
                load_ratio(c),
                -(r if r is not None else -1.0),
                c["worker"])

    def price_of(c):
        return (_price_tier(c), float(c["cost"]) if c.get("cost") is not None else float("inf"))

    pool.sort(key=key)
    choice = pool[0] if pool else None
    explored = None
    if (choice is not None and difficulty == 1 and not _pattern_match(choice, prefer)
            and _cell(stats, choice["worker"], kind, difficulty)["n"] >= MIN_ATTEMPTS):
        total = sum(_cell(stats, c["worker"], kind, difficulty)["n"] for c in candidates)
        if total >= EXPLORE_EVERY - 1 and total % EXPLORE_EVERY == EXPLORE_EVERY - 1:
            thinner = [c for c in pool
                       if c is not choice
                       and _cell(stats, c["worker"], kind, difficulty)["n"] < MIN_ATTEMPTS
                       and price_of(c) <= price_of(choice)]
            if thinner:
                thinner.sort(key=key)
                explored, choice = choice, thinner[0]
                pool = [choice] + [c for c in pool if c is not choice]
    if choice is not None:
        for c in pool[1:]:
            if explored is not None and c is explored:
                reason = ("the usual choice, passed over this once so a cheaper thin-record worker "
                          "gathers evidence on low-stakes work (about one task in %d)" % EXPLORE_EVERY)
            elif _pattern_match(choice, prefer) and not _pattern_match(c, prefer):
                _pat, _why = _pattern_match(choice, prefer)
                reason = "the choice matches the user's own prefer pattern %r%s" % (_pat, (" (%s)" % _why) if _why else "")
            elif _price_tier(c) > _price_tier(choice) or (c.get("cost") is not None and choice.get("cost") is not None
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
            "explored": explored["worker"] if explored else None,
            "load_ratios": {c["worker"]: load_ratio(c) for c in candidates}}


MAX_EXPLAIN_LINES = 20
EXPLAIN_TAIL_LINES = 5  # worker, mechanism, exclusion note, cold-start notice, request for facts


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
        if isinstance(choice.get("prior_score"), (int, float)) and cell["n"] < MIN_ATTEMPTS:
            lines.append("its benchmark prior is %g (%s, %s); with a thin record, price and prior decide the order"
                         % (float(choice["prior_score"]), choice.get("prior_source") or "no source stated",
                            choice.get("prior_date") or "no date stated"))
        if result.get("explored"):
            lines.append("this is an exploration pick: %s was the usual choice, passed over once so a cheaper "
                         "thin-record worker gathers evidence" % result["explored"])
        if result.get("author_maker"):
            choice_maker = choice.get("maker") or maker_of(choice.get("model") or choice["worker"])
            if choice_maker != result["author_maker"]:
                lines.append("it is from a different maker than the author (%s)" % result["author_maker"])
            else:
                lines.append("no worker from a different maker than the author (%s) is available, "
                             "so the review stays with the same maker" % result["author_maker"])
    groups, order = {}, []
    for worker, reason in result["passed_over"]:
        if reason not in groups:
            groups[reason] = []
            order.append(reason)
        groups[reason].append(worker)
    # `--explain` stays short whatever the catalogue size (R-7.2-1): one line per reason with a
    # count and at most 3 example names; if reasons alone would overflow MAX_EXPLAIN_LINES, the
    # smallest groups share one closing line that still names each reason and its count.
    def group_line(reason):
        names = groups[reason]
        shown = ", ".join(names[:3])
        more = " and %d more" % (len(names) - 3) if len(names) > 3 else ""
        return "passed over %d worker(s) (%s%s): %s" % (len(names), shown, more, reason)

    room = max(MAX_EXPLAIN_LINES - len(lines) - EXPLAIN_TAIL_LINES, 1)
    ranked = sorted(order, key=lambda r: -len(groups[r]))
    keep = ranked if len(ranked) <= room else ranked[:room - 1]
    for reason in order:
        if reason in keep:
            lines.append(group_line(reason))
    rest = [r for r in ranked if r not in keep]
    if rest:
        lines.append("passed over %d more worker(s) for %d other reasons: %s"
                     % (sum(len(groups[r]) for r in rest), len(rest),
                        "; ".join("%s (%d)" % (r, len(groups[r])) for r in rest)))
    return lines
