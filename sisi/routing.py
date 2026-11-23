"""Choosing a worker: pure arithmetic over the delegation record. No model call, no file access.

A candidate is a plain dict: worker (canonical id), tool, model, maker, plan ("flat", "per-use" or
None), cost (a comparable blended per-million-token price or None), allowance_pct_left (0..100 or
None), usable, reason (why not usable), standing (a published benchmark's figure or None, with
standing_source and standing_date), and aliases (every spelling the record may use for this worker).

Two scales are kept apart. A benchmark standing is a figure from outside; an accepted rate is what
this organization measured by judging delegations. They are never compared with each other: a
standing is compared only with other workers' standings, a rate only with the bar and with other
rates. Judged evidence outranks the benchmark wherever both exist.

The rule, in order:
  1. Never a model whose id contains "contributor" (those tiers train on prompts).
  2. Never a worker marked unavailable whose retry time is still ahead, nor one whose flat
     allowance is known to be spent. A user's own `avoid` patterns also remove a worker, unless
     that would leave nobody.
  3. For a review, never the author's maker while another maker is available. A stored `maker`
     fact wins; otherwise the maker is derived from the model id (see maker_of).
  4. Capable enough. For a kind and difficulty each remaining worker is judged by the best
     evidence about it, in this order (see `assess`):
       a. its judged record for that kind and difficulty: MIN_ATTEMPTS judged attempts and an
          accepted rate of at least MIN_ACCEPTED_RATE (accepted and not later found wrong);
       b. the nearest judged evidence: the same kind at a harder difficulty proves an easier one;
          then all kinds at that difficulty (or a harder one). The same kind at an easier
          difficulty is only weak evidence, used when no usable worker is capable otherwise;
       c. benchmark standing as a prior, against other workers' standing only: at least a share of
          the best standing among the usable workers (`standing_floor`: 85 percent at difficulty 3,
          60 percent at difficulty 2, none at difficulty 1);
       d. nothing known: capable for difficulty 1 only, as an exploration.
     A worker with a thick bad record (MIN_ATTEMPTS attempts, rate under the bar) for the kind at
     this or an easier difficulty is never capable, so never rides on a benchmark. A thin record
     that already shows repeated rejections also cancels the benchmark prior.
  5. Above difficulty 1 a benchmark is a reason to try a worker, not to prefer it to proof: when any
     usable worker is capable by a judged record for the kind (evidence a, or b from a harder
     difficulty of the kind), only those compete; the record across all kinds counts as proof only
     when no usable worker has evidence from the kind; benchmark standing decides only when nobody
     has a judged record for the request. At difficulty 1 every capable worker competes.
     Among those the cheapest wins: a flat-rate plan with allowance left first
     (it costs nothing more per task), then the blended price (an unknown price counts as most
     expensive), then the benchmark standing, then load. A user's `prefer` patterns come first.
     If no worker is capable, the weak evidence decides; failing that, the strongest known usable
     worker is recommended and the explanation says plainly that none is proven for this.
  6. About one low-stakes task in ten (difficulty 1, every tenth judged attempt for that kind and
     difficulty) goes to a cheaper worker with a thin record instead, so cheaper options keep
     gathering evidence. The slot is a function of the record, so the choice stays deterministic.
  7. Load balancing: within the same price tier and price, the worker that has taken the least work
     relative to its remaining allowance goes first (recorded uses divided by allowance left, an
     unknown allowance counting as half). Ties break on the worker id.

Candidates reach here already restricted to workers with a judged record, a known price or a
benchmark standing (see workers.routable_candidates); on a cold start none qualifies and every
usable worker is offered, with the explanation saying so.
"""
import re

MIN_ATTEMPTS = 8          # below this, a worker's record for a kind and difficulty is thin
MIN_ACCEPTED_RATE = 0.6   # "good enough" among workers with at least MIN_ATTEMPTS attempts
CONTRADICTION_REJECTIONS = 2  # a thin record with this many rejections below the bar cancels a prior
UNKNOWN_ALLOWANCE = 50.0  # allowance weight when a tool reports none
STRONG_BAND = 10.0        # standing points from the best still counts as among the strongest
EXPLORE_EVERY = 10        # about one low-stakes task in ten tries a cheaper thin-record worker
EXPLORE_FREE_EVERY = 3    # an unproven worker that costs nothing extra gets one routine task in three
DEFAULT_STANDING_FLOOR = {1: 0.0, 2: 60.0, 3: 85.0}  # percent of the best usable standing needed
DEFAULT_PRICE_BLEND = 3.0  # parts of input price to one part of output price in a blended price


