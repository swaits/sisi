"""Reading a model id: its maker, line, class and version. Pure: no file access, no clock.

A first guess from the name alone, and the recorded facts that override it. The words that mark
a class (tier words) or mean nothing (ignored words) are data passed in, loaded from
canon/model-words.json by the caller.

What is read from an id (the part after the provider, case aside):
  version  the numbers in it, as a tuple compared numerically (5.10 is newer than 5.9); a date in it
           (20261101 or 2026-11-01) is kept apart and compared as a date. A letter in front of a number
           (v4.1, k2.7) is a marker and is dropped.
  line     the name words before the version that identify the model line (the maker's own name leading
           them is dropped: "abc-flash-5.4" and "abc-5.4-flash" both have no extra line name).
  class    the tier words, before or after the version, or "standard" when there is none. The class
           label for ordering and display adds the line when there is one: "wonder", "wonder-full".
  maker    a recorded maker fact, else the first name word.
An id with no version, or with a word after the version that the data does not know, cannot be read
with confidence: its class is "unknown" and it takes part in no comparison of versions.

A recorded fact (class, family, released, maker) always beats the reading. A bare host alias with no
version in it (the host resolves it to its current model of that class) counts as the newest version
of its class, once a class fact says which class that is.
"""
import re

STANDARD = "standard"
UNKNOWN = "unknown"
_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})-?(\d{2})-?(\d{2})(?!\d)")
_NUM = re.compile(r"\d+(?:\.\d+)*")
_SIZE = re.compile(r"\d+(?:\.\d+)?[bkm]")
_PREFIXED = re.compile(r"([a-z]*)(\d+(?:\.\d+)*)")
_SUFFIXED = re.compile(r"(\d+(?:\.\d+)*)([a-z]+)")
_WORD = re.compile(r"[a-z]+")


def _model_part(worker):
    return str(worker or "").strip().lower().rsplit("/", 1)[-1]


def _numbers(token):
    return [int(x) for x in token.split(".")]


def parse(worker, words, maker=None):
    """What the id alone says: {maker, line, family, tiers, class, label, version, date, confident, unknown_tokens}.
    `words` is {"tiers": [...], "ignore": [...]}. `maker` is a recorded maker fact, if any."""
    tiers_known = {str(w).lower() for w in (words or {}).get("tiers") or []}
    ignored = {str(w).lower() for w in (words or {}).get("ignore") or []}
    s = _model_part(worker)
    dates = []

    def take_date(m):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            dates.append("%s-%s-%s" % (y, mo, d))
            return " "
        return m.group(0)

    s = _DATE.sub(take_date, s)
    names, tiers, nums, unknown = [], [], [], []
    started = closed = False

    def number(token):
        nonlocal started
        if closed:
            unknown.append(token)
        else:
            nums.extend(_numbers(token))
            started = True

    def word(token):
        nonlocal closed
        if token in tiers_known:
            tiers.append(token)
        elif not started:
            names.append(token)
            return
        else:
            unknown.append(token)
        if started:
            closed = True

    for t in (x for x in re.split(r"[-_:@\s]+", s) if x):
        if t in ignored:
            continue
        if _NUM.fullmatch(t):
            number(t)
        elif _SIZE.fullmatch(t):
            tiers.append(t)
        elif _PREFIXED.fullmatch(t) and t not in tiers_known:
            prefix, num = _PREFIXED.fullmatch(t).groups()
            if prefix and started:
                unknown.append(t)
                closed = True
                continue
            if prefix and (len(prefix) > 1 or not names):
                names.append(prefix)
            number(num)
        elif _SUFFIXED.fullmatch(t):
            num, suffix = _SUFFIXED.fullmatch(t).groups()
            number(num)
            if suffix in ignored:
                continue
            word(suffix)
        elif _WORD.fullmatch(t):
            word(t)
        else:
            unknown.append(t)
            if started:
                closed = True
    first = names[0] if names else ""
    mk = (str(maker).lower() if maker else first)
    line = list(names)
    if line and line[0] == mk:
        line = line[1:]
    cls = "-".join(tiers) if tiers else STANDARD
    version = tuple(nums)
    date = max(dates) if dates else None
    confident = bool(names) and bool(version or date) and not unknown
    return {"maker": mk, "line": "-".join(line), "family": "-".join(names), "tiers": tuple(tiers),
            "class": cls if confident else UNKNOWN, "label": _label("-".join(line), cls) if confident else UNKNOWN,
            "version": version or None, "date": date, "confident": confident, "unknown_tokens": unknown}


