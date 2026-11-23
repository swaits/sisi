# The specification

`SPEC.md` at the top of this repository is the standard sisi is judged by: the objective, the
operating model and the requirements. Everything else in the project is a means to it.

| File | What it is |
|---|---|
| `engineering_organization_spec.docx` | The owner's original document, byte for byte. |
| `../../SPEC.md` | The same text as Markdown, so people and agents can read and cite it. |
| `SHA256SUMS` | Checksums of both. `sha256sum -c docs/spec/SHA256SUMS` from the repository root. |

`SPEC.md` was produced from the original with `pandoc -f docx -t gfm --wrap=none`, with the
title and subtitle (which pandoc treats as metadata) put back at the top. The words were then
compared one by one against the text inside the original: the only differences are the list
numbers that Word generates on display and does not store as text.

## Changing it

The specification says (14.3) that the objective, the constraints and the authority model are
versioned and protected from being weakened by an agent. So:

- Only the owner changes these files. An agent may propose a change; it does not make one.
- A change replaces both files and `SHA256SUMS` in one commit that says the owner approved it.
- The test suite fails when either file no longer matches `SHA256SUMS`.