def maker_of(name):
    """A best-effort maker derived from a worker or model id: the first word of the model part.
    A stored `maker` fact wins wherever a candidate carries one; no table of names ships here."""
    s = str(name or "").strip().lower()
    if not s:
        return ""
    model = s.rsplit("/", 1)[-1]
    return re.split(r"[-_:. ]", model)[0] or model


def blended_price(price_in, price_out, ratio=DEFAULT_PRICE_BLEND):
    """One comparable per-million-token price from a published input and output price: `ratio` parts
    of input to one part of output. None when either is missing."""
    if not isinstance(price_in, (int, float)) or not isinstance(price_out, (int, float)):
        return None
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        ratio = DEFAULT_PRICE_BLEND
    if ratio < 0:
        ratio = DEFAULT_PRICE_BLEND
    return (float(price_in) * ratio + float(price_out)) / (ratio + 1.0)


def standing_floors(configured=None):
    """{difficulty: percent of the best usable standing needed}, the defaults overridden by whatever
    valid entries the configured mapping has (keys 1..3, values 0..100)."""
    table = dict(DEFAULT_STANDING_FLOOR)
    if isinstance(configured, dict):
        for k, v in configured.items():
            try:
                d, pct = int(k), float(v)
            except (TypeError, ValueError):
                continue
            if d >= 1 and 0 <= pct <= 100:
                table[d] = pct
    return table


def _floor_pct(floors, difficulty):
    table = standing_floors(floors)
    if difficulty in table:
        return table[difficulty]
    if difficulty is None or difficulty < min(table):
        return 0.0
    return table[max(table)]


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


# ---------------------------------------------------------------- capability evidence

_TIER_RANK = {"a": 0, "b-higher": 1, "b-all": 2}   # smaller is closer to the request
_NO_CELL = {"n": 0, "good": 0}


def _thick(cell):
    return cell["n"] >= MIN_ATTEMPTS


def _rate(cell):
    return cell["good"] / cell["n"] if cell["n"] else None


def _proven(cell):
    return _thick(cell) and _rate(cell) >= MIN_ACCEPTED_RATE


def _poor(cell):
    return _thick(cell) and _rate(cell) < MIN_ACCEPTED_RATE


def _contradicts(cell):
    """A thin record that already shows repeated rejections below the bar."""
    return (not _thick(cell) and cell["n"] - cell["good"] >= CONTRADICTION_REJECTIONS
            and _rate(cell) < MIN_ACCEPTED_RATE)


def _by_difficulty(stats, worker, kind):
    """({difficulty: cell} for this kind, {difficulty: cell} pooled over every kind), whole numbers only."""
    own, pooled = {}, {}
    for (k, d), cell in stats.get(worker, {}).get("by_cell", {}).items():
        if not isinstance(d, int) or isinstance(d, bool):
            continue
        if k == kind:
            own[d] = cell
        p = pooled.setdefault(d, {"n": 0, "good": 0})
        p["n"] += cell["n"]
        p["good"] += cell["good"]
    return own, pooled


