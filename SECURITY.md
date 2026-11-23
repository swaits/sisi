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
