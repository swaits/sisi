"""Compatibility shim: the scoreboard folded into sisi.scorecard (SPEC 13).

`sisi status` is the one report now; the `sisi scoreboard` command is gone. These
names stay only for internal callers not yet migrated (learn_cli's checks command).
"""
from .scorecard import MANY_RUNS, check_stats, iso_week, session_trends


def scoreboard(con):
    return session_trends(con)
