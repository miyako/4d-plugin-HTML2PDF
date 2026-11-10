import codecs
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/scripts"))
import version_model as model


class VersionModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "HTML2PDF").mkdir()
        for path in (model.VERSION_PATH, model.CMAKE_PATH, model.PLIST_PATH):
            shutil.copyfile(ROOT / path, self.root / path)

    def test_live_authority(self):
        self.assertEqual(model.read(ROOT), (ROOT / "VERSION").read_text().strip())

    def test_encoding_endings_modes(self):
        for encoding, bom in (
            ("utf-8", b""), ("utf-8", codecs.BOM_UTF8),
            ("utf-16-le", codecs.BOM_UTF16_LE),
            ("utf-16-be", codecs.BOM_UTF16_BE),
            ("utf-16-le", b""), ("utf-16-be", b""),
        ):
            for ending in ("", "\r", "\n", "\r\n"):
                with self.subTest(encoding=encoding, bom=bom, ending=ending):
                    path = self.root / "VERSION"
                    path.write_bytes(bom + ("1.2.3" + ending).encode(encoding))
                    path.chmod(0o640)
                    self.assertEqual(model.bump(self.root, "patch"), "1.2.4")
                    self.assertEqual(path.read_bytes(), bom + ("1.2.4" + ending).encode(encoding))
                    self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_all_modes(self):
        for mode, expected in (("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")):
            (self.root / "VERSION").write_text("1.2.3\n")
            before = {p: (self.root / p).read_bytes() for p in (model.CMAKE_PATH, model.PLIST_PATH)}
            self.assertEqual(model.bump(self.root, mode), expected)
            self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})

    def test_invalid_version_no_writes(self):
        for version in ("01.2.3", "1.2.3-rc1", "1.2", "1.2.3\n1.2.3\n", " 1.2.3", ""):
            (self.root / "VERSION").write_text(version)
            before = (self.root / "VERSION").read_bytes()
            with self.assertRaises(ValueError):
                model.bump(self.root, "patch")
            self.assertEqual((self.root / "VERSION").read_bytes(), before)

    def test_drift_duplicates_missing_and_overrides_no_writes(self):
        path = self.root / model.CMAKE_PATH
        original = path.read_text()
        for altered in (
            original.replace('MACOSX_BUNDLE_SHORT_VERSION_STRING "${PLUGIN_VERSION}"',
                             'MACOSX_BUNDLE_SHORT_VERSION_STRING "${UNKNOWN}"'),
            original + '\nset_target_properties(x PROPERTIES OTHER foo "MACOSX_BUNDLE_SHORT_VERSION_STRING" "1.0")\n',
            original.replace('MACOSX_BUNDLE_BUNDLE_VERSION "1.0"', ""),
            original.replace('MACOSX_BUNDLE_BUNDLE_VERSION "1.0"',
                             'MACOSX_BUNDLE_BUNDLE_VERSION "01.0"'),
            original + '\nset_target_properties(x PROPERTIES "MACOSX_BUNDLE_BUNDLE_VERSION" "1.0")\n',
            original + '\nset_property(TARGET ${PLUGIN_NAME} PROPERTY MACOSX_BUNDLE_BUNDLE_VERSION 1.0)\n',
            original.replace('set_target_properties(${PLUGIN_NAME} PROPERTIES\n        BUNDLE',
                             'set_target_properties(other PROPERTIES\n        BUNDLE'),
            original.replace('set(PLUGIN_NAME "HTML2PDF"', 'set(PLUGIN_NAME "Wrong"'),
            original + "\nset(PLUGIN_VERSION 1.2.3)\n",
            original.replace("LIMIT_COUNT 1", "LIMIT_COUNT 2"),
        ):
            path.write_text(altered)
            before = (self.root / "VERSION").read_bytes()
            with self.assertRaises(ValueError):
                model.bump(self.root, "patch")
            self.assertEqual((self.root / "VERSION").read_bytes(), before)

    def test_comments_are_not_assignments(self):
        path = self.root / model.CMAKE_PATH
        path.write_text(path.read_text() + '\n# MACOSX_BUNDLE_BUNDLE_VERSION "2.0"\n#[=[\nMACOSX_BUNDLE_BUNDLE_VERSION "3.0"\n]=]\nset(NOISE "MACOSX_BUNDLE_BUNDLE_VERSION")\n')
        self.assertEqual(model.read(self.root), model.read(ROOT))

    def test_required_short_and_duplicate_build(self):
        path = self.root / model.PLIST_PATH
        original = path.read_text()
        for altered in (
            original.replace("<key>CFBundleShortVersionString</key>", "<key>other</key>"),
            original.replace("</dict>", "<key>CFBundleVersion</key><string>1.0</string></dict>"),
        ):
            path.write_text(altered)
            with self.assertRaises(ValueError):
                model.read(self.root)

    def test_optional_build_absence_preserved(self):
        path = self.root / model.PLIST_PATH
        path.write_text(path.read_text().replace(
            "<key>CFBundleVersion</key>\n    <string>${MACOSX_BUNDLE_BUNDLE_VERSION}</string>", ""))
        before = path.read_bytes()
        self.assertFalse(model.has_build_key(self.root))
        model.bump(self.root, "minor")
        self.assertEqual(path.read_bytes(), before)

    def test_metadata_encodings_and_mixed_endings_remain_exactly_unchanged(self):
        baseline = {path: (ROOT / path).read_text() for path in
                    (model.CMAKE_PATH, model.PLIST_PATH)}
        for encoding, bom in (
            ("utf-8", b""), ("utf-8", codecs.BOM_UTF8),
            ("utf-16-le", codecs.BOM_UTF16_LE), ("utf-16-be", codecs.BOM_UTF16_BE),
            ("utf-16-le", b""), ("utf-16-be", b""),
        ):
            for path, text in baseline.items():
                lines = text.splitlines()
                mixed = "".join(line + ("\r\n", "\n", "\r")[i % 3]
                                for i, line in enumerate(lines))
                (self.root / path).write_bytes(bom + mixed.encode(encoding))
            before = {path: (self.root / path).read_bytes() for path in baseline}
            model.bump(self.root, "patch")
            self.assertEqual(before, {path: (self.root / path).read_bytes()
                                      for path in baseline})

    def test_invalid_mode_has_zero_writes(self):
        before = (self.root / "VERSION").read_bytes()
        with self.assertRaises(ValueError):
            model.bump(self.root, "invalid")
        self.assertEqual(before, (self.root / "VERSION").read_bytes())


if __name__ == "__main__":
    unittest.main()
