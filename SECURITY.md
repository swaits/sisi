# Security

## What sisi runs, and when

sisi's end-of-turn hook and `sisi verify` run shell commands. The commands come from the `checks` and
`invariants` of the project's `.sisi/contract.json`. A contract in a repository you cloned is therefore code
written by someone else, and it is treated as such.

- A project's contract runs only after the project is trusted on this machine. `sisi contract init` trusts the
  project it creates; anything else needs an explicit `sisi contract trust`, which you should run after reading
  `.sisi/contract.json`.
- In an untrusted project, `sisi verify` refuses to run (exit 3) and the end-of-turn gate lets the turn end
  without running anything.
- The list of trusted projects is `trusted.json` in your personal data folder. `sisi contract untrust` removes
  a project.
- Every check has a time limit. After a few send-backs in a row the gate lets the agent through and marks the
  result unverified, so a broken check cannot hold a session forever.

## What learning can change, and who decides

A learning cycle can install checks, rules and risk patterns that shape later sessions. What it may do alone is
limited, and the rest waits for you:

- A mechanism a cycle installs carries its learning's id and the scope that learning has earned (its own project,
  unless it was seen in two units in two projects, or you stated it at user scope). Nothing the cycle file claims
  about scope or project is trusted: a request for more only makes the change wait.
- These always wait for you: more scope than earned, a shell command that was not seen to fail and then pass in its
  own trusted project, a risk pattern that lowers a profile, any replaced or disabled rule, and rule text or a
  library entry from a learning confined to one project. Protected rules (`canon/protected.json`) cannot be changed
  by a cycle or by `sisi overlay` at all, and if that file cannot be read, no rule can be changed.
- A cycle file is untrusted input, and `sisi cycle check` never executes anything from it. `sisi cycle apply`
  replays a command check only in a repository on the trust list, only between two commits taken from the learning's
  own record (its unit's start and closing commits, or the ones stored with the finding; never from the file), only
  if the command names a path that differs between the two trees, and only inside an exported copy of each
  commit's tree: no `.git` directory (the command cannot read history), an environment of `PATH`, `HOME` (an empty
  directory) and `LANG` only (none of the caller's credentials or tokens), a time limit, and the copy deleted
  afterwards. A learning with no recorded commits cannot be validated: its command check waits for you as
  `unvalidated`. What this does not do: the replayed command still runs as you, with your file permissions, and
  sisi does not sandbox it; which is why a command that was not seen to fail and then pass waits for you.

`sisi approve` lists every waiting change in full (the exact command, the pattern and profile, the rule text as a
diff). Deciding one takes two layers:

- The before-tool hook refuses any shell command an agent runs whose text invokes `sisi approve` with an argument,
  however it is wrapped (`script`, `sh -c`, `env`, `expect`, a path to the launcher, `python -m sisi`, quotes and
  backslashes inside the words), for main threads and workers alike, and tells the agent that approval is yours
  alone and to show you the command to run yourself. The plain listing (`sisi approve` with no arguments) is
  allowed. The hook fails open on an error, so it is a guard, not a wall: a command built from pieces, from a
  variable or from an encoded string is not recognised by its text.
- `sisi approve ID --yes|--no` itself prints the whole action and a short random word on the controlling terminal
  device (`/dev/tty`, never standard input) and decides only when that word is typed back there. A process with no
  controlling terminal is refused; so is one whose terminal returns the wrong word or nothing. This is the typed
  word, and it is what `script -qec "sisi approve ID --yes" /dev/null </dev/null` runs into: the pseudo-terminal it
  allocates has nobody typing at it.

Every refused attempt, by the hook or by the command, is written to `approvals.jsonl` with the session id; every
decision is written there with the time, the session if known, and whether a terminal was used. Your config may set
`learning.agent_relayed_approval` (off by default): then a decision from a process with no terminal is accepted and
the record says `relayed by an agent`. What this does not stop: an agent that can read and write a terminal it
allocated itself (`expect`, a pty library) sees the word and can type it, and the hook's text check does not see
every way of writing a command. Neither layer proves who is at the keyboard, and anyone who can write your personal
data folder can edit the config, the pending list or the ledger directly. The protection is that an agent is told to
show you the change and give you the command to type yourself, that the hook and the typed word make doing it for you
hard and leave a record, and that the cycle cannot apply anything consequential on its own; it is not a defence
against code that already runs with your permissions.

The same limit applies to who recorded something. A learning recorded from a subagent is held as a candidate until
the parent adopts it by id. "Recorded by a subagent" is read from what the hooks recorded in the session record, not
from the environment; a tool without those hooks, or a process that picks another session id, is not detected. A
row added or edited by hand in `learnings.jsonl` is never delivered: only rows that sisi's own commands wrote, as
they wrote them, are in the ledger. `sisi learn` records whether your words appear in a message you typed in the
session transcript; when they do not, or there is no transcript, the statement is marked `relayed by an agent`
and `sisi oracle` shows that. `sisi learn --withdraw ID --reason ...` takes a statement recorded by mistake out of
delivery for good.

## What sisi does not protect against

- A trusted project's contract runs with your permissions. Trust only projects you trust.
- sisi does not sandbox the commands it runs.
- Instructions that sisi adds to your tools (the rulebook) are text the tools obey. Anyone who can write to your
  personal data folder can change what your agents are told. Keep that folder private (it is created in your home
  directory and is a local git repository that sisi never pushes).
- sisi does not read network resources and has no server. `sisi update` runs `git fetch` and a fast-forward merge
  in the clone and nothing else over the network.

## Reporting a problem

Please report security problems privately, using a private security advisory on the GitHub repository
(github.com/swaits/sisi, "Security" tab, "Report a vulnerability"). Do not open a public issue for something
that could be exploited. Include the version (`sisi --version`), what you did, and what happened.

## What these mechanisms do and do not guarantee

The trust list guarantees only that an untrusted project's contract does not run; it does not
make a trusted contract safe. Protected rules guarantee that a cycle or overlay cannot change
them; they do not stop someone who can write the product folder. Owner approval guarantees
that a consequential change waits and that a decision needs the word typed at a controlling terminal (and is
refused for an agent's shell command by the before-tool hook) unless relayed approval is allowed in config; it
does not stop a program that allocates its own terminal and reads it, and does not prove who was at the keyboard. The
delivery ledger guarantees that only rows sisi's own commands wrote, as written, are
delivered; it does not prove the content of a row is true.