def assess(stats, worker, kind, difficulty, standing=None, best_standing=None, floors=None):
    """What the evidence says about one worker for a kind and difficulty. Returns a dict:
      tier       "a", "b-higher", "b-all", "standing", "unknown" or "none"
      capable    whether the evidence says it is capable enough
      bad        a thick bad record for this kind at this or an easier difficulty: never capable
      weak       a proven record for this kind at an easier difficulty (weak evidence, last resort)
      contradicted  a thin record for this kind that already shows repeated rejections
      level      3 judged proof, 2 benchmark, 1 weak, 0 nothing, -1 bad: never rises with difficulty
      n, good, at   the judged cell behind a, b-higher, b-all and the weak tier (and its difficulty)
      share, needed, floor   for the standing tier: percent of the best, the figure needed, the floor
    Standing is compared only with the best standing; a rate only with the bar."""
    d = difficulty
    own, pooled = _by_difficulty(stats, worker, kind)
    out = {"tier": "none", "capable": False, "bad": False, "weak": False, "contradicted": False,
           "level": 0, "standing": standing, "measure": None}
    easier = sorted(k for k in own if isinstance(d, int) and k <= d)
    out["bad"] = any(_poor(own[k]) for k in easier)
    if out["bad"]:
        k = next(k for k in easier if _poor(own[k]))
        out.update(level=-1, at=k, n=own[k]["n"], good=own[k]["good"], measure=_rate(own[k]))
        return out
    out["contradicted"] = any(_contradicts(own[k]) for k in easier)
    easier_proven = [k for k in easier if k < d and _proven(own[k])]
    out["weak"] = bool(easier_proven)
    if easier_proven:
        k = max(easier_proven)
        out.update(weak_at=k, weak_n=own[k]["n"], weak_good=own[k]["good"], weak_rate=_rate(own[k]))
    proof = None
    if isinstance(d, int):
        exact = own.get(d, _NO_CELL)
        if _proven(exact):
            proof = ("a", d, exact)
        else:
            higher = sorted(k for k in own if k > d and _proven(own[k]))
            if higher:
                proof = ("b-higher", higher[0], own[higher[0]])
            else:
                wide = sorted(k for k in pooled if k >= d and _proven(pooled[k]))
                if wide:
                    proof = ("b-all", wide[0], pooled[wide[0]])
    if proof is not None:
        tier, at, cell = proof
        out.update(tier=tier, capable=True, level=3, at=at, n=cell["n"], good=cell["good"], measure=_rate(cell))
        return out
    if standing is not None:
        pct = _floor_pct(floors, d)
        needed = (best_standing or 0.0) * pct / 100.0
        capable = standing >= needed - 1e-9
        out.update(floor=pct, needed=needed, best=best_standing, below=not capable)
        if not out["contradicted"]:
            out.update(tier="standing", capable=capable, level=2 if capable else (1 if out["weak"] else 0))
            return out
    if standing is None and d == 1 and not out["contradicted"]:
        out.update(tier="unknown", capable=True, level=0)
        return out
    if out["weak"]:
        out["level"] = 1
    return out


def strength(a):
    """How strong the evidence about a worker is, as a tuple that orders workers from weakest to
    strongest. Kinds of evidence are ordered first (judged proof, then benchmark, then weak, then
    nothing); only inside one kind are figures compared, so a standing never meets a rate."""
    if a["bad"]:
        return (-1, 0, 0.0)
    if a["tier"] in _TIER_RANK:
        return (4, -_TIER_RANK[a["tier"]], a["measure"])
    if a["standing"] is not None and not a["contradicted"]:
        return (3, 0, float(a["standing"]))
    if a["weak"]:
        return (2, 0, a["weak_rate"])
    return (1, 0, 0.0)


def _standing_of(c):
    s = c.get("standing")
    return float(s) if isinstance(s, (int, float)) and not isinstance(s, bool) else None


# ---------------------------------------------------------------- the pool, then the choice


def _prepare(candidates, records, availability, now, exclude, avoid, review_of, difficulty=None):
    """The workers that may be recommended at all: (eligible, passed, stats, author_maker). An unproven
    worker (flagged by workers.build_candidates: new, with fewer than MIN_ATTEMPTS judged attempts) is
    offered routine work only: above difficulty 1 it is passed over whatever benchmark it has."""
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
        if c.get("unproven") and isinstance(difficulty, int) and difficulty > 1:
            passed.append((w, "unproven: a new worker with no judged record is offered routine work (difficulty 1) only"))
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
    return eligible, passed, stats, author_maker


def _assess_all(eligible, stats, kind, difficulty, floors):
    """({worker: assessment}, best standing among the usable workers)."""
    standings = [s for s in (_standing_of(c) for c in eligible) if s is not None]
    best = max(standings) if standings else None
    return ({c["worker"]: assess(stats, c["worker"], kind, difficulty, _standing_of(c), best, floors)
             for c in eligible}, best)


