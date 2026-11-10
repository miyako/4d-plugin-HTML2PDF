"""Selective CMake cleanup, immutable Windows build copy, and package validation."""

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import stat
import subprocess

import repository
import source_version
import version_model


ROOT = Path(__file__).resolve().parents[2]
PRODUCT = "HTML2PDF"
BASE = Path("HTML2PDF/HTML2PDF-test/Plugins")
BUNDLE = BASE / "HTML2PDF.bundle"
CONTENTS = BUNDLE / "Contents"
EXECUTABLE = CONTENTS / "MacOS/HTML2PDF"
WINDOWS = BASE / "HTML2PDF/Contents/Windows64/HTML2PDF.4DX"
MERGED = CONTENTS / "Windows64/HTML2PDF.4DX"
DOWNLOAD = Path("winbuild/HTML2PDF.4DX")
RESOURCES = ("manifest.json", "constants.xlf")
FILES = (
    EXECUTABLE, CONTENTS / "Info.plist",
    *(CONTENTS / "Resources" / name for name in RESOURCES),
    MERGED, CONTENTS / "_CodeSignature/CodeResources", DOWNLOAD,
)
BUILD = Path("HTML2PDF/cmake-build")
COPY = BUILD / "source"
WINDOWS_BUILD = BUILD / "windows"
COPY_WINDOWS = COPY / WINDOWS
DIRECTORIES = (BUILD,)
PIXEL = Path("deps/litehtml/include/litehtml/pixel_type.h")


def generated(path):
    value = str(path)
    if "\\" in value or PurePosixPath(value).as_posix() != value \
            or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts:
        return False
    path = Path(value)
    if path in FILES:
        return True
    if not path.is_relative_to(BUILD):
        return False
    relative = path.relative_to(BUILD).as_posix()
    if relative in {
        "CMakeCache.txt", "Makefile", "cmake_install.cmake", "compile_commands.json",
        "litehtml/Makefile", "litehtml/cmake_install.cmake", "litehtml/liblitehtml.a",
        "litehtml/src/gumbo/Makefile", "litehtml/src/gumbo/cmake_install.cmake",
        "litehtml/src/gumbo/libgumbo.a",
        "libharu/include/Makefile", "libharu/include/cmake_install.cmake",
        "libharu/include/include/hpdf_config.h",
        "libharu/include/src/Makefile", "libharu/include/src/cmake_install.cmake",
        "libharu/include/src/libhpdf.a",
        "CMakeFiles/HTML2PDF.dir/Info.plist",
    }:
        return True
    if re.fullmatch(r"(?:litehtml|litehtml/src/gumbo)/CMakeFiles/Export/"
                    r"[0-9a-f]{32}/(?:litehtmlTargets|gumboConfig)(?:-release)?\.cmake",
                    relative):
        return True
    if not (relative.startswith("CMakeFiles/") or "/CMakeFiles/" in relative):
        return False
    leaf = path.name
    if leaf in {
        "cmake.check_cache", "Makefile2", "Makefile.cmake", "TargetDirectories.txt",
        "progress.marks", "CMakeDirectoryInformation.cmake", "CMakeConfigureLog.yaml",
        "CMakeOutput.log", "CMakeError.log", "InstallScripts.json",
        "CMakeCCompiler.cmake", "CMakeCXXCompiler.cmake", "CMakeSystem.cmake",
        "CMakeDetermineCompilerABI_C.bin", "CMakeDetermineCompilerABI_CXX.bin",
        "CMakeCCompilerId.c", "CMakeCXXCompilerId.cpp", "a.out",
        "build.make", "cmake_clean.cmake", "cmake_clean_target.cmake",
        "compiler_depend.make", "compiler_depend.ts", "compiler_depend.internal",
        "depend.make", "flags.make", "link.txt", "progress.make", "DependInfo.cmake",
    }:
        return True
    return bool(re.fullmatch(r".+\.(?:o|o\.d|obj|bin)", leaf))


def regular(path, root=ROOT):
    root = Path(root)
    path = Path(path)
    relative = path.relative_to(root) if path.is_absolute() else path
    if ".." in relative.parts:
        raise ValueError(f"Native path escapes checkout: {path}")
    current = root
    for candidate in (root, *(root / Path(*relative.parts[:i])
                              for i in range(1, len(relative.parts) + 1))):
        current = candidate
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Refusing symlink/reparse native path: {candidate}")
        if not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
            raise ValueError(f"Unsupported native path type: {candidate}")
    return current


def validate_paths(paths, root=Path(".")):
    for relative in paths:
        path = regular(relative, root)
        if path.is_dir():
            for descendant in path.rglob("*"):
                regular(descendant, root)


def require_file(path, root=Path(".")):
    path = regular(path, root)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty native leaf: {path}")
    return path


def clean(platform, root=ROOT):
    root = Path(root)
    source_version.read(root)
    paths = [BUILD]
    if platform == "macos":
        paths += [EXECUTABLE, CONTENTS / "Info.plist",
                  CONTENTS / "_CodeSignature/CodeResources"]
        paths += [CONTENTS / "Resources" / name for name in RESOURCES]
    elif platform != "windows":
        raise ValueError("Unknown native platform")
    validate_paths(paths, root)
    for relative in paths:
        path = root / relative
        if path.exists() and (path.is_dir() if relative != BUILD else not path.is_dir()):
            raise ValueError(f"Unexpected cleanup input/output type: {path}")
    for relative in paths:
        path = root / relative
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def verify_resources(root=Path(".")):
    for name in RESOURCES:
        source = require_file(Path(PRODUCT) / name, root)
        target = require_file(CONTENTS / "Resources" / name, root)
        if source.read_bytes() != target.read_bytes():
            raise ValueError(f"Copied resource differs from exact source: {name}")


