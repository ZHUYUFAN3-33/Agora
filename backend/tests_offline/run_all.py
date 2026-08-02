# -*- coding: utf-8 -*-
"""Run every offline test in tests_offline/ and report one aggregated result.

Each ``test_*.py`` runs in its own subprocess (they mutate global process state —
cwd, env, sys.argv, builtins.input — so they must not share an interpreter) and
prints its own PASS/FAIL lines. This wrapper collects the exit codes and exits
non-zero if any test failed, so CI (or you) only need a single command:

    python tests_offline/run_all.py

No API key or network needed; every LLM call is stubbed inside the tests.
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    tests = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    if not tests:
        print("no test_*.py found in", HERE)
        return 1

    results = []
    for path in tests:
        name = os.path.basename(path)
        print(f"\n===== {name} " + "=" * (60 - len(name)))
        proc = subprocess.run([sys.executable, path])
        results.append((name, proc.returncode))

    print("\n" + "=" * 66)
    failed = [name for name, code in results if code != 0]
    for name, code in results:
        print(f"  [{'PASS' if code == 0 else 'FAIL'}] {name}")
    if failed:
        print(f"\n{len(failed)} of {len(results)} test file(s) FAILED: {failed}")
        return 1
    print(f"\nall {len(results)} test file(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