def _make_key(stats, kind, difficulty, prefer):
    def rate(c):
        cell = _cell(stats, c["worker"], kind, difficulty)
        return (cell["good"] / cell["n"]) if cell["n"] else None

    def load_ratio(c):
        left = c.get("allowance_pct_left")
        if left is None and c.get("host_native"):
            return 0.0   # a host worker has no allowance to spread work across: the record decides
        weight = float(left) if left else UNKNOWN_ALLOWANCE
        return stats.get(c["worker"], {}).get("uses", 0) / max(weight, 1.0)

    def standing_key(c):
        s = _standing_of(c)
        return -s if s is not None else 1.0

    def key(c):
        r = rate(c)
        return (0 if _pattern_match(c, prefer) else 1,
                _price_tier(c),
                float(c["cost"]) if c.get("cost") is not None else float("inf"),
                standing_key(c),
                load_ratio(c),
                -(r if r is not None else -1.0),
                c["worker"])

    return key, rate, load_ratio


def _prefer_judged(capable, assessments, difficulty):
    """(workers, judged): above difficulty 1 a benchmark standing is a reason to try a worker on low-stakes
    work, not to prefer it to measured proof. When any capable worker is capable by a judged record for
    this kind (evidence a, or b from a harder difficulty of the kind), only those compete; failing that,
    those capable by the judged record across all kinds; failing that, everyone capable."""
    if difficulty is None or difficulty < 2:
        return list(capable), False
    for tiers in (("a", "b-higher"), ("b-all",)):
        own = [c for c in capable if assessments[c["worker"]]["tier"] in tiers]
        if own:
            return own, True
    return list(capable), False


def _select(eligible, assessments, difficulty):
    """(pool, basis): the workers to rank by price, and what put them there.
    basis is "capable" (see _prefer_judged), "weak" (nobody capable; judged evidence at an easier difficulty),
    "strongest" (nobody capable; the strongest known by evidence), "nothing" (nobody has any
    evidence) or "all-bad" (every usable worker has a thick bad record)."""
    live = [c for c in eligible if not assessments[c["worker"]]["bad"]]
    if not live:
        return list(eligible), "all-bad"
    capable = [c for c in live if assessments[c["worker"]]["capable"]]
    if capable:
        return _prefer_judged(capable, assessments, difficulty)[0], "capable"
    weak = [c for c in live if assessments[c["worker"]]["weak"]]
    if weak:
        return weak, "weak"
    top = max(strength(assessments[c["worker"]]) for c in live)
    pool = [c for c in live if strength(assessments[c["worker"]]) == top]
    return pool, ("nothing" if top[0] <= 1 else "strongest")


def _free_slot(choice, ranked, candidates, stats, kind, difficulty, basis, prefer, every):
    """The unproven worker that costs nothing extra (a flat or free plan) to try on this routine task
    instead of the usual choice, or None. One routine task in `every` (route.explore_free_one_in), a
    function of the judged record like the paid slot below, so the choice stays deterministic."""
    if choice is None or difficulty != 1 or basis != "capable" or not every or every < 1:
        return None
    if choice.get("unproven") or _pattern_match(choice, prefer):
        return None
    free = [c for c in ranked if c is not choice and c.get("unproven") and c.get("plan") == "flat"]
    total = sum(_cell(stats, c["worker"], kind, difficulty)["n"] for c in candidates)
    if not free or total % every != every - 1:
        return None
    return sorted(free, key=lambda c: (_cell(stats, c["worker"], kind, difficulty)["n"], c["worker"]))[0]