def validate(root=Path(".")):
    version = source_version.read(root)
    path = require_file(CONTENTS / "Info.plist", root)
    metadata = plistlib.loads(path.read_bytes())
    expected = {
        "CFBundleShortVersionString": version,
        "CFBundleExecutable": PRODUCT, "CFBundleIdentifier": "com.4d.HTML2PDF",
        "CFBundlePackageType": "BNDL",
    }
    if version_model.has_build_key(root):
        expected["CFBundleVersion"] = "1.0"
    elif isinstance(metadata, dict) and "CFBundleVersion" in metadata:
        raise ValueError("Built metadata invented an absent source build key")
    if not isinstance(metadata, dict) or any(metadata.get(key) != value
                                            for key, value in expected.items()):
        raise ValueError("Built metadata differs from source short/independent build policy")
    for path in (EXECUTABLE, MERGED):
        require_file(path, root)
    verify_resources(root)
    return version


def validate_final(root=Path(".")):
    validate_paths((*FILES, *DIRECTORIES), root)
    version = validate(root)
    for path in FILES:
        require_file(path, root)
    if (Path(root) / DOWNLOAD).read_bytes() != (Path(root) / MERGED).read_bytes():
        raise ValueError("Merged Windows bytes differ from exact downloaded artifact")
    return version


def merge_windows(root=Path(".")):
    validate_paths((DOWNLOAD, MERGED), root)
    source = require_file(DOWNLOAD, root)
    target = regular(MERGED, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    validate(root)


def architectures(output):
    if not {"arm64", "x86_64"} <= set(output.strip().split()):
        raise ValueError("Executable requires exact arm64 and x86_64 architecture tokens")


def windows_copy(sha):
    """Materialize explicit committed blobs, never archives or worktree source bytes."""
    repository.verify_checkout(sha)
    clean("windows", Path("."))
    entries = repository.entries(repository.run("git", "ls-tree", "-r", "-z", sha, "--"))
    inputs = {
        path: entry for path, entry in entries.items()
        if (path == "VERSION" or Path(path).parts[0] in ("HTML2PDF", "deps", "4D-Plugin-SDK"))
        and not Path(path).is_relative_to(BASE)
        and not Path(path).is_relative_to(BUILD)
    }
    for path, (mode, _) in inputs.items():
        if mode not in ("100644", "100755"):
            raise ValueError(f"Windows build copy requires regular committed blobs: {path}")
    if "VERSION" not in inputs or str(PIXEL) not in inputs:
        raise ValueError("Missing selected Windows build inputs")
    for path, (mode, oid) in inputs.items():
        destination = regular(COPY / path, Path("."))
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = subprocess.check_output(["git", "cat-file", "blob", oid])
        destination.write_bytes(data)
        destination.chmod(0o755 if mode == "100755" else 0o644)
    verify_copy(inputs)
    return inputs


def verify_copy(inputs, *, patched=False):
    validate_paths((COPY,))
    for path, (mode, oid) in inputs.items():
        actual_mode, actual_oid = repository.actual_blob(COPY / path)
        if repository.WINDOWS and actual_mode in ("100644", "100755"):
            actual_mode = mode
        allowed = {oid}
        if patched and Path(path) == PIXEL:
            data = subprocess.check_output(["git", "cat-file", "blob", oid])
            for operator in ("==", "!=", "<", ">", "<=", ">="):
                data = data.replace(("constexpr bool operator" + operator).encode(),
                                    ("inline bool operator" + operator).encode())
            allowed.add(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest())
        if actual_mode != mode or actual_oid not in allowed:
            raise ValueError(f"Unexpected Windows build copy mutation: {path}")


def build_windows(sha):
    inputs = windows_copy(sha)
    subprocess.run(["cmake", "-S", str(COPY / PRODUCT), "-B", str(WINDOWS_BUILD),
                    "-A", "x64"], check=True)
    subprocess.run(["cmake", "--build", str(WINDOWS_BUILD), "--config", "Release"], check=True)
    require_file(COPY_WINDOWS)
    validate_paths((BUILD,))
    # CMake's existing MSVC workaround may alter exactly this copy, never the source.
    verify_copy(inputs, patched=True)
    allowed = {str(COPY / path) for path in inputs}
    for name in (*RESOURCES,):
        path = COPY / WINDOWS.parents[1] / "Resources" / name
        require_file(path)
        if path.read_bytes() != (COPY / PRODUCT / name).read_bytes():
            raise ValueError(f"Windows copied resource differs from source: {name}")
        allowed.add(str(path))
    allowed.add(str(COPY_WINDOWS))
    # Inspect original selected/index/raw bytes again; only this isolated build tree is new.
    repository.verify_checkout(sha, final=True, generated=lambda path: (
        path in allowed or Path(path).is_relative_to(WINDOWS_BUILD)
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(
        "clean-macos", "clean-windows", "build-windows", "merge-windows",
        "validate", "architectures",
    ))
    args = parser.parse_args()
    if args.command.startswith("clean-"):
        clean(args.command[6:], Path("."))
    elif args.command == "build-windows":
        build_windows(os.environ["GITHUB_SHA"])
    elif args.command == "merge-windows":
        merge_windows()
    elif args.command == "validate":
        validate_final()
    else:
        path = require_file(EXECUTABLE)
        result = subprocess.run(["lipo", "-archs", str(path)], check=True,
                                text=True, capture_output=True)
        architectures(result.stdout)


if __name__ == "__main__":
    main()
