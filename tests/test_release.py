"""Create-only API matrices and real-Git/closed-gh publication regressions."""

import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from unittest.mock import patch

from helper_support import GitFixture, source
import native
import release


TAG, SHA = "v3.2.1", "a" * 40
# Independent canonical API identity, not derived from the helper under test.
REPO = "miyako/4d-plugin-HTML2PDF"
BASE = "repos/" + REPO
UPLOAD = f"https://uploads.github.com/repos/{REPO}/releases/789/assets"


def entry(identifier=1, tag="v9.8.7", draft=False):
    return {"id": identifier, "tag_name": tag, "draft": draft, "prerelease": False}


def ref(tag=TAG, sha=SHA, kind="commit"):
    return {"ref": "refs/tags/" + tag, "object": {"sha": sha, "type": kind}}


class API:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def api(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.replies:
            raise AssertionError("Unexpected API call")
        response = self.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AvailabilityTests(GitFixture):
    def available(self, api, tag=TAG):
        with patch.object(release.repository, "run",
                          side_effect=lambda *args: self.git(*args[1:])):
            return release.available(api, tag)

    def test_pagination_through_empty_page_drafts_and_prefix_refs(self):
        api = API([[entry(i + 1) for i in range(100)], [entry(101)], [], []])
        self.assertEqual(len(self.available(api)), 101)
        self.assertEqual([call[0][1] for call in api.calls], [
            f"{BASE}/releases?per_page=100&page=1",
            f"{BASE}/releases?per_page=100&page=2",
            f"{BASE}/releases?per_page=100&page=3",
            f"{BASE}/git/matching-refs/tags/{TAG}",
        ])
        for draft in (False, True):
            with self.assertRaises(ValueError):
                self.available(API([[entry(1)], [entry(2, TAG, draft)], [], []]))
        with self.assertRaises(ValueError):
            self.available(API([[], [ref()]]))
        self.available(API([[], [ref(TAG + "0"), ref(TAG + "-rc1")]]))

    def test_malformed_later_pages_duplicate_ids_refs_and_transport_fail_closed(self):
        malformed = [None, {}, "[]", [None], [{}], [entry(True)], [entry(0)],
                     [dict(entry(), tag_name="")], [dict(entry(), draft="false")],
                     [dict(entry(), prerelease=None)], [entry(i) for i in range(101)],
                     ValueError("404/auth/network")]
        for prefix in ([], [[entry(500)]]):
            for bad in malformed:
                api = API(prefix + [bad])
                with self.assertRaises(ValueError):
                    self.available(api)
                self.assertEqual(len(api.calls), len(prefix) + 1)
        for pages in ([[entry(), entry()]], [[entry()], [entry()]]):
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                self.available(API(pages))
        for bad in (None, {}, [None], [{}], [ref(kind="blob")], [ref(sha="short")],
                    [ref("vother")], [ref(TAG + "0"), ref(TAG + "0")]):
            with self.assertRaises(ValueError):
                self.available(API([[], bad]))
        for tag in ("v01.2.3", "v1.02.3", "v1.2", "1.2.3", "v1.2.3-rc", TAG + "\n", None):
            api = API([])
            with self.assertRaises(ValueError):
                self.available(api, tag)
            self.assertEqual(api.calls, [])

    def test_exact_remote_absence_and_malformed_advertisements(self):
        with patch.object(release.repository, "run", return_value="") as run:
            self.assertIsNone(release.remote_tag(TAG))
            self.assertEqual(run.call_args.args,
                             ("git", "ls-remote", "--refs", "origin", "refs/tags/" + TAG))
        for output in ("broken", SHA + "\trefs/tags/" + TAG + "0",
                       SHA + "\trefs/tags/" + TAG + "\n" + SHA + "\trefs/tags/" + TAG):
            with patch.object(release.repository, "run", return_value=output):
                with self.assertRaises(ValueError):
                    release.remote_tag(TAG)
        with patch.object(release.repository, "run", return_value=SHA + "\trefs/tags/" + TAG):
            with self.assertRaises(ValueError):
                release.available(API([[], []]), TAG)

    def test_strict_json_explicit_methods_payloads_and_no_retry(self):
        api = release.GitHub()
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, '{"id":7}', "")) as run:
            self.assertEqual(api.api("POST", BASE + "/releases", {"draft": False}), {"id": 7})
            self.assertEqual(run.call_args.args[0][:5],
                             ["gh", "api", "--method", "POST", BASE + "/releases"])
            self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"draft": False})
            api.api("POST", UPLOAD, asset=Path("HTML2PDF-3.2.1.zip"))
            self.assertIn("Content-Type: application/octet-stream", run.call_args.args[0])
        for code, output in ((1, "[]"), (0, "invalid"), (0, '{"id":1,"id":2}'),
                             (0, "[NaN]"), (0, "[Infinity]"), (0, "[1e999]")):
            with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], code, output, "offline failure")) as run:
                with self.assertRaises(ValueError):
                    api.api("GET", BASE + "/releases")
                self.assertEqual(run.call_count, 1)


