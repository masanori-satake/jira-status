#!/usr/bin/env python3
"""Keep the in-repository Kiro mirror identical to the canonical skill.

This repository is laid out so that a plain checkout works immediately:
  .agents/skills/jira-status   canonical (Copilot reads .agents/skills)
  .kiro/skills/jira-status     mirror   (Kiro reads .kiro/skills)

Edit only the canonical. Run this tool before committing:

  python tools/sync_mirror.py           copy canonical -> mirror
  python tools/sync_mirror.py --check   verify parity (file set + SHA-256),
                                        exit 1 on any difference

Standard library only.
"""
import argparse
import hashlib
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANON = os.path.join(REPO, ".agents", "skills", "jira-status")
MIRROR = os.path.join(REPO, ".kiro", "skills", "jira-status")
EXCLUDE_DIRS = {"__pycache__", ".git"}
EXCLUDE_SUFFIXES = {".pyc"}


def signature(root):
    sig = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if any(name.endswith(s) for s in EXCLUDE_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            h = hashlib.sha256()
            with open(full, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            sig[rel] = h.hexdigest()
    return sig


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync or verify the .kiro mirror of the canonical skill")
    parser.add_argument("--check", action="store_true", help="Verify parity only; exit 1 on drift")
    args = parser.parse_args(argv)

    if not os.path.isfile(os.path.join(CANON, "SKILL.md")):
        print(f"Canonical skill not found: {CANON}", file=sys.stderr)
        return 3

    if args.check:
        if not os.path.isdir(MIRROR):
            print(f"Mirror missing: {MIRROR}")
            return 1
        a, b = signature(CANON), signature(MIRROR)
        if a == b:
            print(f"OK: mirror is byte-identical to canonical ({len(a)} files)")
            return 0
        differ = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        missing = sorted(set(a) - set(b))
        extra = sorted(set(b) - set(a))
        if differ:
            print("differ: " + ", ".join(differ))
        if missing:
            print("missing in mirror: " + ", ".join(missing))
        if extra:
            print("extra in mirror: " + ", ".join(extra))
        print("DRIFT: run `python tools/sync_mirror.py` to repair")
        return 1

    if os.path.exists(MIRROR):
        shutil.rmtree(MIRROR)
    shutil.copytree(CANON, MIRROR, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    a, b = signature(CANON), signature(MIRROR)
    assert a == b, "mirror does not match canonical after sync"
    print(f"Synced mirror ({len(a)} files), parity verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
