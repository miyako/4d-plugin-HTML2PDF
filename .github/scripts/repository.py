"""Verify selected Git bytes without trusting index stat caches or hidden flags."""

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess

WINDOWS = os.name == "nt"


def run(*args, input=None, env=None):
    return subprocess.run(args, input=input, env=env, text=True, check=True,
                          stdout=subprocess.PIPE).stdout.rstrip("\n")


def selected_sha(sha):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected immutable selected github.sha")
    if run("git", "rev-parse", "HEAD") != sha:
        raise ValueError("Checkout HEAD does not match selected SHA")


def entries(output, *, index=False):
    result = {}
    for record in filter(None, output.split("\0")):
        header, path = record.split("\t", 1)
        mode, kind, oid = header.split()
        if index:
            mode, oid, stage = header.split()
            if stage != "0":
                raise ValueError("Unmerged index")
        elif kind != "blob":
            raise ValueError("Unsupported non-blob checkout entry")
        if path in result:
            raise ValueError("Duplicate checkout entry")
        result[path] = (mode, oid)
    return result


def actual_blob(path):
    path = Path(path)
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError(f"Tracked path has a symlink ancestor: {path}")
    metadata = path.lstat()
    for candidate in (path, *path.parents):
        if getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Tracked path has a reparse point: {path}")
    mode = metadata.st_mode
    if stat.S_ISLNK(mode):
        data = os.fsencode(os.readlink(path))
        return "120000", hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if not stat.S_ISREG(mode):
        raise ValueError(f"Expected regular tracked file: {path}")
    digest = hashlib.sha1(b"blob " + str(path.stat().st_size).encode() + b"\0")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return ("100755" if mode & 0o111 else "100644"), digest.hexdigest()


def verify_checkout(sha, *, generated=lambda path: False, assets=(), final=False):
    selected_sha(sha)
    selected = entries(run("git", "ls-tree", "-r", "-z", sha, "--"))
    indexed = entries(run("git", "ls-files", "--stage", "-z", "--"), index=True)
    for flag in ("-v", "-f"):
        if any(record and record[0] != "H" for record in
               run("git", "ls-files", flag, "-z", "--").split("\0")):
            raise ValueError("Hidden index/stat flags are unsupported")
    for path in selected.keys() | indexed.keys():
        if selected.get(path) != indexed.get(path):
            raise ValueError(f"Index source/config differs from selected SHA: {path}")
        if final and generated(path):
            continue
        try:
            actual_mode, actual_oid = actual_blob(path)
            expected_mode, expected_oid = selected[path]
            # NTFS checkouts cannot represent Git's POSIX executable bit.
            if WINDOWS and actual_mode in ("100644", "100755") \
                    and expected_mode in ("100644", "100755"):
                actual_mode = expected_mode
            if (actual_mode, actual_oid) != (expected_mode, expected_oid):
                raise ValueError(f"Working source/config differs from selected SHA: {path}")
        except OSError as error:
            raise ValueError(f"Working source/config missing or unreadable: {path}") from error
    untracked = filter(None, run("git", "ls-files", "--others", "-z", "--").split("\0"))
    if any(not (final and (generated(path) or path in assets)) for path in untracked):
        raise ValueError("Untracked source/config or unexpected output in checkout")
    if not final and run("git", "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Preflight requires a completely clean source checkout")