def _label(line, cls):
    """The class as the maker's classes are listed: the line name and the tier, or "standard"."""
    if cls in (None, "", STANDARD):
        return line or STANDARD
    return "%s-%s" % (line, cls) if line else cls


def _normal_class(line, cls):
    """A recorded class, lower case, with the line name taken off when the lead agent wrote the whole label."""
    c = str(cls or "").strip().lower()
    if c in (line, "") and line:
        return STANDARD
    if line and c.startswith(line + "-"):
        return c[len(line) + 1:]
    return c or STANDARD


def resolve(worker, words, fact=None, host_native=False, maker_hint=None):
    """The model's identity: parse the id, then let a recorded fact override it. Returns
      {key, maker, line, class, label, version, date, released, alias, source}
    source is "fact" (recorded), "guess" (read from the id, not yet confirmed) or "unknown"
    (no key: the model takes part in no comparison of versions)."""
    fact = fact if isinstance(fact, dict) else {}
    p = parse(worker, words, maker=fact.get("maker") or maker_hint)
    released = str(fact["released"]) if fact.get("released") else None
    maker = p["maker"]
    line = str(fact["family"]).strip().lower() if fact.get("family") else p["line"]
    if fact.get("family") and line == maker:
        line = ""
    out = {"key": None, "maker": maker, "line": line, "class": UNKNOWN, "label": UNKNOWN, "version": p["version"],
           "date": p["date"], "released": released, "alias": False, "source": UNKNOWN}
    if fact.get("class"):
        cls = _normal_class(line, fact["class"])
        out.update(source="fact")
    elif p["confident"]:
        cls = p["class"]
        out.update(source="guess")
    else:
        return out
    out.update({"class": cls, "label": _label(line, cls), "key": (maker, line, cls)})
    if host_native and not (p["version"] or p["date"]) and out["source"] == "fact":
        out["alias"] = True
    return out


def compare(a, b):
    """1 when a is the more recently released model, -1 when b is, 0 when equal or unknowable. A recorded
    release date on both decides; else the version numbers on both; else the dates in the ids on both. A bare
    alias is the newest of its class."""
    if a.get("alias") or b.get("alias"):
        return (1 if a.get("alias") else 0) - (1 if b.get("alias") else 0)
    ra, rb = a.get("released"), b.get("released")
    if ra and rb and ra != rb:
        return 1 if ra > rb else -1
    va, vb = a.get("version"), b.get("version")
    if va and vb:
        n = max(len(va), len(vb))
        pa, pb = tuple(va) + (0,) * (n - len(va)), tuple(vb) + (0,) * (n - len(vb))
        if pa != pb:
            return 1 if pa > pb else -1
        da, db = a.get("date"), b.get("date")
        if da and db and da != db:
            return 1 if da > db else -1
        return 0
    if not va and not vb:
        da, db = a.get("date"), b.get("date")
        if da and db and da != db:
            return 1 if da > db else -1
    return 0


def days(date):
    """A YYYY-MM-DD date as a number of days that sorts correctly (months of 31 days: only the order matters); 0 when
    there is no date."""
    d = str(date or "")
    if len(d) >= 10 and d[:4].isdigit() and d[5:7].isdigit() and d[8:10].isdigit():
        return int(d[0:4]) * 372 + int(d[5:7]) * 31 + int(d[8:10])
    return 0