def choose(candidates, records, availability, kind, difficulty, review_of=None, now=0.0, exclude=(),
           avoid=None, prefer=None, floors=None, explore_free_every=EXPLORE_FREE_EVERY):
    """Pick one candidate, or none. Returns {"choice", "passed_over", "stats", "author_maker", ...}.
    `passed_over` is [(worker, plain reason)] covering every candidate not chosen. `avoid` and
    `prefer` are the user's own [{"pattern", "why"}] constraints; `floors` the standing floors."""
    now = float(now or 0)
    eligible, passed, stats, author_maker = _prepare(candidates, records, availability, now, exclude, avoid, review_of,
                                                     difficulty)
    assessments, best = _assess_all(eligible, stats, kind, difficulty, floors)
    key, rate, load_ratio = _make_key(stats, kind, difficulty, prefer)

    pool, basis = _select(eligible, assessments, difficulty) if eligible else ([], "none")
    detail = {}
    ranked = sorted(pool, key=key)

    def price_of(c):
        return (_price_tier(c), float(c["cost"]) if c.get("cost") is not None else float("inf"))

    if basis == "all-bad":
        ranked = sorted(pool, key=lambda c: (-(assessments[c["worker"]].get("measure") or 0.0), key(c)))
    choice = ranked[0] if ranked else None
    explored = None
    free_slot = _free_slot(choice, ranked, candidates, stats, kind, difficulty, basis, prefer, explore_free_every)
    if free_slot is not None:
        explored, choice = choice, free_slot
        ranked = [choice] + [c for c in ranked if c is not choice]
    elif (choice is not None and difficulty == 1 and basis == "capable" and not _pattern_match(choice, prefer)
            and _cell(stats, choice["worker"], kind, difficulty)["n"] >= MIN_ATTEMPTS):
        total = sum(_cell(stats, c["worker"], kind, difficulty)["n"] for c in candidates)
        if total >= EXPLORE_EVERY - 1 and total % EXPLORE_EVERY == EXPLORE_EVERY - 1:
            thinner = [c for c in ranked
                       if c is not choice
                       and _cell(stats, c["worker"], kind, difficulty)["n"] < MIN_ATTEMPTS
                       and price_of(c) <= price_of(choice)]
            if thinner:
                thinner.sort(key=key)
                explored, choice = choice, thinner[0]
                ranked = [choice] + [c for c in ranked if c is not choice]

    in_pool = {c["worker"] for c in ranked}
    if choice is not None:
        cheaper_than = price_of(choice)
        for c in eligible:
            if c is choice:
                continue
            a = assessments[c["worker"]]
            w = c["worker"]
            if w not in in_pool:
                reason, extra = _why_not(a, difficulty, basis, cheaper=price_of(c) < cheaper_than)
                passed.append((w, reason))
                if extra:
                    detail[w] = extra
                continue
            if explored is not None and c is explored:
                reason = ("the usual choice, passed over this once so an unproven worker that costs nothing extra "
                          "gathers evidence on routine work (about one task in %d)" % explore_free_every
                          if free_slot is not None else
                          "the usual choice, passed over this once so a cheaper thin-record worker "
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
            passed.append((w, reason))
    judged_first = basis == "capable" and _prefer_judged(pool, assessments, difficulty)[1]
    capable_n = len(pool) if basis == "capable" else 0
    return {"choice": choice, "passed_over": passed, "stats": stats, "author_maker": author_maker,
            "explored": explored["worker"] if explored else None, "explored_free": free_slot is not None,
            "load_ratios": {c["worker"]: load_ratio(c) for c in candidates},
            "assessments": assessments, "basis": basis, "capable_count": capable_n, "judged_first": judged_first,
            "best_standing": best, "passed_detail": detail, "floors": floors,
            "kind": kind, "difficulty": difficulty}


def _why_not(a, difficulty, basis, cheaper):
    """(plain reason, short per-worker detail) for a worker kept out of the pool by what is known
    about its capability. The reason text is the same for every worker it applies to, so reasons group."""
    lead = "cheaper than the choice but " if cheaper else ""
    if a["bad"]:
        where = "" if a.get("at") == difficulty else " (at an easier difficulty, which counts against a harder one)"
        return ("%saccepted rate below the bar over %d attempts%s" % ("cheaper but " if cheaper else "", a["n"], where),
                "%d of %d accepted" % (a["good"], a["n"]))
    if basis == "capable":
        if a["capable"]:
            if a["tier"] == "b-all":
                return (lead + "its only judged proof is across other kinds, and a worker with a judged record "
                        "for this kind is usable", None)
            return (lead + "capable only by benchmark standing or as an exploration; above difficulty 1 a worker "
                    "with a judged record is preferred to a benchmark",
                    ("standing %g" % a["standing"]) if a["standing"] is not None else None)
        if a.get("below"):
            return (lead + "not capable enough for difficulty %d: benchmark standing under the %g needed "
                    "(%g%% of the best usable standing, %g)" % (difficulty, a["needed"], a["floor"], a["best"]),
                    "standing %g" % a["standing"])
        if a["contradicted"]:
            return (lead + "not capable enough: its own thin record for this kind repeats rejections, which "
                    "cancels its benchmark standing", None)
        if a["weak"]:
            return (lead + "not capable enough for difficulty %d: its only judged proof is at an easier "
                    "difficulty, and a worker with better evidence is usable" % difficulty, None)
        return (lead + "not capable enough for difficulty %d: nothing is recorded about it that proves it; "
                "unknown workers are tried on difficulty 1 only" % difficulty, None)
    if basis == "weak":
        return (lead + "less evidence: no worker is capable by the evidence, so the one with judged proof at an "
                "easier difficulty was taken", None)
    return (lead + "weaker known evidence than the strongest known usable worker",
            ("standing %g" % a["standing"]) if a["standing"] is not None else None)


# ---------------------------------------------------------------- the retry ladder


def retry_choice(candidates, records, availability, kind, difficulty, rejected, rejections,
                 now=0.0, exclude=(), avoid=None, prefer=None, floors=None, review_of=None):
    """Who gets a task again after `rejected` (a worker id) was rejected `rejections` times in this chain.
    The first retry goes back to the same worker while it is still usable and has no poor record.
    After that: the cheapest capable worker whose evidence is strictly better than the rejected one's, or, when there is none,
    the strongest known usable worker other than it (and only the rejected one itself when nobody
    else is usable). Returns {"choice", "step", "assessments", ...}; step is "same", "better",
    "strongest" or "only", and choice is None when nobody is usable. Pure; the caller supplies facts."""
    now = float(now or 0)
    eligible, passed, stats, author_maker = _prepare(candidates, records, availability, now, exclude, avoid, review_of,
                                                     difficulty)
    assessments, best = _assess_all(eligible, stats, kind, difficulty, floors)
    key, _rate, _load = _make_key(stats, kind, difficulty, prefer)
    out = {"choice": None, "step": None, "passed_over": passed, "stats": stats, "author_maker": author_maker,
           "assessments": assessments, "best_standing": best, "kind": kind, "difficulty": difficulty,
           "rejected": rejected, "rejections": rejections}
    mine = next((c for c in eligible if c["worker"] == rejected), None)
    if int(rejections or 0) <= 1 and mine is not None and not assessments[rejected]["bad"]:
        out.update(choice=mine, step="same")
        return out
    others = [c for c in eligible if c["worker"] != rejected and not assessments[c["worker"]]["bad"]]
    if not others:
        if mine is not None:
            out.update(choice=mine, step="only")
        return out
    gone = next((c for c in candidates if c["worker"] == rejected), None)
    floor = (strength(assessments[rejected]) if mine is not None else
             strength(assess(stats, rejected, kind, difficulty, _standing_of(gone) if gone else None, best, floors)))
    better = [c for c in others if assessments[c["worker"]]["capable"] and strength(assessments[c["worker"]]) > floor]
    better = _prefer_judged(better, assessments, difficulty)[0]
    if better:
        out.update(choice=sorted(better, key=key)[0], step="better")
        return out
    top = max(strength(assessments[c["worker"]]) for c in others)
    out.update(choice=sorted([c for c in others if strength(assessments[c["worker"]]) == top], key=key)[0],
               step="strongest")
    return out


# ---------------------------------------------------------------- the explanation


MAX_EXPLAIN_LINES = 20
EXPLAIN_TAIL_LINES = 5  # worker, mechanism, exclusion note, cold-start notice, request for facts


def _pct(x):
    return "%d%%" % round(100.0 * x)


def _short(text, width=60):
    text = str(text or "no source stated")
    return text if len(text) <= width else text[:width - 3].rstrip() + "..."


def evidence_line(a, kind, difficulty, choice, basis):
    """One line saying which evidence decided that the chosen worker is capable, with the numbers."""
    if a is None:
        return "evidence: none recorded"
    if a["bad"]:
        return ("evidence: none favourable; every usable worker has a poor record, so this one has the best "
                "accepted rate (%d of %d for %s)" % (a["good"], a["n"], kind))
    tier = a["tier"]
    if tier == "a":
        return ("evidence (a), judged record: %d of %d accepted for %s at difficulty %d (%s, bar %s)"
                % (a["good"], a["n"], kind, difficulty, _pct(a["measure"]), _pct(MIN_ACCEPTED_RATE)))
    if tier == "b-higher":
        return ("evidence (b), judged record at a harder difficulty: %d of %d accepted for %s at difficulty %d "
                "(%s), which proves difficulty %d" % (a["good"], a["n"], kind, a["at"], _pct(a["measure"]), difficulty))
    if tier == "b-all":
        return ("evidence (b), judged record across all kinds at difficulty %d: %d of %d accepted (%s)"
                % (a["at"], a["good"], a["n"], _pct(a["measure"])))
    if tier == "standing":
        src = _short(choice.get("standing_source"))
        if a["capable"]:
            if a["floor"]:
                need = "above the %g needed (%g%% of the best usable standing, %g)" % (a["needed"], a["floor"], a["best"])
            else:
                need = "no floor at difficulty %d" % difficulty
            return ("evidence (c), benchmark standing: %g (%s, %s), %s; no judged record for this decides it"
                    % (a["standing"], src, choice.get("standing_date") or "no date stated", need))
        return ("evidence (c), benchmark standing only: %g (%s, %s), the strongest known; it is under the %g "
                "needed for difficulty %d" % (a["standing"], src, choice.get("standing_date") or "no date stated",
                                              a["needed"], difficulty))
    if tier == "unknown":
        return "evidence (d): nothing is known about this worker yet; it is an exploration on low-stakes work"
    if a.get("weak"):
        return ("evidence (b, weak): %d of %d accepted for %s at the easier difficulty %d; no worker has better evidence"
                % (a["weak_good"], a["weak_n"], kind, a["weak_at"]))
    return "evidence: nothing is recorded about any usable worker for %s at difficulty %d" % (kind, difficulty)


def explain_choice(result, kind, difficulty):
    """Plain lines for `--explain`, from a choose() result."""
    choice = result["choice"]
    lines = []
    basis = result.get("basis")
    if choice is None:
        lines.append("no usable worker for kind %s at difficulty %s" % (kind, difficulty))
    else:
        cell = _cell(result["stats"], choice["worker"], kind, difficulty)
        a = (result.get("assessments") or {}).get(choice["worker"])
        if choice.get("plan") == "flat":
            price = "a flat-rate plan with allowance left, so one more task costs nothing extra"
        elif choice.get("cost") is not None:
            price = "the cheapest known per-use price among the workers that are capable enough"
        elif choice.get("plan") == "per-use":
            price = "billed per use; no cheaper flat-rate worker is usable"
        else:
            price = "price unknown, treated as most expensive until learned; nothing priced cheaper is capable"
        if basis in (None, "capable"):
            head = "chose %s: %s" % (choice["worker"], price)
            if result.get("capable_count"):
                head += "; %d usable worker(s) capable %s" % (
                    result["capable_count"], "by a judged record" if result.get("judged_first") else "enough")
        else:
            head = "chose %s: none is proven capable for %s at difficulty %s" % (choice["worker"], kind, difficulty)
            head += ("; taken for the strongest known evidence (%s)" % price if basis == "strongest" else
                     "; %s" % ("every usable worker has a poor record" if basis == "all-bad" else
                               "nothing is recorded about any usable worker, so this is a trial" if basis == "nothing" else
                               "taken for the judged proof at an easier difficulty (%s)" % price))
        lines.append(head)
        if a is not None:
            lines.append(evidence_line(a, kind, difficulty, choice, basis))
        if result.get("explored"):
            lines.append("this is an exploration pick: %s was the usual choice, passed over once so %s gathers evidence"
                         % (result["explored"], "an unproven worker that costs nothing extra"
                            if result.get("explored_free") else "a cheaper thin-record worker"))
        if result.get("author_maker"):
            choice_maker = choice.get("maker") or maker_of(choice.get("model") or choice["worker"])
            if choice_maker != result["author_maker"]:
                lines.append("it is from a different maker than the author (%s)" % result["author_maker"])
            else:
                lines.append("no worker from a different maker than the author (%s) is available, "
                             "so the review stays with the same maker" % result["author_maker"])
    detail = result.get("passed_detail") or {}
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
        shown = ", ".join(("%s [%s]" % (n, detail[n])) if n in detail else n for n in names[:3])
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