GH_STUB = r'''#!PYTHON
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
method, endpoint = args[args.index("--method")+1], args[args.index("--method")+2]
payload = json.load(sys.stdin) if "--input" in args and args[args.index("--input")+1] == "-" else None
with open(os.environ["GH_LOG"], "a") as out:
    out.write(json.dumps({"method":method,"endpoint":endpoint,"payload":payload})+"\n")
state_path = pathlib.Path(os.environ["GH_STATE"])
state = json.loads(state_path.read_text())
mode = os.environ.get("GH_MODE", "")
repo = "miyako/4d-plugin-HTML2PDF"
upload = "https://uploads.github.com/repos/"+repo+"/releases/789/assets"
if not (endpoint.startswith("repos/"+repo+"/") or endpoint.startswith(upload+"?name=")):
    sys.exit("WRONG CANONICAL REPOSITORY: "+endpoint)
stage = ""
if method == "GET" and "/releases?" in endpoint:
    page = int(endpoint.rsplit("page=",1)[1])
    if mode == "later-error" and page == 2:
        sys.exit("HTTP 404")
    result = state.get("pages", [[]])[page-1] if page <= len(state.get("pages",[[]])) else []
elif method == "GET" and "/matching-refs/" in endpoint:
    result = state.get("refs", [])
elif method == "POST" and endpoint.endswith("/git/refs"):
    stage = "tag"
    if mode in ("same-tag-race", "different-tag-race"):
        state["tag"] = payload["sha"] if mode == "same-tag-race" else "b"*40
        state_path.write_text(json.dumps(state))
        if mode == "same-tag-race":
            subprocess.run(["git", "--git-dir", os.environ["GH_BARE_ORIGIN"],
                            "update-ref", payload["ref"], payload["sha"]], check=True)
        sys.exit("HTTP 422 occupied")
    state["tag"], state["tag_name"] = payload["sha"], payload["ref"]
    state_path.write_text(json.dumps(state))
    subprocess.run(["git", "--git-dir", os.environ["GH_BARE_ORIGIN"],
                    "update-ref", payload["ref"], payload["sha"]], check=True)
    if mode == "tag-error":
        sys.exit("HTTP 500 response lost")
    result = {"ref":payload["ref"],"object":{"sha":payload["sha"],"type":"commit"}}
elif method == "GET" and "/git/ref/tags/" in endpoint:
    stage = "verify"
    if mode == "verify-error":
        sys.exit("HTTP 403")
    result = {"ref":state["tag_name"],"object":{"sha":state["tag"],"type":"commit"}}
elif method == "POST" and endpoint.endswith("/releases"):
    stage = "release"
    state["release"] = payload
    state_path.write_text(json.dumps(state))
    if mode == "release-error":
        sys.exit("HTTP 422 response lost")
    result = dict(payload, id=1 if mode == "reused-id" else 789, upload_url=upload+"{?name,label}")
elif method == "POST" and endpoint.startswith(upload+"?name="):
    stage = "upload"
    path = pathlib.Path(args[args.index("--input")+1])
    state.setdefault("uploaded",[]).append(path.name)
    state_path.write_text(json.dumps(state))
    if mode == "upload-"+path.suffix[1:]:
        sys.exit("HTTP 500 response lost")
    result = {"id":45,"name":path.name.replace(" ","."),"size":path.stat().st_size,"state":"uploaded"}
else:
    sys.exit("UNSTUBBED API OPERATION: "+str(args))
if os.environ.get("GH_OVERRIDE_STAGE") == stage:
    result = json.loads(os.environ["GH_OVERRIDE_JSON"])
print(json.dumps(result))
'''


