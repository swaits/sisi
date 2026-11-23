"""Textual (span-preserving) editing of hook JSON files, plus sisi hook-command recognition.

Install and uninstall must never re-serialise a user's whole config: that rewrites number and string
spellings (1e3 becomes 1000.0, \\u escapes change form) and drops duplicate keys. The parser here records
the exact span of every value, so merging or removing sisi's hook entries edits only those spans and
leaves every other byte as it was. Anything the parser cannot handle with certainty (comments, trailing
commas, duplicate keys on a path being edited, unexpected shapes) raises Uncertain and the caller skips
that file instead of rewriting it.
"""
import json, os, shlex


class Uncertain(ValueError):
    pass


# ---- sisi hook-command recognition -------------------------------------------
def sisi_invocation(command):
    """The sisi invocation inside a hook command string, as a token list, or None.

    Recognises the bare form (`/path/sisi gate ...`, written by older installs) and the fail-open form
    (`test -x /path/sisi || exit 0 ; /path/sisi gate ...`) written now, so a deleted sisi folder makes
    every registered hook exit 0 silently instead of 127 on every turn."""
    if not isinstance(command, str):
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if (len(parts) >= 9 and parts[0] == "test" and parts[1] == "-x" and parts[3] == "||"
            and parts[4] == "exit" and parts[5] == "0" and parts[6] == ";" and parts[7] == parts[2]):
        return parts[7:]
    if len(parts) >= 2 and os.path.basename(parts[0]) == "sisi":
        return parts
    return None


def is_ours_command(command, sub):
    inv = sisi_invocation(command)
    return bool(inv) and len(inv) >= 2 and os.path.basename(inv[0]) == "sisi" and inv[1] == sub


def fail_open_command(launcher, sub, tool, subagent=False):
    q = shlex.quote(launcher)
    args = sub + (" --subagent" if subagent else "") + " --tool " + tool
    return "test -x %s || exit 0 ; %s %s" % (q, q, args)


# ---- span-preserving JSON parser ---------------------------------------------
class Node:
    __slots__ = ("kind", "start", "end", "value", "members", "items")

    def __init__(self, kind, start, end, value=None, members=None, items=None):
        self.kind, self.start, self.end, self.value = kind, start, end, value
        self.members, self.items = members, items


_WS = " \t\r\n"
_NUM_OK = set("0123456789+-.eE")


def _skip(s, i):
    while i < len(s) and s[i] in _WS:
        i += 1
    return i


def parse(text):
    if not isinstance(text, str):
        raise Uncertain("not text")
    node, i = _value(text, _skip(text, 0))
    if _skip(text, i) != len(text):
        raise Uncertain("trailing characters after the JSON value")
    return node


def _value(s, i):
    if i >= len(s):
        raise Uncertain("unexpected end of input")
    c = s[i]
    if c == "{":
        return _object(s, i)
    if c == "[":
        return _array(s, i)
    if c == '"':
        return _string(s, i)
    if c == "-" or c.isdigit():
        j = i
        while j < len(s) and s[j] in _NUM_OK:
            j += 1
        raw = s[i:j]
        try:
            v = json.loads(raw)
        except ValueError:
            raise Uncertain("bad number %r" % raw)
        if not isinstance(v, (int, float)):
            raise Uncertain("bad number %r" % raw)
        return Node("num", i, j, v), j
    for lit in ("true", "false", "null"):
        if s.startswith(lit, i):
            return Node("lit", i, i + len(lit), lit), i + len(lit)
    raise Uncertain("unexpected character %r" % c)


def _string(s, i):
    j = i + 1
    while j < len(s):
        c = s[j]
        if c == '"':
            raw = s[i:j + 1]
            try:
                return Node("str", i, j + 1, json.loads(raw)), j + 1
            except ValueError:
                raise Uncertain("bad string")
        if c == "\\":
            j += 2
            continue
        if c < " ":
            raise Uncertain("control character in string")
        j += 1
    raise Uncertain("unterminated string")


def _object(s, i):
    members = []
    j = _skip(s, i + 1)
    if j < len(s) and s[j] == "}":
        return Node("obj", i, j + 1, members=[]), j + 1
    while True:
        j = _skip(s, j)
        if j >= len(s) or s[j] != '"':
            raise Uncertain("expected object key")
        k, j = _string(s, j)
        j = _skip(s, j)
        if j >= len(s) or s[j] != ":":
            raise Uncertain("expected ':' in object")
        v, j = _value(s, _skip(s, j + 1))
        members.append((k.value, k, v))
        j = _skip(s, j)
        if j < len(s) and s[j] == ",":
            j += 1
            continue
        if j < len(s) and s[j] == "}":
            return Node("obj", i, j + 1, members=members), j + 1
        raise Uncertain("expected ',' or '}' in object")


