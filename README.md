# HTML2PDF

A 4D plugin that converts HTML files to PDF using [litehtml](https://github.com/nicehash/litehtml) for HTML/CSS rendering and [libharu](https://github.com/libharu/libharu) for PDF generation.

## Requirements

- 4D v21.1 or later

## Installation

Download the latest release from the [Releases](../../releases) page.

### macOS & Windows (single download)

1. Download the `.zip` from the release
2. Extract to get the `HTML2PDF.bundle` folder
3. Copy the `.bundle` into your 4D application's **Plugins** folder (or your database's **Plugins** folder)
4. Restart 4D

### macOS only (notarized DMG)

1. Download the `.dmg` from the release
2. Mount it and copy the `.bundle` into your **Plugins** folder
3. Restart 4D

## Commands

### `HTML2PDF`

```4d
$status:=HTML2PDF($htmlPath; $pdfPath)
```

| Parameter | Type | Description |
|---|---|---|
| `$htmlPath` | Text | POSIX path to the input HTML file |
| `$pdfPath` | Text | POSIX path for the output PDF file |
| `$status` | Longint | `0` on success, non-zero on error |

**Example:**

```4d
var $status : Integer
$status:=HTML2PDF("/Users/me/email.html"; "/Users/me/email.pdf")
ASSERT($status=0; "Conversion failed with status: "+String($status))
```

> **Note:** On macOS, 4D's `Get 4D folder()` returns HFS-style paths (`:` separator). Convert them before passing to this plugin:
> ```4d
> $posixPath:=Convert path system to POSIX(Get 4D folder(Current resources folder))+"file.html"
> ```

## Building from Source

### Prerequisites

- CMake 3.20+
- Xcode (macOS) or Visual Studio 2022+ (Windows)

### Clone

```bash
git clone --recurse-submodules https://github.com/{owner}/html2pdf-plugin.git
cd html2pdf-plugin
```

### Build (macOS)

```bash
cd HTML2PDF
mkdir -p cmake-build && cd cmake-build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build .
```

### Build (Windows)

```pwsh
cd HTML2PDF
mkdir cmake-build; cd cmake-build
cmake .. -A x64
cmake --build . --config Release
```

### Run Tests

Requires [tool4d](https://developer.4d.com/docs/Admin/cli/) (free, no license needed):

**macOS:**
```bash
tool4d.app/Contents/MacOS/tool4d --dataless --startup-method=test_all \
  --project=$(pwd)/HTML2PDF/HTML2PDF-test/Project/HTML2PDF.4DProject
```

**Windows:**
```pwsh
./tool4d/tool4d.exe --dataless --startup-method=test_all `
  --project="$((Get-Location).Path)\HTML2PDF\HTML2PDF-test\Project\HTML2PDF.4DProject"
```

## CI/CD

This project includes three GitHub Actions workflows:

| Workflow | Trigger | Description |
|---|---|---|
| `test.yml` | Tag push / manual | Builds and tests on macOS + Windows |
| `bump-version.yml` | Manual | Bumps `VERSION`, commits, and pushes a `vX.Y.Z` tag |
| `release.yml` | `v*.*.*` tag | Builds universal binary, codesigns, notarizes, publishes release |

### Required Secrets (for `release.yml` only)

| Secret | Description |
|---|---|
| `APPLE_DEVELOPER_ID_CERTIFICATE` | Base64-encoded `.p12` Developer ID Application certificate |
| `APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD` | Password for the `.p12` file |
| `KEYCHAIN_PASSWORD` | Arbitrary password for the CI keychain |
| `NOTARYTOOL_APPLE_ID` | Apple ID email for notarization |
| `NOTARYTOOL_TEAM_ID` | Apple Developer Team ID |
| `NOTARYTOOL_PASSWORD` | App-specific password from [appleid.apple.com](https://appleid.apple.com) |

## Dependencies

- [4D Plugin SDK](https://github.com/4d/4D-Plugin-SDK) — 4D plugin interface
- [litehtml](https://github.com/nicehash/litehtml) — HTML/CSS rendering engine
- [libharu](https://github.com/libharu/libharu) — PDF generation library

## License

MIT
