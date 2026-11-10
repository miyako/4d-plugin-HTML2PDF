"""Execute actual workflow scripts behind closed-PATH native/credential stubs."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from helper_support import Fixture, GitFixture, ROOT, original, source
import native


STUB = r'''#!PYTHON
import base64, json, os, pathlib, plistlib, sys
tool, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ["NATIVE_LOG"], "a") as out:
    out.write(json.dumps([tool, *args])+"\n")
if os.environ.get("FAIL_TOOL") == tool:
    sys.exit(23)
contents = pathlib.Path("HTML2PDF/HTML2PDF-test/Plugins/HTML2PDF.bundle/Contents")
if tool in ("python", "python3"):
    if args and args[0].endswith("release.py"):
        assert os.environ["GH_TOKEN"] == "offline-only"
        assert os.environ["GITHUB_REPOSITORY"] == "miyako/4d-plugin-HTML2PDF"
        assert args[2:4] == ["--sha", os.environ["GITHUB_SHA"]]
        if os.environ.get("FAIL_PREFLIGHT") and args[1] == "preflight":
            sys.exit(9)
        if args[1] == "publish":
            assert args[4:] == [f"HTML2PDF-{os.environ['VERSION']}.zip",
                                f"HTML2PDF-{os.environ['VERSION']}.dmg"]
    else:
        os.execv(sys.executable, [sys.executable, *args])
elif tool == "cmake":
    if os.environ.get("FAIL_CMAKE") == ("build" if "--build" in args else "configure"):
        sys.exit(7)
    if args[0] == "--build":
        if "--config" in args:
            assert args == ["--build", "HTML2PDF/cmake-build/windows", "--config", "Release"]
            root = pathlib.Path("HTML2PDF/cmake-build/source")
            output = root / "HTML2PDF/HTML2PDF-test/Plugins/HTML2PDF/Contents"
            for name in ("manifest.json", "constants.xlf"):
                target = output / "Resources" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((root / "HTML2PDF" / name).read_bytes())
            target = output / "Windows64/HTML2PDF.4DX"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not os.environ.get("NO_BINARY"):
                target.write_bytes(b"fresh-windows")
            if os.environ.get("COPY_MUTATION"):
                (root / "deps/litehtml/include/litehtml/pixel_type.h").write_bytes(b"unrelated edit")
            if os.environ.get("ORIGINAL_MUTATION"):
                pathlib.Path("deps/litehtml/include/litehtml/pixel_type.h").write_bytes(b"source mutation")
        else:
            assert args == ["--build", "HTML2PDF/cmake-build"]
            if not os.environ.get("NO_BINARY"):
                (contents / "MacOS").mkdir(parents=True, exist_ok=True)
                (contents / "MacOS/HTML2PDF").write_bytes(b"fresh-macos")
                (contents / "Info.plist").write_bytes(plistlib.dumps({
                    "CFBundleShortVersionString": os.environ["VERSION"], "CFBundleVersion": "1.0",
                    "CFBundleExecutable": "HTML2PDF", "CFBundleIdentifier": "com.4d.HTML2PDF",
                    "CFBundlePackageType": "BNDL",
                }, fmt=plistlib.FMT_BINARY))
                for name in ("manifest.json", "constants.xlf"):
                    target = contents / "Resources" / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes((pathlib.Path("HTML2PDF") / name).read_bytes())
    elif "-A" in args:
        assert args == ["-S", "HTML2PDF/cmake-build/source/HTML2PDF",
                        "-B", "HTML2PDF/cmake-build/windows", "-A", "x64"]
        assert pathlib.Path("HTML2PDF/cmake-build/source/VERSION").read_bytes() == pathlib.Path("VERSION").read_bytes()
        pixel = pathlib.Path("HTML2PDF/cmake-build/source/deps/litehtml/include/litehtml/pixel_type.h")
        raw = pixel.read_bytes()
        for op in ("==", "!=", "<", ">", "<=", ">="):
            raw = raw.replace(("constexpr bool operator"+op).encode(),("inline bool operator"+op).encode())
        pixel.write_bytes(raw)
        pathlib.Path("HTML2PDF/cmake-build/windows").mkdir(parents=True, exist_ok=True)
    else:
        assert args == ["-S", "HTML2PDF", "-B", "HTML2PDF/cmake-build",
                        "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64",
                        "-DCMAKE_OSX_DEPLOYMENT_TARGET=10.13"]
        for relative in ("MacOS/HTML2PDF", "Info.plist", "Resources/manifest.json",
                         "Resources/constants.xlf", "_CodeSignature/CodeResources"):
            assert not (contents / relative).exists(), relative
elif tool == "lipo":
    assert args[:1] == ["-archs"]
    print(os.environ.get("ARCHS", "arm64 x86_64"))
elif tool == "base64":
    pathlib.Path(args[args.index("-o")+1]).write_bytes(base64.b64decode(sys.stdin.read()))
elif tool == "security":
    if args[0] == "find-identity":
        print("" if os.environ.get("MISSING_IDENTITY") else '1) FIXTURE "Developer ID Application: Fixture"')
elif tool == "codesign":
    if "--verify" in args and os.environ.get("FAIL_VERIFY"):
        sys.exit(7)
    if "--verify" not in args:
        (contents / "_CodeSignature").mkdir(exist_ok=True)
        (contents / "_CodeSignature/CodeResources").write_bytes(b"fresh-signature")
elif tool in ("ditto", "hdiutil"):
    suffix = "zip" if tool == "ditto" else "dmg"
    assert args[-1] == f"HTML2PDF-{os.environ['VERSION']}.{suffix}"
    pathlib.Path(args[-1]).write_bytes(b"offline-package")
elif tool == "xcrun":
    if args[:2] == ["notarytool", "submit"]:
        print(os.environ.get("NOTARY_JSON", '{"status":"Accepted"}'))
        sys.exit(int(os.environ.get("NOTARY_EXIT", "0")))
    elif args[:2] == ["stapler", "staple"]:
        sys.exit(int(os.environ.get("STAPLE_EXIT", "0")))
    else:
        assert args[:2] == ["notarytool", "store-credentials"]
else:
    sys.exit("UNSTUBBED TOOL "+tool)
'''


def tools_at(path, *, python_stub):
    path.mkdir()
    for tool in ("cmake", "lipo", "base64", "security", "codesign", "ditto", "hdiutil", "xcrun"):
        target = path / tool
        target.write_text(STUB.replace("PYTHON", sys.executable))
        target.chmod(0o755)
    for tool in ("python", "python3"):
        target = path / tool
        if python_stub:
            target.write_text(STUB.replace("PYTHON", sys.executable))
            target.chmod(0o755)
        else:
            target.symlink_to(sys.executable)
    for tool in ("bash", "grep", "head", "sed", "git"):
        (path / tool).symlink_to(shutil.which(tool))


class NativeWorkflowTests(Fixture):
    def setUp(self):
        super().setUp()
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        self.tools = self.root / "tools"
        tools_at(self.tools, python_stub=True)
        self.log = self.root / "native.jsonl"
        shutil.copytree(ROOT / ".github/scripts", self.checkout / ".github/scripts",
                        ignore=shutil.ignore_patterns("__pycache__"))
        self.sources(self.checkout)
        for name in native.RESOURCES:
            path = self.checkout / "HTML2PDF" / name
            path.write_bytes(original("HTML2PDF/" + name))
        for relative in native.FILES:
            path = self.checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"stale")
        (self.checkout / native.DOWNLOAD).write_bytes(b"fresh-windows")
        self.protected = {}
        for relative in (
            native.CONTENTS / "MacOS/runtime.dylib", native.CONTENTS / "QuickLook/Thumbnail.png",
            native.CONTENTS / "Resources/custom.txt", native.BASE / "Default/keep",
            Path("HTML2PDF/cmake-build-evil/keep"),
        ):
            path = self.checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"preserved")
            self.protected[path] = b"preserved"
        self.env = {
            "PATH": str(self.tools), "HOME": str(self.checkout), "LC_ALL": "C",
            "RUNNER_TEMP": str(self.checkout), "NATIVE_LOG": str(self.log),
            "MACOS_DEPLOYMENT_TARGET": "10.13", "VERSION": source.read(self.checkout),
            "BUNDLE_PATH": str(native.BUNDLE), "GITHUB_ENV": str(self.checkout / "github-env"),
            "KEYCHAIN_PATH": str(self.checkout / "offline.keychain"),
            "GITHUB_SHA": "a" * 40, "GH_TOKEN": "offline-only",
            "GITHUB_REPOSITORY": "miyako/4d-plugin-HTML2PDF",
            "PYTHONDONTWRITEBYTECODE": "1", "CERT_BASE64": "b2ZmbGluZQ==",
            "CERT_PASSWORD": "offline-only", "KEYCHAIN_PASSWORD": "offline-only",
            "APPLE_ID": "offline@example.invalid", "TEAM_ID": "OFFLINEONLY",
            "APP_PASSWORD": "offline-only",
        }
        self.jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def pipeline(self):
        for job in ("version", "build-macos"):
            for step in self.jobs[job]["steps"]:
                if "run" not in step:
                    continue
                self.assertNotIn("${{", step["run"])
                result = subprocess.run(
                    ["/bin/bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                    cwd=self.checkout, env=self.env, text=True, capture_output=True, timeout=30)
                if result.returncode:
                    return result
                environment = self.checkout / "github-env"
                if environment.exists():
                    for line in environment.read_text().splitlines():
                        key, value = line.split("=", 1)
                        self.env[key] = value
        return result

    def test_complete_real_workflow_scripts_keep_native_topology_and_publish_after_staple(self):
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.checkout / native.EXECUTABLE).read_bytes(), b"fresh-macos")
        self.assertEqual((self.checkout / native.MERGED).read_bytes(), b"fresh-windows")
        self.assertEqual((self.checkout / native.CONTENTS / "_CodeSignature/CodeResources").read_bytes(),
                         b"fresh-signature")
        for path, raw in self.protected.items():
            self.assertEqual(path.read_bytes(), raw)
        calls = self.calls()
        index = lambda test: next(i for i, call in enumerate(calls) if test(call))
        self.assertLess(index(lambda c: c[0] == "cmake"), index(lambda c: c[0] == "codesign"))
        self.assertLess(index(lambda c: c[0] == "codesign"), index(lambda c: c[0] == "ditto"))
        self.assertLess(index(lambda c: c[:3] == ["xcrun", "stapler", "staple"]),
                        index(lambda c: c[0] == "python3" and "publish" in c))
        self.assertEqual(sum(c[:3] == ["xcrun", "notarytool", "submit"] for c in calls), 2)
        self.assertTrue(all("--deep" in c and "--strict" in c for c in calls
                            if c[0] == "codesign" and "--verify" in c))

    def test_source_version_dynamic_not_original_intake_literal(self):
        (self.checkout / "VERSION").write_text("3.2.1\n")
        self.env["VERSION"] = "3.2.1"
        result = self.pipeline()
        self.assertEqual(result.returncode, 0, result.stderr)
        for suffix in ("zip", "dmg"):
            self.assertTrue((self.checkout / f"HTML2PDF-3.2.1.{suffix}").is_file())

    def test_preflight_failure_precedes_native_and_credentials(self):
        self.env["FAIL_PREFLIGHT"] = "1"
        result = self.pipeline()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(all(call[0] == "python3" for call in self.calls()))

    def test_configure_build_stale_arch_sign_notary_and_staple_failures_never_publish(self):
        variants = [
            {"FAIL_CMAKE": "configure"}, {"FAIL_CMAKE": "build"}, {"NO_BINARY": "1"},
            {"ARCHS": "arm64e x86_64"}, {"ARCHS": "arm64 x86_64h"},
            {"MISSING_IDENTITY": "1"}, {"FAIL_VERIFY": "1"},
            {"NOTARY_JSON": '{"status":"Invalid"}'}, {"NOTARY_EXIT": "1"},
            {"NOTARY_JSON": '{"status":"Accepted","status":"Invalid"}'},
            {"NOTARY_JSON": '{"status":"Accepted","value":NaN}'},
            {"NOTARY_JSON": '{"status":"Accepted","value":1e999}'},
            {"NOTARY_JSON": "[]"}, {"STAPLE_EXIT": "1"},
        ]
        initial = dict(self.env)
        for extra in variants:
            self.log.unlink(missing_ok=True)
            for suffix in ("zip", "dmg"):
                (self.checkout / f"HTML2PDF-{self.env['VERSION']}.{suffix}").unlink(missing_ok=True)
            self.env = {**initial, **extra}
            result = self.pipeline()
            self.assertNotEqual(result.returncode, 0, extra)
            self.assertFalse(any(c[0] == "python3" and "publish" in c for c in self.calls()))
            if "NOTARY_JSON" in extra or "NOTARY_EXIT" in extra:
                self.assertFalse(any(c[:3] == ["xcrun", "stapler", "staple"] for c in self.calls()))


class WindowsCopyTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.tools = self.root / "tools"
        tools_at(self.tools, python_stub=False)
        for relative, raw in (
            ("deps/litehtml/include/litehtml/pixel_type.h",
             b"constexpr bool operator==(int);\nconstexpr bool operator<=(int);\n"),
            ("deps/litehtml/empty.h", b""),
            ("4D-Plugin-SDK/4D Plugin API/4DPluginAPI.h", b"selected sdk"),
            ("HTML2PDF/manifest.json", original("HTML2PDF/manifest.json")),
            ("HTML2PDF/constants.xlf", original("HTML2PDF/constants.xlf")),
            (str(native.MERGED), b"selected prebuilt Windows"),
        ):
            path = self.local / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (self.local / ".gitignore").write_text("HTML2PDF/cmake-build/*\n")
        self.git("add", "-f", ".")
        self.git("commit", "--quiet", "-m", "selected native sources")
        self.sha = self.git("rev-parse", "HEAD")
        self.env.update(PATH=str(self.tools), GITHUB_SHA=self.sha,
                        NATIVE_LOG=str(self.root / "native.jsonl"),
                        POWERSHELL_TELEMETRY_OPTOUT="1", DOTNET_CLI_TELEMETRY_OPTOUT="1")

    def run_windows(self, **extra):
        powershell = shutil.which("pwsh")
        self.assertIsNotNone(powershell, "PowerShell required for actual extracted Windows scripts")
        jobs = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())["jobs"]
        step = next(s for s in jobs["build-windows"]["steps"] if s.get("name") == "build with CMake")
        script = self.root / "windows-build.ps1"
        script.write_text(step["run"])
        return subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(script)],
                              cwd=self.local, env={**self.env, **extra},
                              text=True, capture_output=True, timeout=60)

    def test_actual_windows_helper_builds_only_committed_copy_and_preserves_original(self):
        pixel = self.local / native.PIXEL
        original_pixel = pixel.read_bytes()
        result = self.run_windows()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(pixel.read_bytes(), original_pixel)
        self.assertEqual((self.local / native.COPY / "VERSION").read_bytes(),
                         (self.local / "VERSION").read_bytes())
        self.assertEqual((self.local / native.COPY_WINDOWS).read_bytes(), b"fresh-windows")
        self.assertIn(b"inline bool operator", (self.local / native.COPY / native.PIXEL).read_bytes())
        self.assertFalse((self.local / native.COPY / native.MERGED).exists())
        self.assertEqual((self.local / native.MERGED).read_bytes(), b"selected prebuilt Windows")
        self.assertEqual(self.git("diff", "--name-only", "HEAD"), "")

    def test_windows_failures_missing_outputs_and_copy_or_original_source_mutation_fail_closed(self):
        for extra in ({"FAIL_CMAKE": "configure"}, {"FAIL_CMAKE": "build"},
                      {"NO_BINARY": "1"}, {"COPY_MUTATION": "1"}, {"ORIGINAL_MUTATION": "1"}):
            result = self.run_windows(**extra)
            self.assertNotEqual(result.returncode, 0, extra)
            self.git("restore", "--", str(native.PIXEL))
            shutil.rmtree(self.local / native.BUILD)

    def test_windows_initial_source_drift_fails_before_cmake(self):
        pixel = self.local / native.PIXEL
        pixel.write_bytes(b"unexpected original mutation")
        result = self.run_windows()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "native.jsonl").exists())

    def test_snapshot_raw_bytes_revalidated_before_configure(self):
        executable = shutil.which("git")
        git = self.tools / "git"
        git.unlink()
        git.write_text(
            f"#!{sys.executable}\nimport os,subprocess,sys\n"
            "if sys.argv[1:3] == ['cat-file','blob']:\n"
            f"    raw=subprocess.check_output([{executable!r},*sys.argv[1:]])\n"
            "    sys.stdout.buffer.write(raw+b'altered snapshot bytes')\n"
            "else:\n"
            f"    os.execv({executable!r},[{executable!r},*sys.argv[1:]])\n"
        )
        git.chmod(0o755)
        result = self.run_windows()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected Windows build copy mutation", result.stdout + result.stderr)
        self.assertFalse((self.root / "native.jsonl").exists())
