"""Immutable index and raw bytes are independent of Git's stat caches."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from helper_support import GitFixture, cwd
import repository


class RepositoryTests(GitFixture):
    def test_windows_only_regular_executable_bit_compatibility(self):
        relative = ".github/hooks/pre-push"
        target = self.local / relative
        expected = repository.actual_blob(target)
        self.assertEqual(expected[0], "100755")
        real_blob = repository.actual_blob

        def windows_blob(path):
            mode, oid = real_blob(path)
            return ("100644" if mode == "100755" else mode), oid

        with cwd(self.local), patch.object(repository, "actual_blob", side_effect=windows_blob):
            with self.assertRaisesRegex(ValueError, "Working source"):
                repository.verify_checkout(self.sha)
            with patch.object(repository, "WINDOWS", True):
                repository.verify_checkout(self.sha)
                target.write_bytes(target.read_bytes() + b"# raw mutation\n")
                with self.assertRaisesRegex(ValueError, "Working source"):
                    repository.verify_checkout(self.sha)

    def test_windows_tolerance_never_normalizes_index_modes_or_reversed_staging(self):
        target = self.local / "VERSION"
        before = target.read_bytes()
        with cwd(self.local), patch.object(repository, "WINDOWS", True):
            self.git("update-index", "--chmod=+x", "--", "VERSION")
            with self.assertRaisesRegex(ValueError, "Index source"):
                repository.verify_checkout(self.sha)
            self.git("update-index", "--chmod=-x", "--", "VERSION")
            target.write_bytes(before + b" ")
            self.git("add", "VERSION")
            target.write_bytes(before)
            with self.assertRaisesRegex(ValueError, "Index source"):
                repository.verify_checkout(self.sha)

    def test_raw_crlf_is_not_normalized(self):
        target = self.local / "VERSION"
        target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
        with cwd(self.local), patch.object(repository, "WINDOWS", True):
            with self.assertRaisesRegex(ValueError, "Working source"):
                repository.verify_checkout(self.sha)

    def test_samebytes_symlink_directory_and_reparse_cannot_use_windows_tolerance(self):
        target = self.local / "VERSION"
        before = target.read_bytes()
        outside = self.root / "same-bytes"
        outside.write_bytes(before)
        target.unlink()
        with cwd(self.local), patch.object(repository, "WINDOWS", True):
            target.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "Working source"):
                repository.verify_checkout(self.sha)
            target.unlink()
            target.mkdir()
            with self.assertRaisesRegex(ValueError, "regular tracked"):
                repository.verify_checkout(self.sha)
            target.rmdir()
            target.write_bytes(before)
            original = Path.lstat

            def reparse(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                if path == Path("VERSION"):
                    return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
                return result

            with patch.object(Path, "lstat", reparse):
                with self.assertRaisesRegex(ValueError, "reparse"):
                    repository.verify_checkout(self.sha)

    def test_hidden_flags_ignored_untracked_and_head_fail_closed(self):
        with cwd(self.local):
            for flag in ("--assume-unchanged", "--skip-worktree"):
                self.git("update-index", flag, "--", "VERSION")
                with self.assertRaisesRegex(ValueError, "Hidden"):
                    repository.verify_checkout(self.sha)
                self.git("update-index", "--no-" + flag[2:], "--", "VERSION")
            for relative in ("untracked-source.cpp",):
                path = self.local / relative
                path.write_bytes(b"unexpected")
                with self.assertRaisesRegex(ValueError, "Untracked"):
                    repository.verify_checkout(self.sha)
                path.unlink()
            exclude = self.local / ".git/info/exclude"
            exclude.parent.mkdir(exist_ok=True)
            exclude.write_text("ignored-source.cpp\n")
            path = self.local / "ignored-source.cpp"
            path.write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "Untracked"):
                repository.verify_checkout(self.sha)
            path.unlink()
            with self.assertRaisesRegex(ValueError, "HEAD"):
                repository.verify_checkout(self.ancestor)

    def test_no_gitlinks_in_this_repository_or_dependency_exceptions(self):
        self.assertNotIn("160000 ", self.git("ls-tree", "-r", "HEAD"))
        with self.assertRaisesRegex(ValueError, "non-blob"):
            repository.entries("160000 commit " + "a" * 40 + "\tdeps/litehtml\0")
