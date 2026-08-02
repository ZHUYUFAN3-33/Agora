# -*- coding: utf-8 -*-
"""Shared bootstrap + reporting for the offline agentwake tests.

Every offline test used to repeat the same four-line preamble (dummy API key,
put agora_backend on sys.path, chdir into a throwaway temp dir, then import the
main module). That boilerplate now lives here so the test files only carry their
actual assertions.

Usage
-----
    from _harness import bootstrap, Checker

    aw = bootstrap("agentwake_test_")   # MUST run before touching aw
    ck = Checker(); check = ck.check    # keep the familiar check(...) call site
    ...
    ck.finish("ALL CHECKS PASSED")
"""
import os
import sys
import tempfile


def bootstrap(prefix):
    """Prepare an isolated offline environment and import ``agentwake_new``.

    Order matters: the dummy key, the sys.path entry, and the chdir into a fresh
    temp dir all have to happen *before* the module is imported, so all three are
    done here and the imported module is returned.

    Args:
        prefix: temp-dir name prefix, e.g. ``"agentwake_smoke_"`` — handy when
            eyeballing leftover scratch dirs.

    Returns:
        The imported ``agentwake_new`` module.
    """
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
    if backend not in sys.path:
        sys.path.insert(0, backend)
    os.chdir(tempfile.mkdtemp(prefix=prefix))
    import agentwake_new as aw  # noqa: E402  (import is deliberately deferred)
    return aw


class Checker:
    """Collects PASS/FAIL lines and exits non-zero if anything failed.

    Prints ``[PASS] name`` / ``[FAIL] name  -- detail`` per check (detail only on
    failure, matching the original hand-rolled ``check()`` helpers).
    """

    def __init__(self):
        self.failures = []

    def check(self, name, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {name}"
              + (f"  -- {detail}" if (detail and not cond) else ""))
        if not cond:
            self.failures.append(name)

    def finish(self, ok_msg="ALL CHECKS PASSED"):
        """Print the summary line and exit(1) if any check failed."""
        print()
        if self.failures:
            print(f"{len(self.failures)} FAILURE(S): {self.failures}")
            sys.exit(1)
        print(ok_msg)
