#!/usr/bin/env python3
"""Install this skill from one canonical copy into Copilot and Kiro locations.

Layout this tool maintains (per workspace):

  <workspace>/.agents/skills/jira-status   <- canonical (a git clone of the skill repo)
  <workspace>/.kiro/skills/jira-status     <- link to canonical (Kiro reads here)
  Copilot reads the canonical .agents/skills directly, so no .github copy is
  needed. Pass --with-github to also place .github/skills/jira-status.

Modes:
  link (default)  Create a directory link (Windows junction / POSIX symlink).
                  One physical copy: edits to the canonical are visible to both
                  tools immediately, and drift is impossible.
  copy            Copy the files. Use when links are not possible (for example
                  when the target tree must be committed as real files).
                  Re-run this tool after every canonical update, and verify
                  with --check.

Usage:
  python scripts/install.py --workspace <root> [--source <canonical-dir>]
                            [--mode link|copy] [--with-github] [--force]
  python scripts/install.py --workspace <root> --check

--check compares every installed location against the canonical by file set
and SHA-256, and exits 1 on any drift. Standard library only.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys

SKILL_NAME = "jira-status"
EXCLUDE_DIRS = {"__pycache__", ".git"}
EXCLUDE_SUFFIXES = {".pyc"}


def iter_files(root):
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for name in filenames:
            if any(name.endswith(s) for s in EXCLUDE_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            result[rel] = full
    return result


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_signature(root):
    return {rel: sha256(p) for rel, p in iter_files(root).items()}


def is_link(path):
    return os.path.islink(path)


def link_target(path):
    return os.path.realpath(path)


def make_link(source, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.name == "nt":
        # cmd /c re-parses its command line: quotes can break out of an
        # argument, and &, |, <, >, ^ and % are special to cmd even in
        # an unquoted argument (subprocess only adds quotes around
        # arguments that contain spaces). Refuse such paths outright.
        cmd_specials = set('"&|<>^%')
        if cmd_specials & set(dest) or cmd_specials & set(source):
            raise RuntimeError("paths containing cmd-special characters are not supported for mklink")
        # Directory junction: no administrator rights needed.
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", dest, source],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"mklink failed: {proc.stdout} {proc.stderr}")
    else:
        os.symlink(source, dest, target_is_directory=True)


def remove_path(path):
    if is_link(path) or os.path.isfile(path):
        os.unlink(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def place(source, dest, mode, force):
    """Place dest as a link to (or copy of) source. Returns a status string."""
    source = os.path.abspath(source)
    if os.path.lexists(dest):
        if is_link(dest):
            if link_target(dest) == source:
                return "already linked"
            if not force:
                return f"REFUSED: {dest} is a link to {link_target(dest)}, not the canonical"
            remove_path(dest)
        elif os.path.isdir(dest):
            sig_src = tree_signature(source)
            sig_dst = tree_signature(dest)
            if sig_src == sig_dst:
                if mode == "link":
                    if not force:
                        return "identical copy exists (pass --force to replace it with a link)"
                    remove_path(dest)
                else:
                    return "already copied (identical)"
            else:
                if not force:
                    return f"REFUSED: {dest} exists and differs from the canonical (pass --force to overwrite)"
                remove_path(dest)
        else:
            return f"REFUSED: {dest} exists and is not a directory"
    if mode == "link":
        make_link(source, dest)
        return "linked"
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("__pycache__", ".git", "*.pyc"))
    return "copied"


def check_one(source, dest):
    """Return (ok, message) comparing dest against canonical source."""
    if not os.path.lexists(dest):
        return False, "missing"
    if is_link(dest):
        if link_target(dest) == os.path.abspath(source):
            return True, "link to canonical (identical by construction)"
        return False, f"link points elsewhere: {link_target(dest)}"
    sig_src = tree_signature(source)
    sig_dst = tree_signature(dest)
    if sig_src == sig_dst:
        return True, "copy, byte-identical to canonical"
    only_src = sorted(set(sig_src) - set(sig_dst))
    only_dst = sorted(set(sig_dst) - set(sig_src))
    differ = sorted(k for k in set(sig_src) & set(sig_dst) if sig_src[k] != sig_dst[k])
    parts = []
    if differ:
        parts.append("differ: " + ", ".join(differ[:5]))
    if only_src:
        parts.append("missing: " + ", ".join(only_src[:5]))
    if only_dst:
        parts.append("extra: " + ", ".join(only_dst[:5]))
    return False, "DRIFT (" + "; ".join(parts) + ")"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install the jira-status skill from one canonical copy")
    parser.add_argument("--workspace", default=".", help="Workspace root (default: current directory)")
    parser.add_argument(
        "--source",
        default=None,
        help="Canonical skill directory (default: <workspace>/.agents/skills/jira-status if it exists, else the directory containing this script's skill)",
    )
    parser.add_argument("--mode", choices=["link", "copy"], default="link")
    parser.add_argument(
        "--with-github",
        action="store_true",
        help="Also place .github/skills/jira-status (not needed for Copilot, which reads .agents/skills directly)",
    )
    parser.add_argument("--force", action="store_true", help="Replace conflicting existing locations")
    parser.add_argument("--check", action="store_true", help="Verify parity only; exit 1 on drift")
    args = parser.parse_args(argv)

    workspace = os.path.abspath(args.workspace)
    default_canonical = os.path.join(workspace, ".agents", "skills", SKILL_NAME)
    script_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = args.source or (default_canonical if os.path.isdir(default_canonical) else script_skill_dir)
    source = os.path.abspath(source)
    if not os.path.isfile(os.path.join(source, "SKILL.md")):
        print(f"Canonical skill not found at {source} (no SKILL.md)", file=sys.stderr)
        return 3

    targets = {"kiro": os.path.join(workspace, ".kiro", "skills", SKILL_NAME)}
    if os.path.abspath(source) != default_canonical:
        targets["agents (canonical home)"] = default_canonical
    if args.with_github:
        targets["github"] = os.path.join(workspace, ".github", "skills", SKILL_NAME)

    print(f"Canonical: {source}")
    ok = True
    for label, dest in targets.items():
        if os.path.abspath(dest) == source:
            continue
        if args.check:
            good, msg = check_one(source, dest)
            ok = ok and good
            print(f"[{label}] {dest}: {'OK' if good else 'NG'} - {msg}")
        else:
            status = place(source, dest, args.mode, args.force)
            print(f"[{label}] {dest}: {status}")
            if status.startswith("REFUSED"):
                ok = False
    if args.check:
        return 0 if ok else 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
