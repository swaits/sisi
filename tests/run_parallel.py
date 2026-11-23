"""Run every test module in its own process, several at a time.

The suite is the fast check in this project's contract, so it runs at the end
of every agent turn and must finish well inside 60 seconds even on a busy
machine. Each module already isolates itself (temporary home, state and data
folders), so modules are safe to run side by side.

Usage: python3 tests/run_parallel.py [-j N]
Exit status is 0 only if every module passes. Output of a failing module is
printed in full; passing modules print one line.
"""
import concurrent.futures
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def run(module):
    start = time.time()
    proc = subprocess.run(
        [sys.executable, "-W", "ignore::ResourceWarning", "-m", "unittest", module],
        cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    return module, proc.returncode, proc.stdout, time.time() - start


def main(argv):
    jobs = os.cpu_count() or 4
    if "-j" in argv:
        jobs = int(argv[argv.index("-j") + 1])
    modules = sorted(f[:-3] for f in os.listdir(HERE)
                     if f.startswith("test_") and f.endswith(".py"))
    if not modules:
        print("no test modules found")
        return 1
    failed = []
    total = 0
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for module, code, out, secs in pool.map(run, modules):
            ran = [l for l in out.splitlines() if l.startswith("Ran ")]
            count = int(ran[-1].split()[1]) if ran else 0
            total += count
            if code != 0 or not ran:
                failed.append(module)
                print("FAILED %s (%.1fs)\n%s" % (module, secs, out))
            else:
                print("ok     %-28s %4d tests %6.1fs" % (module, count, secs))
    print("\nRan %d tests in %d modules in %.1fs" % (total, len(modules), time.time() - start))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
