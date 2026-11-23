# Harnesses: what sisi does in each tool

`sisi install` wires every tool it finds (a tool whose configuration folder is missing is skipped and
reported). `sisi doctor` shows the same state as this file, per tool: whether the rulebook is loaded,
whether lessons print at session start, how the end of a turn is enforced, and anything you must do
yourself. `sisi install --dry-run` prints exactly what would be created, edited (with unified diffs) or
skipped, and changes nothing.

The uninstall guarantee, exactly: a file you have not edited since install is restored byte for byte, or
removed if sisi created it (a symlink is never deleted by uninstall; symlinked configs are written
through, and dangling symlinks are refused and left alone). A file you have edited since install keeps
your edits — uninstall removes only sisi's own entries, by textual span edits, leaving every other byte
(formatting, number and string spellings, duplicate keys) as it was; empty containers sisi itself added
(an emptied `hooks` object, a seeded `"version": 1`) are removed only when the backup proves sisi added
them. A generated plugin or extension you edited since install is left alone entirely. Any file sisi
cannot parse or edit with certainty (invalid or commented JSON, duplicate keys on a path being edited,
an unrecognised `read:` shape in Aider's config, a read-only or unreadable file) is skipped and
reported, never rewritten. Backups are content-addressed under `<personal>/install/backups/`
in an owner-only (0700) folder, each with its source file's permissions.

Wiring is always by reference: an import line, a symlink to the generated rulebook
(`~/.local/share/sisi/generated/core.md`), hook entries that run `sisi tick --tool NAME` /
`sisi prompt --tool NAME` / `sisi gate --tool NAME`, or a small generated plugin/extension (recognised by its exact
`sisi:generated …` first line, never by the words appearing anywhere else in the file). Every registered
shell hook command first checks the sisi launcher still exists, so deleting the sisi folder without
uninstalling makes hooks exit silently instead of erroring on every turn. The per-tool translation
between each tool's hook JSON and the gate lives in `sisi/hookio.py`; the adapters live in
`sisi/adapters.py`; the textual JSON editing lives in `sisi/hookjson.py`. Install also links any
skills shipped under `canon/skills` into `~/.agents/skills`; `sisi doctor` reports the linked
state. Hooks fail open: any error lets the agent finish. Where a tool's hook input has no transcript path, the gate falls back to its pre-attribution behaviour (tree-change based, with no per-session edit attribution). Shell commands are attributed by measurement, not by their text, wherever the tool has confirmed before/after tool events (`sisi watch` takes a stat-only tree snapshot before and after the command and attributes the paths that changed to the session; provably read-only commands skip the pair); tools without confirmed before/after tool events keep the command-text classifier described in [docs/design.md](design.md).

## Claude Code

Fully wired, as before: an `@import` line in `~/.claude/CLAUDE.md`, `SessionStart` → `sisi tick`,
`UserPromptSubmit` → `sisi prompt` (the matching recipe and lessons for the human's request, as
added context; silent when nothing strictly matches, and never able to block a turn),
`Stop`/`SubagentStop` → `sisi gate` (blocking), and `PreToolUse`/`PostToolUse` with matcher `Bash` →
`sisi watch` (before/after tree measurement) in `~/.claude/settings.json`. The gate also enforces
the question-dialog rule here: `AskUserQuestion` exists and the transcript is readable, so ending a
turn by asking in reply text without using the dialog is sent back once. Evidence: the hooks
reference documents `UserPromptSubmit` and its added-context output. Nothing for you to do.

## Codex CLI

Rulebook symlink at `~/.codex/AGENTS.md` (or `$CODEX_HOME/AGENTS.md`), plus hooks in
`~/.codex/hooks.json`: `SessionStart` → tick, `UserPromptSubmit` → prompt (the hooks page documents
the event and its added-context output; it needs the same one-time trust below),
`Stop`/`SubagentStop` → gate,
`PreToolUse`/`PostToolUse` (matcher `Bash`) → `sisi watch`, blocking with
`{"decision":"block","reason":...}`. One step is yours: Codex only runs hooks you have trusted, by exact
definition hash. After `sisi install`, open Codex, run `/hooks`, and trust the sisi hooks; repeat after
any change to the hook commands (for example after moving the sisi clone). `sisi doctor` cannot verify
trust from the files it knows, so it always reminds you. Verified: the session-start hook was observed
firing with its documented payload in a throwaway home (a full turn needs your Codex login, so the block
itself rests on the documented output shape and unit tests). Note Codex caps model-visible hook output
at roughly 2,500 tokens and spills the rest to a file, so a long gate report arrives as a preview plus a
file path.

## Gemini CLI

Rulebook symlink at `~/.gemini/GEMINI.md`, hooks merged into `~/.gemini/settings.json`: `SessionStart`
→ tick (lessons injected as `additionalContext`), `BeforeAgent` → prompt (the documented
before-turn event, carrying the request text), `AfterAgent` → gate, `BeforeTool`/`AfterTool` →
`sisi watch` (`{"decision":"deny","reason":...}`
rejects the response and forces a retry). Built from the hooks reference; Gemini is not installed on the
development machine, so this has not run live. Gemini has no subagent-stop event in its hook list, so
only the main turn is gated.

## GitHub Copilot CLI

Rulebook symlink at `~/.copilot/copilot-instructions.md` (or under `$COPILOT_HOME`), hooks in
`~/.copilot/hooks/sisi.json`: `sessionStart` → tick (`additionalContext`),
`userPromptSubmitted` → prompt (the documented before-prompt event), `agentStop`/`subagentStop` →
gate (`{"decision":"block","reason":...}` forces another turn), `preToolUse`/`postToolUse` → `sisi watch`. Verified end to end in a throwaway home:
a secret planted in session-start context was answered by the model, and a blocking `agentStop` visibly
forced a second turn. The cloud coding agent only runs hooks committed in the repository
(`.github/hooks/*.json`); sisi does not write repository files, so cloud enforcement needs such a file
copied from your `~/.copilot/hooks/sisi.json` if you want it.

## Qwen Code

Rulebook symlink at `~/.qwen/QWEN.md`, hooks merged into `~/.qwen/settings.json`: `SessionStart` → tick,
`Stop`/`SubagentStop` → gate (blocking, Claude-shaped output). The `~/.qwen` folder appears on Qwen's
first run, so run Qwen once before `sisi install`. Verified: the session-start hook was observed firing
with its documented payload (a full turn needs an auth type configured). Qwen's question tool is named
`ask_user_question` (the rulebook still names Claude Code's dialog; generalising that wording is future
work). The gate's question-dialog check is wired for Qwen the same way as for Claude Code, but
Qwen's transcript shape is unconfirmed, so the check reads nothing — and therefore sends nothing
back — until that shape is verified. No prompt hook is registered either: Qwen's prompt-submission
event name is not confirmed in its hooks reference excerpts or in the installed package's text, and
sisi does not guess event names into a config. Qwen's before/after tool event names are not confirmed, so sisi registers no watch hooks there:
shell edits in Qwen are still judged from the command text.

## Pi

Rulebook symlink at `~/.pi/agent/AGENTS.md` (or `$PI_CODING_AGENT_DIR/AGENTS.md`; skipped if you already
have your own file there) plus a generated extension at `~/.pi/agent/extensions/sisi.ts`. The extension
runs `sisi tick` on `session_start` and injects the lessons at `before_agent_start`, runs
`sisi prompt` there too with the request text that event carries (the installed extension docs
confirm the event and its message injection; a missing text field leaves it silent), and runs the gate on
`agent_before_settle`, forcing one continuation with the failure report when checks fail (capped by the
gate's own three send-backs). Verified: the extension loads in real Pi and tick runs; the blocking
continuation could not be exercised end to end without a model login in the throwaway home. Pi gets no
watch hooks (its extension has no confirmed before/after shell payload for this), so shell edits there are
still judged from the command text.

## Cursor

Hooks merged into `~/.cursor/hooks.json`: `sessionStart` → tick (lessons as `additional_context`),
`stop`/`subagentStop` → gate, `preToolUse`/`postToolUse` → `sisi watch`. No prompt hook: Cursor's
documented `beforeSubmitPrompt` event can allow or stop a submission, but no channel for injecting
added context is documented for it, so there is nothing for `sisi prompt` to print into. Cursor cannot veto a stop; instead a non-empty `followup_message` is
auto-submitted as the next user message, which is how the gate sends the agent back (Cursor caps this at
5 per script by default; sisi's own cap is 3). Only completed (not aborted/error) stops are gated.
There is no confirmed user-global instruction *file* for Cursor, so sisi wires no global rulebook there;
project-level `AGENTS.md` files still load as usual. Built from the hooks documentation — a live run
needed a Cursor login that the throwaway home did not have.

## OpenCode

Rulebook symlink at `~/.config/opencode/AGENTS.md` plus a generated plugin at
`~/.config/opencode/plugins/sisi.js`. The plugin runs `sisi tick` when a session is created and the gate
when the session goes idle, and then tries to continue the session with the failure report through the
client prompt API where one exists. Be clear about the limits: `session.idle` fires after the agent has
finished and cannot veto anything, and on OpenCode v2.3.2 no plugin event delivery or lesson injection
could be confirmed in headless runs (the plugin itself is loaded — verified — and the v1-style hooks and
v2 `setup()` registration are both attempted, all fail-open). Treat OpenCode enforcement as unproven
until it is observed on your version; `sisi doctor` says `unknown` on purpose. It also gets no
prompt hook: a per-message plugin callback exists, but the transform that would inject added
context is unconfirmed on the installed version. OpenCode gets no watch
hooks either, so shell edits there are still judged from the command text.

## Muse Code

Nothing is wired directly, and `sisi doctor` says why. There is no documented native global instruction
path (independent tooling ships `supportsGlobal:false` rather than guess one), so sisi invents no path.
Muse loads foreign personal context by default — `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` — so the
rulebook already reaches it whenever Claude Code or Codex is wired (unless you pass
`--no-foreign-personal-context`). Hooks are not wired: the installed binary's hook event list
(`SessionStart`, `PreToolUse`, …, `SubagentStop`, `SessionEnd`, `StopFailure`, …) contains no plain
end-of-turn `Stop`, and the global hook location/shape via plugins is unconfirmed. Muse's question tool
is `request_user_input`.

## Antigravity

No separate wiring. Antigravity shares `~/.gemini/GEMINI.md` with Gemini CLI, so the Gemini symlink also
serves it. Its hooks are not wired: whether the CLI fires hooks at all is disputed in the sources, and
the always-on size budget (a per-file cap around 24 KB) is unconfirmed, so the full rulebook may shrink
to a pointer there. `sisi doctor` lists it as unknown when its folders are present.

## Windsurf (Devin Desktop)

Global rules are size-capped (6,000 characters for the global file in the sources checked), so sisi
cannot link the whole rulebook in. Instead, when no global rules file exists, sisi writes a short
pointer at `~/.codeium/windsurf/memories/global_rules.md` telling Cascade to read the generated rulebook
and run the contract workflow itself. An existing user file there is left alone. Evidence: the file name
and cap are from Cascade's own documentation; the on-disk path is only secondary-sourced, whether
Cascade reliably follows such a pointer is unconfirmed, and no session-start or blocking hook is
confirmed, so there are no lessons at session start and no gate.

## Cline

Rulebook symlink into the global rules directory (`~/Documents/Cline/Rules/sisi.md`, or
`~/.cline/rules/sisi.md` when only that exists). Evidence: confirmed — Cline's own rules documentation
(linux path included) was read during implementation; that the extension follows the symlink was not
verified live (Cline is not installed here). Cline has hooks, but they must be enabled in its settings
and no contract is confirmed under which the task-end hook can send the agent back, so sisi wires no
gate. Cline's question tool is `ask_followup_question`.

## Kiro

Rulebook symlink at `~/.kiro/steering/AGENTS.md` (Kiro always includes `AGENTS.md` files in the global
steering folder; frontmatter-less steering files also default to always-included). Kiro hooks are
trigger-to-action automations with no confirmed way to veto the end of a turn, so there is no gate.

## Zed

Rulebook symlink at `~/.config/zed/AGENTS.md`. Zed's built-in agent has no hooks; external agents run
through Zed (ACP) bring their own tool's wiring with them.

## Goose

Rulebook symlink at `~/.config/goose/.goosehints` (the global hints file; project `AGENTS.md` files load
as usual). Evidence: not confirmed live — the path comes from Goose's published goosehints documentation
as surfaced in search results during implementation; the docs site itself could not be fetched then, and
Goose is not installed here, so neither the path nor symlink loading was verified live. Goose lifecycle
hooks ship in plugins, but on the documented contracts they cannot inject model-visible context or force
a continuation, so sisi wires no gate.

## Amp

Rulebook symlink at `~/.config/amp/AGENTS.md`. Evidence: the path is confirmed — Amp's own AGENTS.md
documentation (ampcode.com/docs) was read during implementation and names `$HOME/.config/amp/AGENTS.md`
explicitly; the original research notes had marked it unconfirmed pending that check. Loading was not
verified live (no signed-in Amp run in a throwaway home). No blocking end-of-turn hook is confirmed in
Amp's documentation, so there is no gate.

## Grok CLI

Rulebook symlink at `~/.grok/AGENTS.md` (or `$GROK_HOME/AGENTS.md`) — verified with `grok inspect`,
which lists it as a global instruction file under either home. Grok has hooks, but session-start hook output is reportedly discarded before reaching
the model and no blocking stop contract is confirmed, so sisi wires no hooks. (Grok also reads Claude
Code-compatible configuration; whether sisi's Claude hooks fire under Grok is not relied on.)

## Crush

Rulebook symlink at `~/.config/crush/CRUSH.md` (or `$XDG_CONFIG_HOME/crush/CRUSH.md`, honoured as
`crush dirs` confirms; one of Crush's default global context paths, confirmed from the binary's own
configuration schema). Crush hooks support only `PreToolUse`, which is not a turn gate, so
sisi wires no hooks. Revisit when its session/turn hook events ship.

## Aider

Aider auto-discovers no instruction file. When `~/.aider.conf.yml` already exists, sisi adds the
generated rulebook to its `read:` list (creating the file would change Aider's defaults, so sisi never
creates it — create it yourself, even empty, and re-run `sisi install`). Aider has no hooks at all, so
nothing enforces the rulebook there.

## T3 Code and Orca

Both are hosts, not agents: they run other harnesses (Claude Code, Codex, OpenCode, Cursor, Pi, Muse
Code and friends) as providers, and each provider loads its own global instructions and fires its own
hooks. There is nothing T3- or Orca-specific to wire; wire the providers and both are covered.
`sisi doctor` lists them as covered through their providers and names which providers are wired.

## Not wired

Roo Code was discontinued and gets no wiring; any remaining installs still read project
`AGENTS.md`. Agents beyond the list above that read a project `AGENTS.md` (Factory, Warp, Junie and
similar) are covered by the project file, with no per-tool wiring and no gate.
