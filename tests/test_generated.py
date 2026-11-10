"""Only actual CMake products, not arbitrary build/source siblings, are generated."""

from helper_support import GitFixture, cwd
import native
import repository


class GeneratedTests(GitFixture):
    def test_exact_native_and_dependency_cmake_outputs_final_only_and_retained(self):
        paths = [
            *map(str, native.FILES),
            "HTML2PDF/cmake-build/CMakeCache.txt",
            "HTML2PDF/cmake-build/litehtml/liblitehtml.a",
            "HTML2PDF/cmake-build/litehtml/src/gumbo/libgumbo.a",
            "HTML2PDF/cmake-build/libharu/include/include/hpdf_config.h",
            "HTML2PDF/cmake-build/libharu/include/src/libhpdf.a",
            "HTML2PDF/cmake-build/CMakeFiles/HTML2PDF.dir/pdf_container.cpp.o",
            "HTML2PDF/cmake-build/litehtml/CMakeFiles/litehtml.dir/src/html.cpp.o.d",
            "HTML2PDF/cmake-build/CMakeFiles/3.31.0/CompilerIdC/CMakeCCompilerId.c",
            "HTML2PDF/cmake-build/litehtml/CMakeFiles/Export/"
            "0123456789abcdef0123456789abcdef/litehtmlTargets-release.cmake",
        ]
        for relative in paths:
            self.assertTrue(native.generated(relative), relative)
            path = self.local / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fresh native bytes")
        with cwd(self.local):
            with self.assertRaises(ValueError):
                repository.verify_checkout(self.sha, generated=native.generated)
            repository.verify_checkout(self.sha, generated=native.generated, final=True)
        for relative in paths:
            self.assertEqual((self.local / relative).read_bytes(), b"fresh native bytes")

    def test_source_bundle_cmake_xcode_and_alias_negatives(self):
        paths = (
            "VERSION", "HTML2PDF/CMakeLists.txt", "HTML2PDF/Info.plist.in",
            "HTML2PDF/manifest.json", "HTML2PDF/constants.xlf", "deps/litehtml/source.cpp",
            str(native.CONTENTS / "Resources/manifest.json.bak"),
            str(native.CONTENTS / "Resources/unexpected.cpp"),
            str(native.CONTENTS / "MacOS/other"),
            str(native.CONTENTS / "_CodeSignature/evil"),
            "HTML2PDF/cmake-build-evil/CMakeCache.txt",
            "HTML2PDF/cmake-build/unexpected-source.cpp",
            "HTML2PDF/cmake-build/CMakeFiles/unexpected-source.cpp",
            "HTML2PDF/cmake-build/CMakeFiles/build.db-evil",
            "HTML2PDF/cmake-build/source/deps/litehtml/source.cpp",
            "build/XCBuildData/build.db", "build/XCBuildData/unexpected-source.cpp",
            "build/XCBuildData/build.db-evil", "build/XCBuildData/evil.xcbuilddata/manifest.json",
            "build/XCBuildData/0123456789abcdef0123456789abcdef.xcbuilddata/manifest.json",
            "HTML2PDF/cmake-build/build/XCBuildData/evil.xcbuilddata/manifest.json",
            "../HTML2PDF/cmake-build/CMakeCache.txt",
            "./HTML2PDF/cmake-build/CMakeCache.txt",
            "HTML2PDF//cmake-build/CMakeCache.txt",
            "HTML2PDF\\cmake-build\\CMakeCache.txt",
        )
        for relative in paths:
            self.assertFalse(native.generated(relative), relative)

    def test_generated_tracked_index_changes_still_rejected(self):
        path = self.local / native.EXECUTABLE
        path.parent.mkdir(parents=True)
        path.write_bytes(b"old")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "tracked generated fixture")
        sha = self.git("rev-parse", "HEAD")
        path.write_bytes(b"new")
        with cwd(self.local):
            repository.verify_checkout(sha, generated=native.generated, final=True)
        self.git("add", ".")
        with cwd(self.local), self.assertRaisesRegex(ValueError, "Index"):
            repository.verify_checkout(sha, generated=native.generated, final=True)
