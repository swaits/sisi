"""sisi: one rulebook and enforced definitions of done for every AI coding CLI."""
import os

def _version():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "unknown"

__version__ = _version()