class PublicationCLITests(GitFixture):
    def setUp(self):
        super().setUp()
        self.version = source.read(self.local)
        self.tag = "v" + self.version
        self.output, self.state, self.log = (self.root / name for name in (
            "output", "state.json", "gh.jsonl"))
        self.state.write_text("{}")
        self.tools = self.root / "closed-path"
        self.tools.mkdir()
        for name in ("git", "git-upload-pack"):
            executable = shutil.which(name)
            if executable is None:
                executable = Path(subprocess.check_output(
                    ["git", "--exec-path"], text=True).strip()) / name
            (self.tools / name).symlink_to(executable)
        (self.tools / "python3").symlink_to(sys.executable)
        fake = self.tools / "gh"
        fake.write_text(GH_STUB.replace("PYTHON", sys.executable))
        fake.chmod(0o755)
        self.env.update(PATH=str(self.tools), GH_TOKEN="offline-fixture-token",
                        GITHUB_REPOSITORY=REPO, GITHUB_OUTPUT=str(self.output),
                        GH_STATE=str(self.state), GH_LOG=str(self.log),
                        GH_BARE_ORIGIN=str(self.bare))
        self.protected = (
            "HTML2PDF/HTML2PDF-4dplugin.cpp", "HTML2PDF/manifest.json",
            "HTML2PDF/constants.xlf", ".gitignore", "HTML2PDF/CMakeLists.txt",
            "HTML2PDF/Info.plist.in", "deps/litehtml/include/litehtml/pixel_type.h",
            str(native.CONTENTS / "Resources/other.dat"),
            str(native.CONTENTS / "QuickLook/Thumbnail.png"),
            str(native.CONTENTS / "MacOS/runtime.dylib"),
            "HTML2PDF/HTML2PDF-test/Plugins/Default/keep",
        )
        for name in self.protected:
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name == ".gitignore":
                path.write_bytes(b"ignored-source.cpp\nHTML2PDF/cmake-build/*\n")
            elif not path.exists():
                path.write_bytes(b"protected")
        self.generated = tuple(map(str, native.FILES))
        for name in self.generated:
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original generated output")
        self.git("add", "-f", ".")
        self.git("commit", "--quiet", "-m", "force-track actual generated native output paths")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        self.git("--git-dir=" + str(self.bare), "fetch", "--quiet", "--no-tags",
                 str(self.local), self.sha)
        self.baseline = {name: (self.local / name).read_bytes()
                         for name in self.protected + tuple(map(str, source.SOURCE_PATHS))}
        self.assertTrue(set(self.generated) <= set(self.git("ls-files").splitlines()))

    def command(self, name, *, mode="", assets=None, extra_env=None, windows=False):
        args = [name, "--sha", self.sha]
        if name == "publish":
            args.extend(release.asset_names(self.version) if assets is None else assets)
        env = {**self.env, "GH_MODE": mode, **(extra_env or {})}
        if windows:
            bootstrap = (
                "import os,runpy,sys;sys.dont_write_bytecode=True;"
                "sys.path.insert(0,'.github/scripts');import repository;"
                "repository.WINDOWS=True;"
                "from pathlib import Path;from types import SimpleNamespace;"
                "real=Path.lstat;"
                "Path.lstat=lambda p,*a,**k: "
                "SimpleNamespace(st_mode=real(p,*a,**k).st_mode,st_file_attributes=0x400) "
                "if os.environ.get('TEST_REPARSE') and p==Path('.github/scripts/native.sh') "
                "else real(p,*a,**k);"
                "sys.argv=['.github/scripts/release.py',*sys.argv[1:]];"
                "runpy.run_path('.github/scripts/release.py',run_name='__main__')"
            )
            return subprocess.run([sys.executable, "-c", bootstrap, *args], cwd=self.local,
                                  env=env, text=True, capture_output=True, timeout=60)
        return self.cli(".github/scripts/release.py", *args, env=env)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def reset_api(self, state=None):
        self.state.write_text(json.dumps(state or {}))
        self.log.unlink(missing_ok=True)
        self.git("--git-dir=" + str(self.bare), "update-ref", "-d", "refs/tags/" + self.tag)

    def build(self):
        data = {
            str(native.EXECUTABLE): b"fresh native executable",
            str(native.CONTENTS / "Info.plist"): plistlib.dumps({
                "CFBundleShortVersionString": self.version, "CFBundleVersion": "1.0",
                "CFBundleExecutable": "HTML2PDF", "CFBundleIdentifier": "com.4d.HTML2PDF",
                "CFBundlePackageType": "BNDL",
            }, fmt=plistlib.FMT_BINARY),
            str(native.MERGED): b"fresh Windows executable",
            str(native.DOWNLOAD): b"fresh Windows executable",
            str(native.CONTENTS / "_CodeSignature/CodeResources"): b"fresh signature bytes",
            "HTML2PDF/cmake-build/CMakeCache.txt": b"fresh CMake cache",
            "HTML2PDF/cmake-build/CMakeFiles/HTML2PDF.dir/pdf_container.cpp.o": b"fresh object",
            "HTML2PDF/cmake-build/litehtml/CMakeFiles/litehtml.dir/src/html.cpp.o": b"fresh dependency",
        }
        data.update({str(native.CONTENTS / "Resources" / name): self.baseline["HTML2PDF/" + name]
                     for name in native.RESOURCES})
        for name, raw in data.items():
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        for name in release.asset_names(self.version):
            (self.local / name).write_bytes(b"fresh package")
        return data

    def test_clean_preflight_then_tracked_generated_dirt_publication_retains_bytes(self):
        self.assertEqual(release.REPOSITORY, "miyako/4d-plugin-HTML2PDF")
        result = self.command("preflight")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), f"version={self.version}\ntag={self.tag}\n")
        expected = self.build()
        self.assertNotEqual(self.command("preflight").returncode, 0)
        self.reset_api()
        self.assertEqual(self.command("check").returncode, 0)
        result = self.command("publish")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        self.assertEqual([call["method"] for call in calls],
                         ["GET", "GET", "GET", "GET", "POST", "GET", "POST", "POST", "POST"])
        self.assertEqual(calls[4]["payload"]["sha"], self.sha)
        self.assertEqual(calls[6]["payload"], {
            "tag_name": self.tag, "name": self.tag, "target_commitish": self.sha,
            "draft": False, "prerelease": False, "body": "", "generate_release_notes": False,
        })
        self.assertTrue(all(call["endpoint"].startswith(UPLOAD + "?name=HTML2PDF-")
                            for call in calls[-2:]))
        self.assertEqual(self.git("rev-parse", "HEAD"), self.sha)
        self.assertTrue(self.git("status", "--porcelain"))
        for name, raw in {**self.baseline, **expected}.items():
            self.assertEqual((self.local / name).read_bytes(), raw)

    def test_every_final_leaf_missing_empty_directory_and_samebytes_symlink_before_api(self):
        expected = self.build()
        for relative in native.FILES:
            path = self.local / relative
            saved = path.read_bytes()
            for mutation in ("missing", "empty", "directory", "symlink"):
                with self.subTest(path=relative, mutation=mutation):
                    path.unlink()
                    if mutation == "empty":
                        path.write_bytes(b"")
                    elif mutation == "directory":
                        path.mkdir()
                    elif mutation == "symlink":
                        peer = self.root / "same-generated-bytes"
                        peer.write_bytes(saved)
                        path.symlink_to(peer)
                    result = self.command("publish")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(self.calls(), [], result.stderr)
                    if mutation == "directory":
                        path.rmdir()
                    elif path.exists() or path.is_symlink():
                        path.unlink()
                    path.write_bytes(saved)
        self.assertEqual(self.command("publish").returncode, 0)
        for name, raw in expected.items():
            self.assertEqual((self.local / name).read_bytes(), raw)

    def test_metadata_resources_and_windows_equality_rechecked_before_api(self):
        self.build()
        path = self.local / native.CONTENTS / "Info.plist"
        saved = path.read_bytes()
        metadata = plistlib.loads(saved)
        for change in ({"CFBundleShortVersionString": "900.800.700"},
                       {"CFBundleVersion": "9.0"}, {"CFBundleExecutable": "wrong"}):
            path.write_bytes(plistlib.dumps(dict(metadata, **change)))
            self.assertNotEqual(self.command("publish").returncode, 0)
            self.assertEqual(self.calls(), [])
        path.write_bytes(saved)
        for relative in (native.DOWNLOAD, native.MERGED,
                         *(native.CONTENTS / "Resources" / name for name in native.RESOURCES)):
            path = self.local / relative
            saved = path.read_bytes()
            path.write_bytes(b"late substitution")
            self.assertNotEqual(self.command("publish").returncode, 0)
            self.assertEqual(self.calls(), [])
            path.write_bytes(saved)
        self.assertEqual(self.command("publish").returncode, 0)

    def test_source_index_raw_hidden_flags_and_reversed_changes_fail_before_api(self):
        self.build()
        for name, raw in self.baseline.items():
            for stage in ("unstaged", "staged", "reversed", "assume-unchanged", "skip-worktree"):
                with self.subTest(path=name, stage=stage):
                    path = self.local / name
                    if stage in ("assume-unchanged", "skip-worktree"):
                        self.git("update-index", "--" + stage, "--", name)
                    path.write_bytes(raw + b" altered")
                    if stage in ("staged", "reversed"):
                        self.git("add", "--", name)
                    if stage == "reversed":
                        path.write_bytes(raw)
                    self.assertNotEqual(self.command("publish").returncode, 0)
                    self.assertEqual(self.calls(), [])
                    if stage in ("assume-unchanged", "skip-worktree"):
                        self.git("update-index", "--no-" + stage, "--", name)
                    path.write_bytes(raw)
                    self.git("add", "--", name)

    def test_initial_ignored_cache_rejected_final_cache_retained_unexpected_source_rejected(self):
        path = self.local / "HTML2PDF/cmake-build/CMakeCache.txt"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"stale initial cache")
        self.assertNotEqual(self.command("preflight").returncode, 0)
        self.assertEqual(self.calls(), [])
        path.unlink()
        expected = self.build()
        for name in (
            "ignored-source.cpp", "deps/litehtml/unexpected.cpp",
            "HTML2PDF/cmake-build-evil/CMakeCache.txt",
            "HTML2PDF/cmake-build/unexpected-source.cpp",
            "HTML2PDF/cmake-build/CMakeFiles/unexpected-source.cpp",
            "HTML2PDF/cmake-build/CMakeFiles/build.db-evil",
            "build/XCBuildData/build.db", "build/XCBuildData/unexpected-source.cpp",
            "build/XCBuildData/build.db-evil", "build/XCBuildData/evil.xcbuilddata/manifest.json",
            str(native.CONTENTS / "_CodeSignature/unexpected"),
        ):
            target = self.local / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"unexpected ignored/source output")
            self.assertNotEqual(self.command("publish").returncode, 0, name)
            self.assertEqual(self.calls(), [])
            target.unlink()
        self.assertEqual(self.command("publish").returncode, 0)
        self.assertEqual(path.read_bytes(), expected[str(path.relative_to(self.local))])

    def test_windows_simulated_executable_mode_only_raw_index_and_type_guards_remain(self):
        script = ".github/scripts/native.sh"
        path = self.local / script
        path.chmod(0o755)
        self.git("add", script)
        self.git("commit", "--quiet", "--allow-empty", "-m", "executable selected fixture")
        self.sha = self.git("rev-parse", "HEAD")
        self.env["GITHUB_SHA"] = self.sha
        self.git("config", "core.filemode", "false")
        self.assertTrue(self.git("ls-tree", self.sha, "--", script).startswith("100755 blob "))
        path.chmod(0o644)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertNotEqual(self.command("preflight").returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.command("preflight", windows=True).returncode, 0)
        self.reset_api()
        self.assertNotEqual(self.command(
            "preflight", windows=True, extra_env={"TEST_REPARSE": "1"}).returncode, 0)
        self.assertEqual(self.calls(), [])
        for final in (False, True):
            if final:
                self.build()
            for mutation in ("raw", "staged", "reversed", "index-mode", "symlink", "directory"):
                saved = path.read_bytes()
                if mutation == "index-mode":
                    self.git("update-index", "--chmod=-x", "--", script)
                elif mutation in ("symlink", "directory"):
                    path.unlink()
                    if mutation == "symlink":
                        peer = self.root / "same-executable"
                        peer.write_bytes(saved)
                        path.symlink_to(peer)
                    else:
                        path.mkdir()
                else:
                    path.write_bytes(saved + b"\n# altered\n")
                    if mutation in ("staged", "reversed"):
                        self.git("add", script)
                    if mutation == "reversed":
                        path.write_bytes(saved)
                result = self.command("publish" if final else "preflight", windows=True)
                self.assertNotEqual(result.returncode, 0, mutation)
                self.assertEqual(self.calls(), [])
                if mutation == "directory":
                    path.rmdir()
                elif mutation == "symlink":
                    path.unlink()
                path.write_bytes(saved)
                path.chmod(0o644)
                self.git("restore", "--staged", "--", script)

    def test_auth_canonical_identity_event_sha_and_head_fail_before_api(self):
        self.build()
        for env in ({"GH_TOKEN": ""}, {"GH_TOKEN": " ", "GITHUB_TOKEN": "ambient"},
                    {"GITHUB_REPOSITORY": "miyako/4d-plugin-html2pdf"},
                    {"GITHUB_REPOSITORY": "owner/other"}, {"GITHUB_SHA": "b" * 40}):
            self.assertNotEqual(self.command("publish", extra_env=env).returncode, 0)
            self.assertEqual(self.calls(), [])
        self.git("commit", "--quiet", "--allow-empty", "-m", "changed HEAD")
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_exact_asset_arguments_regular_nonempty_symlink_and_alias_rejection(self):
        self.build()
        names = release.asset_names(self.version)
        for assets in ([], names[:1], names + names[:1], list(reversed(names)),
                       [names[0], names[0]], ["./" + name for name in names],
                       [str(self.local / name) for name in names]):
            self.assertNotEqual(self.command("publish", assets=assets).returncode, 0)
            self.assertEqual(self.calls(), [])
        path = self.local / names[0]
        path.write_bytes(b"")
        self.assertNotEqual(self.command("publish").returncode, 0)
        path.unlink()
        path.symlink_to(names[1])
        self.assertNotEqual(self.command("publish").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_late_occupancy_and_later_page_errors_stop_before_posts(self):
        self.assertEqual(self.command("preflight").returncode, 0)
        self.build()
        for state, mode in (({"pages": [[entry(1, self.tag, True)], []]}, ""),
                            ({"refs": [ref(self.tag, self.sha)]}, ""),
                            ({"pages": [[entry(1)], []]}, "later-error")):
            self.reset_api(state)
            self.assertNotEqual(self.command("publish", mode=mode).returncode, 0)
            self.assertTrue(all(call["method"] == "GET" for call in self.calls()))

    def test_races_and_partial_failures_retain_state_without_retry_or_rollback(self):
        self.build()
        for mode, count, has_release in (
            ("same-tag-race", 3, False), ("different-tag-race", 3, False),
            ("tag-error", 3, False), ("verify-error", 4, False),
            ("release-error", 5, True), ("upload-zip", 6, True), ("upload-dmg", 7, True),
        ):
            self.reset_api()
            result = self.command("publish", mode=mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Manual recovery required", result.stderr)
            self.assertEqual(len(self.calls()), count)
            state = json.loads(self.state.read_text())
            self.assertIn("tag", state)
            self.assertEqual("release" in state, has_release)
            self.assertFalse(any(call["method"] in ("PATCH", "DELETE") for call in self.calls()))
            if mode == "upload-dmg":
                self.assertIn("release ID 789 retained", result.stderr)
                self.assertEqual(state["uploaded"][0], release.asset_names(self.version)[0])

    def test_reused_id_and_malformed_creation_verification_or_upload_retains_state(self):
        self.build()
        self.reset_api({"pages": [[entry(1)], []]})
        result = self.command("publish", mode="reused-id")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reused", result.stderr)
        self.assertFalse(any("/assets?name=" in call["endpoint"] for call in self.calls()))
        proper_ref = ref(self.tag, self.sha)
        proper_release = {
            "id": 789, "tag_name": self.tag, "name": self.tag,
            "target_commitish": self.sha, "draft": False, "prerelease": False,
            "body": "", "upload_url": UPLOAD + "{?name,label}",
        }
        name = release.asset_names(self.version)[0]
        proper_upload = {
            "id": 45, "name": name, "size": (self.local / name).stat().st_size, "state": "uploaded",
        }
        ref_variants = [None, [], {}, dict(proper_ref, ref="refs/tags/wrong"),
                        dict(proper_ref, object={"sha": self.sha, "type": "tag"})]
        release_variants = [None, [], {}, *(dict(proper_release, **{key: value})
                            for key, value in (("id", True), ("id", 0), ("id", "789"),
                                               ("tag_name", "v900.800.700"), ("name", "wrong"),
                                               ("target_commitish", "b" * 40), ("draft", True),
                                               ("draft", 0), ("prerelease", True),
                                               ("body", "unexpected notes"),
                                               ("upload_url", "https://invalid.example/assets")))]
        upload_variants = [None, [], {}, *(dict(proper_upload, **{key: value})
                           for key, value in (("id", True), ("id", 0), ("name", "wrong"),
                                              ("size", True), ("size", "13"), ("size", 0),
                                              ("state", "new")))]
        for stage, variants, count in (("tag", ref_variants, 3), ("verify", ref_variants, 4),
                                       ("release", release_variants, 5),
                                       ("upload", upload_variants, 6)):
            for value in variants:
                self.reset_api()
                result = self.command("publish", extra_env={
                    "GH_OVERRIDE_STAGE": stage, "GH_OVERRIDE_JSON": json.dumps(value),
                })
                self.assertNotEqual(result.returncode, 0, (stage, value))
                self.assertIn("Manual recovery required", result.stderr)
                self.assertEqual(len(self.calls()), count)
                self.assertFalse(any(call["method"] in ("PATCH", "DELETE") for call in self.calls()))
