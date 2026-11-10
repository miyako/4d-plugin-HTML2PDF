"""Static workflow contracts complement closed-PATH native execution tests."""

import re
import unittest

import yaml

from helper_support import ROOT, original


class WorkflowContractTests(unittest.TestCase):
    def test_exact_manual_build_and_independent_source_only_bump(self):
        release = (ROOT / ".github/workflows/release.yml").read_text()
        bump = (ROOT / ".github/workflows/bump-version.yml").read_text()
        self.assertTrue(release.startswith("name: Build\n"))
        trigger = release.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        for forbidden in ("inputs:", "push:", "pull_request:", "workflow_run:"):
            self.assertNotIn(forbidden, trigger)
        self.assertIn("default: patch", bump)
        self.assertIn("required: true", bump)
        self.assertEqual(re.findall(r"^      \w+:\s*$", bump.split("permissions:", 1)[0], re.M),
                         ["      mode:"])
        for mode in ("patch", "minor", "major"):
            self.assertIn("- " + mode, bump)
        for forbidden in ("git tag", "gh workflow", "workflow-dispatch", "release.py", "cmake"):
            self.assertNotIn(forbidden, bump)

    def test_every_checkout_immutable_and_unrelated_test_preserved(self):
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            jobs = yaml.safe_load(workflow.read_text())["jobs"]
            checkouts = [step for job in jobs.values() for step in job["steps"]
                         if step.get("uses", "").startswith("actions/checkout@")]
            self.assertTrue(checkouts, workflow)
            for step in checkouts:
                self.assertEqual(step["with"]["ref"], "${{ github.sha }}", workflow)
        original_test = yaml.safe_load(original(".github/workflows/test.yml"))
        actual_test = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
        # PyYAML represents YAML 1.1 'on' as True; compare complete semantics.
        self.assertEqual(actual_test[True], original_test[True])
        for name, job in original_test["jobs"].items():
            for step in job["steps"]:
                if step.get("uses", "").startswith("actions/checkout@"):
                    step.setdefault("with", {})["ref"] = "${{ github.sha }}"
                if "run" in step:
                    step["run"] = step["run"].replace(
                        '>> $GITHUB_OUTPUT', '>> "$GITHUB_OUTPUT"'
                    ).replace(
                        '--project=$(pwd)/HTML2PDF/HTML2PDF-test/Project/HTML2PDF.4DProject',
                        '--project="$(pwd)/HTML2PDF/HTML2PDF-test/Project/HTML2PDF.4DProject"',
                    )
        self.assertEqual(actual_test, original_test)

    def test_original_topology_early_preflight_and_poststaple_publication(self):
        text = (ROOT / ".github/workflows/release.yml").read_text()
        workflow = yaml.safe_load(text)
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"version", "build-windows", "build-macos"})
        self.assertEqual(jobs["build-windows"]["needs"], "version")
        self.assertEqual(jobs["build-macos"]["needs"], ["version", "build-windows"])
        self.assertEqual(jobs["build-windows"]["runs-on"], "windows-latest")
        self.assertEqual(jobs["build-macos"]["runs-on"], "macos-latest")
        self.assertEqual(workflow["env"]["MACOS_DEPLOYMENT_TARGET"], "10.13")
        self.assertEqual(workflow["concurrency"],
                         {"group": "html2pdf-publication", "cancel-in-progress": False})
        for job in jobs.values():
            run = [step for step in job["steps"] if "run" in step]
            self.assertIn("release.py preflight", run[0]["run"])
            self.assertEqual(run[0]["env"]["GH_TOKEN"], "${{ github.token }}")
        mac = [step for step in jobs["build-macos"]["steps"] if "run" in step]
        self.assertIn("native.sh package", mac[-2]["run"])
        self.assertIn("release.py publish", mac[-1]["run"])
        for secret in ("APPLE_DEVELOPER_ID_CERTIFICATE", "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD",
                       "KEYCHAIN_PASSWORD", "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID",
                       "NOTARYTOOL_PASSWORD"):
            self.assertIn("secrets." + secret, text)
        self.assertNotIn("softprops", text)
        self.assertNotIn("if: github.ref", text)

    def test_scoped_autocrlf_environment_precedes_all_build_checkouts(self):
        text = (ROOT / ".github/workflows/release.yml").read_text()
        environment = yaml.safe_load(text)["env"]
        self.assertEqual(environment["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(environment["GIT_CONFIG_KEY_0"], "core.autocrlf")
        self.assertEqual(environment["GIT_CONFIG_VALUE_0"], "false")
        self.assertNotIn("git config --global", text)
        self.assertEqual(text.count("submodules: recursive"), 3)

    def test_cmake_only_source_short_repair_and_independent_build(self):
        expected = original("HTML2PDF/CMakeLists.txt").replace(
            b"project(${PLUGIN_NAME} LANGUAGES C CXX)\n",
            b'project(${PLUGIN_NAME} LANGUAGES C CXX)\n\n'
            b'file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" PLUGIN_VERSION LIMIT_COUNT 1)\n',
            1,
        ).replace(
            b'MACOSX_BUNDLE_SHORT_VERSION_STRING "1.0"',
            b'MACOSX_BUNDLE_SHORT_VERSION_STRING "${PLUGIN_VERSION}"',
            1,
        )
        self.assertEqual((ROOT / "HTML2PDF/CMakeLists.txt").read_bytes(), expected)
        self.assertEqual((ROOT / "HTML2PDF/Info.plist.in").read_bytes(),
                         original("HTML2PDF/Info.plist.in"))
        text = (ROOT / "HTML2PDF/CMakeLists.txt").read_text()
        for policy in (
            'MACOSX_BUNDLE_BUNDLE_VERSION "1.0"',
            'MACOSX_BUNDLE_SHORT_VERSION_STRING "${PLUGIN_VERSION}"',
            'file(STRINGS "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" PLUGIN_VERSION LIMIT_COUNT 1)',
            'set(BUILD_SHARED_LIBS OFF', 'find_library(COREGRAPHICS_FRAMEWORK CoreGraphics REQUIRED)',
            'target_link_libraries(${PLUGIN_NAME} PRIVATE ${COREGRAPHICS_FRAMEWORK} litehtml hpdf)',
            'set(PNG_LIBRARY "${PNG_DIR}/libpng16.a"',
            'file(WRITE "${LITEHTML_DIR}/include/litehtml/pixel_type.h"',
        ):
            self.assertIn(policy, text)
