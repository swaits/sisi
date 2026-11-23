"""Compatibility shim: escape candidates folded into sisi.scorecard, where they feed the
intent and correctness dimensions. These names stay for learn_cli's escapes command."""
from .scorecard import WEEK_S, attribute, escape_candidates, passed_runs

find = escape_candidates
