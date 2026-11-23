"""Path resolution. Everything that touches tool config, personal data or state goes through here.

Three places, three owners:
  product   REPO            the clone: code, base rulebook, verifier and recipe library. Never written at run time.
  personal  data()          everything sisi learned for this person (its own local git repository).
  scratch   state()         rebuildable or evidential files: harvest.db, locks, logs, session records, results.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def home():
    return os.environ.get("SISI_HOME") or os.path.expanduser("~")


def state():
    return os.environ.get("SISI_STATE") or os.path.join(home(), ".local", "state", "sisi")


def data():
    """Personal data folder: SISI_DATA, else under SISI_HOME (tests), else $XDG_DATA_HOME/sisi, else ~/.local/share/sisi."""
    d = os.environ.get("SISI_DATA")
    if d:
        return d
    if os.environ.get("SISI_HOME"):
        return os.path.join(home(), ".local", "share", "sisi")
    x = os.environ.get("XDG_DATA_HOME")
    if x and os.path.isabs(x):
        return os.path.join(x, "sisi")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "sisi")


def data_file(*parts):
    return os.path.join(data(), *parts)


def personal(name):
    """A personal file. Until `sisi update` has moved it, a copy still sitting in the state dir is used,
    so an installation that has not been updated yet keeps working."""
    p = data_file(name)
    if not os.path.exists(p):
        old = state_file(name)
        if os.path.exists(old):
            return old
    return p


def generated():
    """The effective rulebook (base rules with the personal overlay applied). What the tools load."""
    return data_file("generated", "core.md")


def overlay_dir(*parts):
    return data_file("overlay", *parts)


def canon(*parts):
    return os.path.join(REPO, "canon", *parts)


def lib():
    """Where stable releases live: SISI_LIB, else <home>/.local/lib/sisi."""
    return os.environ.get("SISI_LIB") or os.path.join(home(), ".local", "lib", "sisi")


def releases_dir():
    return os.path.join(lib(), "releases")


def current_link():
    return os.path.join(lib(), "current")


def stable_launcher():
    """The launcher of the stable copy (through the `current` link), or None when no release has been made."""
    p = os.path.join(current_link(), "bin", "sisi")
    return p if os.path.isfile(p) else None


def launcher():
    """What the tools are wired to: the stable copy when one exists, else the clone itself."""
    return stable_launcher() or os.path.join(REPO, "bin", "sisi")


def product_root():
    """The folder the tools run: the stable copy (through the link) when one exists, else the clone."""
    return current_link() if stable_launcher() else REPO


def personal_config():
    import json
    try:
        with open(personal("config.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def set_personal_config(keys, value, msg):
    """Set (or with None remove) a nested key in the personal config.json; one commit in the personal repository."""
    import json
    from . import pdata
    cfg = personal_config()
    d = cfg
    for k in keys[:-1]:
        d = d.setdefault(k, {}) if isinstance(d.get(k, {}), dict) else d.setdefault(k, {})
    if value is None:
        d.pop(keys[-1], None)
        if not d and len(keys) > 1:
            cfg.pop(keys[0], None)
    else:
        d[keys[-1]] = value
    os.makedirs(data(), exist_ok=True)
    p = data_file("config.json")
    tmp = p + ".sisi-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, p)
    pdata.commit(msg, ["config.json"])


def state_file(name):
    return os.path.join(state(), name)


def verifiers_dir():
    return os.environ.get("SISI_VERIFIERS") or os.path.join(REPO, "verifiers")


def done_dir():
    return os.environ.get("SISI_DONE") or os.path.join(REPO, "done")


def notes_dir():
    return os.environ.get("SISI_NOTES") or data_file("notes")


def legacy_notes_dir():
    """Where earlier versions wrote field notes: inside the product. Read only, by `sisi update`."""
    return os.path.join(REPO, "notes")
