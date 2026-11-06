"""Command-line entry point: qacclaims validate | build | execute."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .build import build_all, check_fresh
from .execute import execute
from .loader import find_root
from .validate import validate_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qacclaims", description="QAC claims registry tooling")
    parser.add_argument("--version", action="version", version=f"qacclaims {__version__}")
    parser.add_argument("--root", type=Path, default=None, help="repository root (auto-detected)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="schema + cross-file checks for every claim")
    p_validate.add_argument("--online", action="store_true", help="also check that DOIs resolve")

    p_build = sub.add_parser("build", help="write dist/ (merged public records)")
    p_build.add_argument("--check", action="store_true", help="fail if committed dist/ is out of date")
    p_build.add_argument("--out", type=Path, default=None, help="output directory (default: <root>/dist)")

    p_exec = sub.add_parser("execute", help="rerun a reproduction (notebook or script) in its pinned environment")
    p_exec.add_argument("repro_dir", type=Path)
    p_exec.add_argument("--python", default=None, help="interpreter of the pinned environment (default: current)")
    p_exec.add_argument("--write", action="store_true", help="commit the results, run.json, the executed notebook if any (and the lockfile if missing)")
    p_exec.add_argument("--refresh-lock", action="store_true", help="with --write: regenerate requirements.lock.txt from the environment")
    p_exec.add_argument("--operator", default=None, help="name recorded in run.json (default: git user.name)")
    p_exec.add_argument("--github", default=None)
    p_exec.add_argument("--automation", default=None, help="e.g. 'github-actions' when run unattended")
    p_exec.add_argument("--timeout", type=int, default=3600)

    args = parser.parse_args(argv)
    root = (args.root or find_root()).resolve()

    if args.command == "validate":
        problems = validate_all(root, online=args.online)
        for problem in problems:
            print(problem)
        errors = [p for p in problems if p.level == "error"]
        print(f"{len(errors)} error(s), {len(problems) - len(errors)} warning(s)")
        return 1 if errors else 0

    if args.command == "build":
        dist = args.out or (root / "dist")
        blocking = [p for p in validate_all(root) if p.level == "error"]
        if blocking:
            for problem in blocking:
                print(problem)
            print(f"refusing to build: {len(blocking)} validation error(s)")
            return 1
        if args.check:
            stale = check_fresh(root, root / "dist")
            for line in stale:
                print(line)
            print("dist/ is up to date" if not stale else f"{len(stale)} stale file(s)")
            return 1 if stale else 0
        written = build_all(root, dist)
        for rel, digest in written.items():
            print(f"{digest[:12]}  {dist.relative_to(root) if dist.is_relative_to(root) else dist}/{rel}")
        return 0

    if args.command == "execute":
        diffs, duration = execute(
            root, args.repro_dir, python=args.python, write=args.write, operator=args.operator,
            github=args.github, automation=args.automation, refresh_lock=args.refresh_lock, timeout=args.timeout,
        )
        print(f"executed in {duration}s")
        for line in diffs:
            print(f"DRIFT {line}")
        if diffs:
            print(f"{len(diffs)} difference(s) from committed results.json" + (" (written)" if args.write else ""))
        else:
            print("results reproduce the committed results.json exactly" if not args.write else "results written")
        return 0 if (args.write or not diffs) else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
