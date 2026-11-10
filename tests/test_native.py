"""Native validation and cleanup without invoking native or credential tools."""

from pathlib import Path
import plistlib
import shutil
import stat
from types import SimpleNamespace
from unittest.mock import patch

from helper_support import Fixture, cwd, original
import native
import source_version


class NativeTests(Fixture):
    def setUp(self):
        super().setUp()
        self.sources()
        for name in native.RESOURCES:
            self.write("HTML2PDF/" + name, original("HTML2PDF/" + name))
        self.populate()

    def populate(self, binary=False):
        self.write(native.CONTENTS / "Info.plist", plistlib.dumps({
            "CFBundleShortVersionString": source_version.read(self.root), "CFBundleVersion": "1.0",
            "CFBundleExecutable": "HTML2PDF", "CFBundleIdentifier": "com.4d.HTML2PDF",
            "CFBundlePackageType": "BNDL",
        }, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML))
        for relative in native.FILES:
            if relative != native.CONTENTS / "Info.plist":
                self.write(relative, b"fresh native bytes")
        for name in native.RESOURCES:
            self.write(native.CONTENTS / "Resources" / name,
                       (self.root / "HTML2PDF" / name).read_bytes())

    def test_xml_and_binary_metadata_source_short_and_independent_build(self):
        for binary in (False, True):
            self.populate(binary)
            self.assertEqual(native.validate(self.root), (self.root / "VERSION").read_text().strip())
            self.assertEqual(native.validate_final(self.root), native.validate(self.root))

    def test_unsigned_validation_separate_from_final_signature_gate(self):
        (self.root / native.CONTENTS / "_CodeSignature/CodeResources").unlink()
        native.validate(self.root)
        with self.assertRaisesRegex(ValueError, "native leaf"):
            native.validate_final(self.root)

    def test_metadata_drift_missing_short_and_invalid_plist_rejected(self):
        path = self.root / native.CONTENTS / "Info.plist"
        for change in ({"CFBundleShortVersionString": "900.800.700"}, {"CFBundleVersion": "1.0.9"},
                       {"CFBundleExecutable": "wrong"}, {"CFBundleIdentifier": "wrong"},
                       {"CFBundlePackageType": "APPL"}, {"CFBundleShortVersionString": None}):
            self.populate()
            metadata = plistlib.loads(path.read_bytes())
            metadata.update(change)
            path.write_bytes(plistlib.dumps({k: v for k, v in metadata.items() if v is not None}))
            with self.assertRaises(ValueError):
                native.validate(self.root)
        for raw in (b"not a plist", b"", plistlib.dumps([])):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                native.validate(self.root)

    def test_optional_source_build_key_absence_preserved(self):
        path = self.root / "HTML2PDF/Info.plist.in"
        raw = path.read_bytes()
        raw = raw.replace(
            b"    <key>CFBundleVersion</key>\n    <string>${MACOSX_BUNDLE_BUNDLE_VERSION}</string>\n",
            b"",
        )
        path.write_bytes(raw)
        built = self.root / native.CONTENTS / "Info.plist"
        metadata = plistlib.loads(built.read_bytes())
        with self.assertRaisesRegex(ValueError, "invented"):
            native.validate(self.root)
        del metadata["CFBundleVersion"]
        built.write_bytes(plistlib.dumps(metadata))
        native.validate(self.root)

    def test_final_resources_and_download_are_exact(self):
        for relative in (native.DOWNLOAD, native.MERGED,
                         *(native.CONTENTS / "Resources" / name for name in native.RESOURCES)):
            self.populate()
            (self.root / relative).write_bytes(b"late substitution")
            with self.assertRaises(ValueError):
                native.validate_final(self.root)

    def test_final_every_leaf_regular_nonempty_nonsymlink(self):
        for relative in native.FILES:
            self.populate()
            path = self.root / relative
            saved = path.read_bytes()
            for kind in ("missing", "empty", "directory", "symlink"):
                path.unlink()
                if kind == "empty":
                    path.write_bytes(b"")
                elif kind == "directory":
                    path.mkdir()
                elif kind == "symlink":
                    peer = self.write("samebytes", saved)
                    path.symlink_to(peer)
                with self.assertRaises(ValueError):
                    native.validate_final(self.root)
                if kind == "directory":
                    path.rmdir()
                elif path.exists() or path.is_symlink():
                    path.unlink()
                path.write_bytes(saved)

    def test_architecture_tokens_require_both_but_do_not_invent_exclusion(self):
        for value in ("arm64 x86_64", "arm64 x86_64 i386", "arm64e arm64 x86_64"):
            native.architectures(value)
        for value in ("arm64e x86_64", "arm64 x86_64h", "", "i386"):
            with self.assertRaises(ValueError):
                native.architectures(value)

    def test_selective_cleanup_retains_tracked_inputs_windows_and_bundle_siblings(self):
        protected = (
            native.CONTENTS / "Resources/custom.txt", native.CONTENTS / "MacOS/runtime.dylib",
            native.CONTENTS / "QuickLook/Thumbnail.png",
            native.BASE / "Default/keep", native.BASE / "Other.bundle/keep",
            Path("HTML2PDF/cmake-build-evil/keep"), native.MERGED, native.DOWNLOAD,
            Path("HTML2PDF/manifest.json"), Path("HTML2PDF/constants.xlf"),
        )
        for relative in protected[:6]:
            self.write(relative, b"preserved")
        before = {relative: (self.root / relative).read_bytes() for relative in protected}
        self.write(native.BUILD / "CMakeCache.txt", b"stale")
        native.clean("macos", self.root)
        native.clean("macos", self.root)
        for relative, raw in before.items():
            self.assertEqual((self.root / relative).read_bytes(), raw)
        for relative in (native.EXECUTABLE, native.CONTENTS / "Info.plist", native.BUILD):
            self.assertFalse((self.root / relative).exists())
        self.assertTrue((self.root / native.BUNDLE).is_dir())

    def test_symlink_and_reparse_prevalidation_precedes_any_cleanup(self):
        for relative in (native.FILES[-2], native.BUILD / "nested/link"):
            self.populate()
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            outside = self.write("outside/keep", b"untouched")
            path.symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                native.clean("macos", self.root)
            self.assertEqual((self.root / native.EXECUTABLE).read_bytes(), b"fresh native bytes")
            path.unlink()
        real = Path.lstat

        def reparse(path, *args, **kwargs):
            metadata = real(path, *args, **kwargs)
            if path == self.root / native.CONTENTS:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return metadata

        with patch.object(Path, "lstat", new=reparse):
            with self.assertRaisesRegex(ValueError, "reparse"):
                native.clean("macos", self.root)
        self.assertTrue((self.root / native.EXECUTABLE).is_file())

    def test_cleanup_io_error_is_fatal(self):
        with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                native.clean("macos", self.root)
        self.write(native.BUILD / "cache", b"stale")
        with patch.object(shutil, "rmtree", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                native.clean("macos", self.root)

    def test_merge_prevalidates_download_and_destination_before_copy(self):
        saved = (self.root / native.MERGED).read_bytes()
        (self.root / native.DOWNLOAD).unlink()
        with self.assertRaises(ValueError):
            native.merge_windows(self.root)
        self.assertEqual((self.root / native.MERGED).read_bytes(), saved)
        self.write(native.DOWNLOAD, b"new Windows")
        path = self.root / native.MERGED
        path.unlink()
        path.symlink_to(self.root / native.DOWNLOAD)
        with self.assertRaisesRegex(ValueError, "symlink"):
            native.merge_windows(self.root)
        path.unlink()
        native.merge_windows(self.root)
        self.assertEqual(path.read_bytes(), b"new Windows")
