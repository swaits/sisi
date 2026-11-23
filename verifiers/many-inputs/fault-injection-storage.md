---
id: fault-injection-storage
title: Fault injection for storage (power loss, disk full, short writes)
answers: If the machine dies or the disk fills in the middle of a write, do the data reopen correctly with nothing lost that was acknowledged?
rung: 2
section: many-inputs
languages: any
kinds: state-machine, general
cost: medium
detect:
ran_here: yes
verified: ran
---

## Use when

- Code writes its own files (journal, snapshot, backup) and claims to be crash-safe or atomic.

## Do not use when

- A database makes the guarantee and you only use its API: test your use of transactions instead.
- You need real kernel or hardware faults (reordered writes, lost fsync); this simulates file contents only.

## Set up

Make the last write observable: record the file bytes before and after it. Then
simulate each fault by building the damaged file yourself and reopening it:

- power loss: for every cut `k` in `1..len(last_write)`, the file is `before + last[:k]`;
- disk full or short write: a write function that raises `OSError` after N bytes.

## Minimal example (Python; a checksummed append-only log)

    import os, tempfile, zlib

    class Log:
        def __init__(self, path):
            self.path, self.items = path, []
            if os.path.exists(path):
                raw = open(path, "rb").read()
                good = 0
                for line in raw.splitlines(keepends=True):
                    body, _, crc = line.rstrip(b"\n").rpartition(b" ")
                    if not line.endswith(b"\n") or not crc.isdigit() or zlib.crc32(body) != int(crc):
                        break                              # torn tail: drop it
                    self.items.append(body.decode()); good += len(line)
                if good < len(raw):
                    open(path, "r+b").truncate(good)       # heal
        def append(self, text):
            line = text.encode() + b" " + str(zlib.crc32(text.encode())).encode() + b"\n"
            with open(self.path, "ab") as f:
                f.write(line); f.flush(); os.fsync(f.fileno())
            self.items.append(text)

    def test_power_loss_at_every_byte_of_the_last_append():
        p = os.path.join(tempfile.mkdtemp(), "log")
        log = Log(p); log.append("one"); log.append("two")
        before = open(p, "rb").read()
        log.append("three")
        last = open(p, "rb").read()[len(before):]
        for k in range(1, len(last)):                      # every cut short of the whole line
            open(p, "wb").write(before + last[:k])
            assert Log(p).items == ["one", "two"], f"cut at {k}"
            assert open(p, "rb").read() == before, f"not healed at {k}"
        open(p, "wb").write(before + last)
        assert Log(p).items == ["one", "two", "three"]

## Run

    python3 -m pytest -q test_faults.py

Passing looks like: `1 passed`, exit 0. Failure names the byte cut (`cut at 7`).
One reference project's store also checks that reports after reopening equal those from before.

## As a contract check

    {"id": "torn-write-recovery", "claim": "a power cut at any byte of the last append reopens to the state before it", "kind": "state-machine", "rung": 2, "cmd": "python3 -m pytest -q test_faults.py", "expect": {"exit": 0, "stdout_contains": "passed"}, "tier": "deep", "timeout_s": 300}

## What a pass does not prove

- It covers truncation of the last write only. Torn writes that leave garbage in the middle, reordered writes, a lost `fsync` and media errors need other tests or a real crash rig.
- Also check an acknowledged write is never lost, not only that the file opens.
- Check the check: remove the CRC check or the truncate and see it fail.
