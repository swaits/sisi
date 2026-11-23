---
id: tool-description-lint
title: Linting tool descriptions and help text for misleading instructions
answers: Do this tool's descriptions and help text tell an agent anything false, missing or contradictory?
rung: 3
section: real-world
languages: any
kinds: general
cost: low
detect: python3 --version
ran_here: yes
verified: ran
---

## Use when
- You write or change tool descriptions for an MCP server, `--help` text, error messages or prompts that an agent reads and acts on.
- You rename or remove a tool and need every mention of it found.

## Do not use when
- You want to judge whether the text is persuasive or clear to a model. A lint finds mechanical errors only; use a rubric review or `agent-surface-evals`.

## Set up
Dump the tool list as JSON (for MCP, the result of `tools/list`; for a CLI, the output of each `--help`). Write the rules as a small script and keep it in the repo. Useful rules: every tool named in a description exists; a tool marked read-only does not say it creates, saves or deletes; every required parameter has a description; no description is empty or over a stated length; examples in descriptions parse against the input schema.

## Minimal example
`tests/lint_tools.py` (ran here against a two-tool list)
```python
import json, re, sys
tools = json.load(open(sys.argv[1]))["tools"]
names = {t["name"] for t in tools}
bad = []
for t in tools:
    d = t.get("description", "")
    for ref in re.findall(r"\b[a-z_]+\.[a-z_]+\b", d):
        if ref not in names and ref.split(".")[0] in {n.split(".")[0] for n in names}:
            bad.append(f"{t['name']}: description names unknown tool {ref}")
    if t.get("annotations", {}).get("readOnlyHint") and re.search(r"\b(creates?|deletes?|saves?|writes?|updates?)\b", d, re.I):
        bad.append(f"{t['name']}: readOnlyHint tool description talks about writing")
    for p in t["inputSchema"].get("required", []):
        if not t["inputSchema"]["properties"].get(p, {}).get("description"):
            bad.append(f"{t['name']}: required parameter {p} has no description")
print("\n".join(bad) or "tool text ok"); sys.exit(1 if bad else 0)
```

## Run
`python3 tests/lint_tools.py tools.json`

Passing looks like: `tool text ok` and exit 0. Failure lists each problem, one per line, and exits 1, for example `books.show: description names unknown tool books.post_entry`.

## As a contract check
```json
{"id": "tool-text-lint", "claim": "Tool descriptions name only existing tools and match their annotations", "kind": "general", "rung": 3,
 "cmd": "python3 tests/lint_tools.py tests/tools.json", "expect": {"exit": 0, "stdout_contains": "tool text ok"}, "timeout_s": 60}
```

## What a pass does not prove
- Only the rules you wrote. A description can be mechanically clean and still send an agent the wrong way.
- The regex for write words has false positives and misses synonyms; treat each hit as a question to a human.
- A stale `tools.json` passes against an old tool list. Regenerate it from the running server in the same check.
- Check the check: add a reference to a tool that does not exist and confirm failure (done here).
