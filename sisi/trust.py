"""Trusted project roots. A contract runs shell commands, so only contracts in trusted roots are executed."""
import json, os

from . import paths


def _file():
    return paths.personal("trusted.json")


def norm(p):
    return os.path.realpath(p)


def load():
    try:
        with open(_file(), encoding="utf-8") as f:
            d = json.load(f)
        return [x for x in d if isinstance(x, str)] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    os.makedirs(os.path.dirname(_file()), exist_ok=True)
    tmp = _file() + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(set(items)), f, indent=1)
    os.replace(tmp, _file())


def is_trusted(project):
    return norm(project) in load()


def add(project):
    _save(load() + [norm(project)])


def remove(project):
    _save([x for x in load() if x != norm(project)])


def hint(project):
    return "the contract in %s is untrusted (its commands have not been approved on this machine). " \
           "Read .sisi/contract.json, then run `sisi contract trust` in that project to allow it." % project
