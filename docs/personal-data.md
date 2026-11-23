# Product and personal data

sisi lives in three places. An update replaces the first and never touches the second.

| Place | Where | What | Written at run time |
|---|---|---|---|
| Product | the clone (`paths.REPO`) | code, `canon/core.md` (base rulebook), `verifiers/`, `done/`, `config.default.json`, `VERSION`, docs | never (a test enforces it; bytecode goes to scratch) |
| Personal data | `$SISI_DATA`, else `$XDG_DATA_HOME/sisi`, else `~/.local/share/sisi` | what sisi learned for this person; its own local git repository | yes, committed |
| Scratch | `$SISI_STATE`, else `~/.local/state/sisi` | `harvest.db`, locks, logs, session records, results, bytecode | yes, rebuildable |

Under `SISI_HOME` (tests) the personal folder is `$SISI_HOME/.local/share/sisi` unless `SISI_DATA` is set.

## Personal data layout

    VERSION              format version of this folder, a single integer (an update migrates older folders after taking a backup).
                         Not the product's release number: that is the VERSION file in the clone, shown by `sisi --version`
    oracle.md            what the person wants
    overlay/             learned changes to the product (below); overlay/enforced.json holds enforced lessons
    notes/<id>.md        field notes per verifier or recipe id (notes/draft-<id>.md: a recipe that does not exist yet)
    cycles/              one JSON record per learning cycle, including the bytes revert restores
    config.json          settings (over config.default.json)
    trusted.json         projects whose contracts may run commands
    lessons.jsonl        sorted dump of the lessons database, committed whenever lessons change
    learn-quarantine.jsonl, notes.jsonl, proposals.jsonl
    retest.jsonl         replaced items whose base changed in an update (id, old base hash, new base hash)
    retro.db             lessons database (sqlite; not in git; lessons.jsonl is its committed form)
    generated/core.md    the effective rulebook (not in git; rebuilt by `sisi build-canon`)
    install/             manifest and original copies of the files `sisi install` edited (not in git)
    backups/             copies taken before a migration or an update (not in git)

Git is private bookkeeping: author `sisi`, no hooks, no global git config needed, never pushed.

## Overlay

Ids: rules are `## 1. Title {#rule-id}` in `canon/core.md`; verifiers and recipes use their file stem.

    overlay/rules/<id>.md              `## Title` + body. A base id replaces that rule; a new id adds one
    overlay/rules/disabled.txt         ids switched off, one per line
    overlay/rules/order.txt            order of added rules (they follow the base rules)
    overlay/verifiers/<section>/<id>.md   a verifier in the library format: replaces the product's, or adds
    overlay/verifiers/disabled.txt
    overlay/done/<id>.md               a recipe: replaces or adds
    overlay/done/disabled.txt
    overlay/bases.json                 per replacement, the hash of the base item it was made against

Commands: `sisi overlay list | diff | add-rule | replace-rule | disable-rule | enable-rule` (and the same for
`verifier` and `recipe`), `sisi overlay revert COMMIT`. Each change is one commit and rebuilds the rulebook.
The generated rulebook may not exceed 120 lines: a change that would pass it is refused, so a rule is added
by shortening or replacing another. `sisi canon cost` prints the always-loaded size.

On `sisi update` the overlay is applied to the new product. A replacement whose base item changed keeps the
person's version and is queued in `retest.jsonl` for the learning loop.

## Moving data

`sisi migrate` (also run by install and update) moves an older layout in, after a timestamped copy under
`backups/`. `sisi export [PATH]` / `sisi import PATH` carry personal data, results and session records as one
tar.gz.
