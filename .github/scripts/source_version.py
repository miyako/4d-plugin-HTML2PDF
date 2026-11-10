#!/usr/bin/env python3
"""Canonical release version from the selected source checkout."""

from pathlib import Path
import argparse

import version_model

ROOT = Path(__file__).resolve().parents[2]
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
SOURCE_PATHS = (Path("VERSION"),)


def read(root=Path(".")):
    return version_model.read(root)


def bump(mode, root=Path(".")):
    return version_model.bump(root, mode)


def verify_bundle(bundle, root=Path(".")):
    import native
    if Path(bundle) != native.BUNDLE:
        raise ValueError("unexpected built bundle path")
    native.validate(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bump", choices=("patch", "minor", "major"))
    args = parser.parse_args()
    print(bump(args.bump) if args.bump else read())