def _array(s, i):
    items = []
    j = _skip(s, i + 1)
    if j < len(s) and s[j] == "]":
        return Node("arr", i, j + 1, items=[]), j + 1
    while True:
        v, j = _value(s, _skip(s, j))
        items.append(v)
        j = _skip(s, j)
        if j < len(s) and s[j] == ",":
            j += 1
            continue
        if j < len(s) and s[j] == "]":
            return Node("arr", i, j + 1, items=items), j + 1
        raise Uncertain("expected ',' or ']' in array")


# ---- span edits ---------------------------------------------------------------
def member(node, key):
    """(index, value_node) for key, None if absent; Uncertain on duplicates of a key being navigated."""
    if node.kind != "obj":
        raise Uncertain("expected an object")
    found = None
    for idx, (k, _kn, v) in enumerate(node.members):
        if k == key:
            if found is not None:
                raise Uncertain("duplicate key %r" % key)
            found = (idx, v)
    return found


def _indent_at(text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    seg = text[line_start:pos]
    return seg if seg.strip(" \t") == "" else ""


def _pretty(text, node):
    return "\n" in text[node.start:node.end]


def insert_member(text, obj, key, value_text):
    frag = "%s: %s" % (json.dumps(key), value_text)
    if not obj.members:
        return text[:obj.start] + "{" + frag + "}" + text[obj.end:]
    last = obj.members[-1][2]
    if _pretty(text, obj):
        ind = _indent_at(text, obj.members[-1][1].start)
        return text[:last.end] + ",\n" + ind + frag + text[last.end:]
    return text[:last.end] + ", " + frag + text[last.end:]


def append_element(text, arr, elem_text):
    if not arr.items:
        return text[:arr.start] + "[" + elem_text + "]" + text[arr.end:]
    last = arr.items[-1]
    if _pretty(text, arr):
        ind = _indent_at(text, last.start)
        return text[:last.end] + ",\n" + ind + elem_text + text[last.end:]
    return text[:last.end] + ", " + elem_text + text[last.end:]


def _remove_among(text, spans, idx):
    """Remove spans[idx] (a (start,end) pair) plus exactly one separating comma."""
    start, end = spans[idx]
    if len(spans) == 1:
        return text[:start] + text[end:]
    if idx > 0:
        return text[:spans[idx - 1][1]] + text[end:]
    return text[:start] + text[spans[1][0]:]


def remove_member(text, obj, key):
    found = member(obj, key)
    if found is None:
        return text
    idx, _v = found
    spans = [(kn.start, v.end) for _k, kn, v in obj.members]
    return _remove_among(text, spans, idx)


def remove_element(text, arr, idx):
    return _remove_among(text, [(v.start, v.end) for v in arr.items], idx)


def replace_node(text, node, new_text):
    return text[:node.start] + new_text + text[node.end:]


def _dump(v):
    return json.dumps(v, ensure_ascii=False)


def _entry_command(entry_node):
    """The command string of a hook entry object, or None. Flat entries may use bash or command."""
    if entry_node.kind != "obj":
        return None
    for key in ("bash", "command"):
        found = None
        for k, _kn, v in entry_node.members:
            if k == key:
                found = v
        if found is not None and found.kind == "str":
            return found.value
    return None


def _entry_is_ours(entry_node, sub, require_type=False):
    cmd = _entry_command(entry_node)
    if cmd is None or not is_ours_command(cmd, sub):
        return False
    for k, _kn, v in entry_node.members:
        if k == "type":
            return v.kind == "str" and v.value == "command"
    return not require_type


def _update_entry(text, entry_node, want):
    """Replace the given scalar fields on one entry object, in place by span."""
    edits = []  # (start, end, replacement) on disjoint spans, plus optional inserts
    for key, val in want.items():
        found = None
        for k, kn, v in entry_node.members:
            if k == key:
                found = v
        if found is not None:
            if found.kind == "num" and isinstance(val, (int, float)) and found.value == val:
                continue
            if found.kind == "str" and found.value == val:
                continue
            edits.append((found.start, found.end, _dump(val)))
    for start, end, rep in sorted(edits, reverse=True):
        text = text[:start] + rep + text[end:]
    # inserts after replacements: reparse to locate the entry again by identity of its command is fragile,
    # so callers keep entry objects with all fields present; inserts are handled by reparse in callers.
    return text


def _insert_missing_fields(text, entry_node, want):
    for key, val in want.items():
        if all(k != key for k, _kn, _v in entry_node.members):
            return insert_member(text, entry_node, key, _dump(val)), True
    return text, False


def _update_fields(text, locate, want):
    """locate(text) -> a fresh entry Node. Replace differing fields, then insert missing ones."""
    text = _update_entry(text, locate(text), want)
    while True:
        text, did = _insert_missing_fields(text, locate(text), want)
        if not did:
            return text


def _root(text):
    root = parse(text)
    if root.kind != "obj":
        raise Uncertain("top level is not a JSON object")
    return root


def _hooks_node(text, required=True):
    root = _root(text)
    found = member(root, "hooks")
    if found is None:
        return root, None
    node = found[1]
    if node.kind == "lit" and node.value == "null":
        return root, node
    if node.kind != "obj":
        if required:
            raise Uncertain("'hooks' is not an object")
        return root, None
    return root, node


def _seed_version(text, created_version):
    if created_version is None:
        return text
    root = _root(text)
    if member(root, "version") is None:
        return insert_member(text, root, "version", _dump(created_version))
    return text


# ---- nested hook groups --------------------------------------------------------
def _nested_ours(text, event, sub):
    """[(group_index, entry_index)] of sisi entries for one event, in document order."""
    _r, hooks = _hooks_node(text, required=False)
    if hooks is None or hooks.kind != "obj":
        return []
    found = member(hooks, event)
    if found is None or found[1].kind != "arr":
        return []
    out = []
    for gi, g in enumerate(found[1].items):
        if g.kind != "obj":
            continue
        hm = None
        for k, _kn, v in g.members:
            if k == "hooks":
                hm = v
        if hm is None or hm.kind != "arr":
            continue
        for ei, e in enumerate(hm.items):
            if e.kind == "obj" and _entry_is_ours(e, sub):
                out.append((gi, ei))
    return out


def _nested_locate(text, event, loc):
    _r, hooks = _hooks_node(text)
    arr = member(hooks, event)[1]
    g = arr.items[loc[0]]
    hm = [v for k, _kn, v in g.members if k == "hooks"][0]
    return arr, g, hm, hm.items[loc[1]]


def _nested_remove_at(text, event, loc):
    arr, _g, hm, _e = _nested_locate(text, event, loc)
    text = remove_element(text, hm, loc[1])
    # cascade: drop the group if its hooks list is now empty, then the event if its list is empty
    _r, hooks = _hooks_node(text)
    arr = member(hooks, event)[1]
    if loc[0] < len(arr.items):
        g = arr.items[loc[0]]
        hm2 = [v for k, _kn, v in g.members if k == "hooks"] if g.kind == "obj" else []
        if hm2 and hm2[0].kind == "arr" and not hm2[0].items:
            text = remove_element(text, arr, loc[0])
    _r, hooks = _hooks_node(text)
    found = member(hooks, event)
    if found is not None and found[1].kind == "arr" and not found[1].items:
        text = remove_member(text, hooks, event)
    return text


def _nested_entry(s):
    e = {"type": "command", "command": s["cmd"], "timeout": s["timeout"]}
    if s.get("name"):
        e["name"] = s["name"]
    return e


def _nested_group(s):
    g = {"matcher": s["matcher"], "hooks": [_nested_entry(s)]} if s.get("matcher") else {"hooks": [_nested_entry(s)]}
    return g


def _add_nested_event(text, event, s):
    _r, hooks = _hooks_node(text)
    found = member(hooks, event)
    if found is None:
        return insert_member(text, hooks, event, _dump([_nested_group(s)]))
    node = found[1]
    if node.kind == "lit" and node.value == "null":
        return replace_node(text, node, _dump([_nested_group(s)]))
    if node.kind != "arr":
        raise Uncertain("hooks.%s is not a list" % event)
    ours = _nested_ours(text, event, s["sub"])
    while len(ours) > 1:  # keep exactly one registration of this command per event
        text = _nested_remove_at(text, event, ours[-1])
        ours = _nested_ours(text, event, s["sub"])
    if ours:
        want = _nested_entry(s)
        return _update_fields(text, lambda t: _nested_locate(t, event, _nested_ours(t, event, s["sub"])[0])[3], want)
    _r, hooks = _hooks_node(text)
    return append_element(text, member(hooks, event)[1], _dump(_nested_group(s)))


def add_nested(text, spec, created_version=None):
    """Merge nested hook groups into JSON text. spec: {event: {cmd, timeout, sub, matcher?, name?}}."""
    text = _seed_version(text, created_version)
    _r, hooks = _hooks_node(text)
    if hooks is None:
        built = {ev: [_nested_group(s)] for ev, s in spec.items()}
        return insert_member(text, _root(text), "hooks", _dump(built))
    if hooks.kind == "lit":  # "hooks": null
        built = {ev: [_nested_group(s)] for ev, s in spec.items()}
        return replace_node(text, hooks, _dump(built))
    for ev, s in spec.items():
        text = _add_nested_event(text, ev, s)
    return text


def remove_nested(text, subs, created_version=None, drop_version=False, drop_empty_hooks=True):
    for ev, sub in subs.items():
        while True:
            ours = _nested_ours(text, ev, sub)
            if not ours:
                break
            text = _nested_remove_at(text, ev, ours[0])
    _r, hooks = _hooks_node(text, required=False)
    if hooks is not None and hooks.kind == "obj" and not hooks.members and drop_empty_hooks:
        text = remove_member(text, _root(text), "hooks")
    if drop_version and created_version is not None:
        root = _root(text)
        found = member(root, "version")
        if found is not None and found[1].kind == "num" and found[1].value == created_version:
            text = remove_member(text, root, "version")
    return text


# ---- flat hook lists -------------------------------------------------------------
def _flat_ours(text, event, sub):
    _r, hooks = _hooks_node(text, required=False)
    if hooks is None or hooks.kind != "obj":
        return []
    found = member(hooks, event)
    if found is None or found[1].kind != "arr":
        return []
    return [i for i, e in enumerate(found[1].items) if e.kind == "obj" and _entry_is_ours(e, sub)]


def _flat_locate(text, event, idx):
    _r, hooks = _hooks_node(text)
    return member(hooks, event)[1].items[idx]


def _flat_remove_at(text, event, idx):
    _r, hooks = _hooks_node(text)
    text = remove_element(text, member(hooks, event)[1], idx)
    _r, hooks = _hooks_node(text)
    found = member(hooks, event)
    if found is not None and found[1].kind == "arr" and not found[1].items:
        text = remove_member(text, hooks, event)
    return text


def _add_flat_event(text, event, s):
    _r, hooks = _hooks_node(text)
    found = member(hooks, event)
    if found is None:
        return insert_member(text, hooks, event, _dump([s["entry"]]))
    node = found[1]
    if node.kind == "lit" and node.value == "null":
        return replace_node(text, node, _dump([s["entry"]]))
    if node.kind != "arr":
        raise Uncertain("hooks.%s is not a list" % event)
    ours = _flat_ours(text, event, s["sub"])
    while len(ours) > 1:
        text = _flat_remove_at(text, event, ours[-1])
        ours = _flat_ours(text, event, s["sub"])
    if ours:
        return _update_fields(text, lambda t: _flat_locate(t, event, _flat_ours(t, event, s["sub"])[0]), s["entry"])
    _r, hooks = _hooks_node(text)
    return append_element(text, member(hooks, event)[1], _dump(s["entry"]))


def add_flat(text, spec, created_version=None):
    """Merge flat hook lists into JSON text. spec: {event: {sub, entry: {..}}}."""
    text = _seed_version(text, created_version)
    _r, hooks = _hooks_node(text)
    if hooks is None:
        built = {ev: [s["entry"]] for ev, s in spec.items()}
        return insert_member(text, _root(text), "hooks", _dump(built))
    if hooks.kind == "lit":
        built = {ev: [s["entry"]] for ev, s in spec.items()}
        return replace_node(text, hooks, _dump(built))
    for ev, s in spec.items():
        text = _add_flat_event(text, ev, s)
    return text


def backup_drop_flags(orig_text, created_version):
    """(drop_empty_hooks, drop_version) for uninstall, derived from the pre-install backup text:
    empty containers sisi added may be removed; ones the user already had stay."""
    if orig_text is None:
        return True, created_version is not None
    try:
        root = _root(orig_text)
    except Uncertain:
        return True, False
    return (member(root, "hooks") is None,
            created_version is not None and member(root, "version") is None)


def remove_flat(text, subs, created_version=None, drop_version=False, drop_empty_hooks=True):
    for ev, sub in subs.items():
        while True:
            ours = _flat_ours(text, ev, sub)
            if not ours:
                break
            text = _flat_remove_at(text, ev, ours[0])
    _r, hooks = _hooks_node(text, required=False)
    if hooks is not None and hooks.kind == "obj" and not hooks.members and drop_empty_hooks:
        text = remove_member(text, _root(text), "hooks")
    if drop_version and created_version is not None:
        root = _root(text)
        found = member(root, "version")
        if found is not None and found[1].kind == "num" and found[1].value == created_version:
            text = remove_member(text, root, "version")
    return text
