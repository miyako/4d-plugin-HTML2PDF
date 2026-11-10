"""VERSION is the release authority; CMake's independent build stays unchanged."""

import codecs
import re
from pathlib import Path
import xml.etree.ElementTree as ET


VERSION_PATH = "VERSION"
CMAKE_PATH = "HTML2PDF/CMakeLists.txt"
PLIST_PATH = "HTML2PDF/Info.plist.in"
SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def decode(raw):
    for bom, encoding in (
        (codecs.BOM_UTF8, "utf-8"),
        (codecs.BOM_UTF16_LE, "utf-16-le"),
        (codecs.BOM_UTF16_BE, "utf-16-be"),
    ):
        if raw.startswith(bom):
            return raw[len(bom):].decode(encoding), encoding, bom
    encoding = "utf-8"
    if b"\0" in raw:
        encoding = "utf-16-be" if raw[0] == 0 else "utf-16-le"
    return raw.decode(encoding), encoding, b""


def canonical(value):
    if not SEMVER.fullmatch(value):
        raise ValueError(f"not a canonical X.Y.Z version: {value!r}")
    return value


def cmake_tokens(text):
    # Discard both CMake comment forms, without treating quoted '#' as comments.
    token = re.compile(
        r"#\[(=*)\[.*?\]\1\]|#[^\r\n]*|"
        r'"(?:\\.|[^"\\])*"|[()]|[^\s()"]+',
        re.DOTALL,
    )
    return [
        item.group()[1:-1] if item.group().startswith('"') else item.group()
        for item in token.finditer(text)
        if not item.group().startswith("#")
    ]


def plist_dictionary(root):
    try:
        plist = ET.fromstring(decode((Path(root) / PLIST_PATH).read_bytes())[0])
    except ET.ParseError as error:
        raise ValueError(f"invalid source plist: {error}") from error
    children = list(plist)
    if plist.tag != "plist" or len(children) != 1 or children[0].tag != "dict":
        raise ValueError("source plist must contain exactly one dictionary")
    return children[0]


def read(root=Path(".")):
    root = Path(root)
    text, _, _ = decode((root / VERSION_PATH).read_bytes())
    match = re.fullmatch(r"([0-9]+\.[0-9]+\.[0-9]+)(\r\n|\r|\n)?", text)
    if not match:
        raise ValueError("VERSION must contain exactly one canonical version")
    version = canonical(match[1])
    tokens = cmake_tokens(decode((root / CMAKE_PATH).read_bytes())[0])
    commands = []
    start = 0
    while start < len(tokens):
        if start + 1 >= len(tokens) or tokens[start + 1] != "(":
            raise ValueError("invalid CMake command")
        end, depth = start + 2, 1
        while end < len(tokens) and depth:
            depth += (tokens[end] == "(") - (tokens[end] == ")")
            end += 1
        if depth:
            raise ValueError("unclosed CMake command")
        commands.append((tokens[start].lower(), tokens[start + 2:end - 1]))
        start = end
    properties = []
    version_keys = {
        "MACOSX_BUNDLE_SHORT_VERSION_STRING", "MACOSX_BUNDLE_BUNDLE_VERSION",
        "MACOSX_BUNDLE_INFO_PLIST",
    }
    for name, args in commands:
        if name == "set_target_properties" and "PROPERTIES" in args:
            values = args[args.index("PROPERTIES") + 1:]
            if len(values) % 2:
                raise ValueError("unpaired CMake target property")
            pairs = list(zip(values[::2], values[1::2]))
            if any(key in version_keys for key, _ in pairs) and \
                    args[:args.index("PROPERTIES")] != ["${PLUGIN_NAME}"]:
                raise ValueError("unexpected CMake version target")
            properties += pairs
        elif name == "set_property" and "PROPERTY" in args:
            values = args[args.index("PROPERTY") + 1:]
            if values and values[0] in version_keys:
                raise ValueError("unexpected CMake version property override")
    plugin_names = [args for name, args in commands
                    if name == "set" and args and args[0] == "PLUGIN_NAME"]
    if plugin_names != [["PLUGIN_NAME", "HTML2PDF", "CACHE", "STRING", "Plugin name"]]:
        raise ValueError("missing, duplicate or drifting CMake plugin name")
    for key, expected in (
        ("MACOSX_BUNDLE_SHORT_VERSION_STRING", "${PLUGIN_VERSION}"),
        ("MACOSX_BUNDLE_BUNDLE_VERSION", "1.0"),
        ("MACOSX_BUNDLE_INFO_PLIST", "${CMAKE_SOURCE_DIR}/Info.plist.in"),
    ):
        values = [value for name, value in properties if name == key]
        if values != [expected]:
            raise ValueError(f"missing, duplicate or drifting CMake {key}")
    command = [
        "file", "(", "STRINGS", "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION",
        "PLUGIN_VERSION", "LIMIT_COUNT", "1", ")",
    ]
    if sum(tokens[i:i + len(command)] == command for i in range(len(tokens))) != 1:
        raise ValueError("CMake must read the authoritative VERSION exactly once")
    if any(name == "set" and args and args[0] == "PLUGIN_VERSION" for name, args in commands):
        raise ValueError("CMake must not override PLUGIN_VERSION")
    elements = list(plist_dictionary(root))
    if len(elements) % 2:
        raise ValueError("invalid plist dictionary")
    for key, expected in (
        ("CFBundleShortVersionString", "${MACOSX_BUNDLE_SHORT_VERSION_STRING}"),
        ("CFBundleVersion", "${MACOSX_BUNDLE_BUNDLE_VERSION}"),
    ):
        values = [value.text for item, value in zip(elements[::2], elements[1::2])
                  if item.tag == "key" and item.text == key and value.tag == "string"]
        keys = [item for item in elements[::2] if item.text == key]
        if key == "CFBundleVersion" and not keys:
            continue
        if len(keys) != 1 or values != [expected]:
            raise ValueError(f"missing, duplicate or drifting plist {key}")
    return version


def bump(root, mode):
    version = read(root)
    major, minor, patch = map(int, version.split("."))
    if mode == "patch":
        patch += 1
    elif mode == "minor":
        minor, patch = minor + 1, 0
    elif mode == "major":
        major, minor, patch = major + 1, 0, 0
    else:
        raise ValueError("mode must be patch, minor or major")
    new = f"{major}.{minor}.{patch}"
    path = Path(root) / VERSION_PATH
    text, encoding, bom = decode(path.read_bytes())
    path.write_bytes(bom + text.replace(version, new, 1).encode(encoding))
    return new


def has_build_key(root):
    return any(item.text == "CFBundleVersion" for item in plist_dictionary(root).findall("key"))
