# Manual source versioning and publication

The two independent release workflows are **Bump** and **Build**.

* **Bump** accepts one required `patch`/`minor`/`major` choice (default `patch`).
  It changes only `VERSION`, commits one direct child of the selected source
  commit and pushes only that branch. It does not create tags, publish releases,
  invoke native tools or dispatch Build. The committed executable pre-push guard
  is checked before edits and again immediately before push.
* **Build** has no custom inputs. Select the intended ref using GitHub's built-in
  selector. Every checkout uses the immutable event `github.sha`; no default-only
  branch restriction is added. `VERSION` is the sole canonical `X.Y.Z` release
  authority. CMake's short version derives from selected `VERSION`; its independent
  build version remains **1.0**, including after a Bump. The built bundle is
  checked against that policy, preserving an absent optional build key.

Build has a repository-wide publication concurrency group with cancellation
disabled. This serializes publication across refs; GitHub does not promise FIFO
ordering. The unrelated `test.yml` retains its original tag-only and manual
triggers and 4D test policy; its checkouts are also SHA-pinned.

At migration intake, source `VERSION` is **1.0.9**, and `v1.0.9` is already
published. Build therefore stops at its early availability check, before native
or credential work. Run the separate source-only Bump first to select an
unpublished version, then manually run Build on that commit. The migration does
not increment source version. The narrow CMake repair reads selected `VERSION`
into `PLUGIN_VERSION` and uses it only for the short version; the independent
build version remains **1.0** and the source Info.plist template is unchanged.

## Reviewed provenance

The native/publication implementation adapts immutable, raw-Git-blob-verified
helpers, workflows and regression tests from:

* [`4d-plugin-RTF2TEXT@4a8c89677515cd5c71c162e0b296e63bee374cdd`](https://github.com/miyako/4d-plugin-RTF2TEXT/tree/4a8c89677515cd5c71c162e0b296e63bee374cdd):
  final packaged-leaf validation, Windows merge equality and closed-PATH native
  regression patterns.
* [`4d-plugin-libarchive@9547d09522fc422ddd754fb088165b3d1d1d3073`](https://github.com/miyako/4d-plugin-libarchive/tree/9547d09522fc422ddd754fb088165b3d1d1d3073):
  CMake layout, selective cleanup, independent metadata and create-only
  publication patterns.
* [`4d-plugin-stomp@ab9f5e51dba5b8b6ec1a1b70e191082fcb73fb41`](https://github.com/miyako/4d-plugin-stomp/tree/ab9f5e51dba5b8b6ec1a1b70e191082fcb73fb41):
  final resource/Windows checks, reparse-point rejection and Windows checkout
  conversion/mode regressions.

UTI's canonical case-sensitive identity checks and serial's exact copied-resource
checks were also reviewed. Repository-specific topology, source authority and
generated paths are derived from HTML2PDF, not copied from another product.
The complete sixteen-reference manifest, immutable commits and raw blob hashes
are retained in the migration session's `references/manifest.json` artifact.

## Preserved native topology

The version job validates selected source and checks publication absence before
either platform starts. Each platform repeats preflight before native work;
macOS does so before artifact download or credential import. `GH_TOKEN` must be
explicit and nonempty. The repository identity is exactly
`miyako/4d-plugin-HTML2PDF`, including case.

* Windows uses the existing CMake **Release x64** configuration. Its CMake
  project retains the vendored `pixel_type.h` patch to work around MSVC's
  `constexpr std::abs` rejection. To retain that workaround without changing
  immutable checked-out source, `native.py build-windows` materializes explicit
  regular-file blobs, including the authoritative `VERSION`, from the selected Git tree into
  `HTML2PDF/cmake-build/source`. It does not extract an archive, follow a
  worktree source symlink, clone a dependency, or copy stale packaged outputs.
  CMake runs with source `.../source/HTML2PDF` and binary tree
  `HTML2PDF/cmake-build/windows`. The helper rehashes copied input bytes against
  selected Git blobs before configuration, then checks them again after build.
  It permits only the existing exact operator replacements in the copied header, checks
  copied resources and revalidates the original HEAD/index/raw source. The
  uploaded `.4DX` is the exact CMake output inside that copy, not a recursive
  first match. A previous build copy fails initial preflight; it is never
  silently accepted as a fresh build.
* macOS builds the CMake project, with only the source short-version repair, at
  `HTML2PDF/cmake-build`, with `Release`, `arm64;x86_64`, and deployment target
  **10.13**. CoreGraphics and vendored static libpng/hpdf/litehtml are unchanged.
  `lipo -archs` must contain the exact `arm64` and `x86_64` tokens; no new
  architecture or runtime-library exclusion is invented.
* The package remains
  `HTML2PDF/HTML2PDF-test/Plugins/HTML2PDF.bundle`. Only known generated leaves
  and the exact CMake intermediate tree are cleaned after symlink/reparse/type
  prevalidation; no entire bundle, Default sibling, or source resource is
  deleted. Cleanup failures are fatal.
* The downloaded Windows binary is merged into `Contents/Windows64`. Before
  publication, it must still byte-match the downloaded artifact.

Checkout conversion is disabled using inherited, workflow-scoped Git
`core.autocrlf=false` before all Build checkouts. Windows may represent selected
regular-file executable bits differently; selected/index modes and raw blob
hashes still must match. Symlink/reparse/type differences are never normalized.
There are no Git submodule links in this repository despite `.gitmodules`.

## Validation and publication protocol

Initial checkout validation requires a globally clean checkout, including ignored
files. Final validation instead retains actual rebuilt tracked outputs: it
separately protects immutable HEAD, index entries/modes, raw nongenerated bytes,
hidden index/stat flags, and unexpected untracked/ignored files. Only exact
packaged generated leaves and classified CMake intermediates are exempted.
Arbitrary CMake source files, other bundles and XCBuildData are not exempted.

Unsigned merge validation does not require a signature. Final publication
requires every packaged generated leaf (including the macOS executable,
signature, Info.plist, resources and Windows binary) and downloaded binary to be
a **nonempty regular nonsymlink file**. Built XML/binary plist metadata, exact
source `manifest.json`/`constants.xlf` copies and merged Windows equality are
rechecked. ZIP/DMG arguments must be the exact ordered, unqualified
`HTML2PDF-X.Y.Z.zip` and `HTML2PDF-X.Y.Z.dmg` paths.

The original certificate/keychain and notary credential secrets are unchanged.
Signing requires a nonempty Developer ID identity and deep strict verification.
Each notary submission must both exit successfully and return strict JSON with
`status: Accepted`. Both packages are submitted; the DMG is stapled and strict
signing validation runs again. Publication is the final step after all of this.

Early and final availability checks enumerate draft-inclusive release pages
**through an empty page**, check exact API tag refs and exact `git ls-remote`
tag absence. Duplicate JSON keys, nonfinite numbers, malformed schemas, later-page
errors, authentication failures and network errors stop publication.

Publication uses separate create-only API calls:

1. POST a new `refs/tags/vX.Y.Z` at the selected SHA; verify API and advertised
   remote tag equality. An occupied tag fails even if it points to the same SHA.
2. POST a new public, non-prerelease release with explicit tag/name/target,
   preserving the original **empty body and disabled generated notes**.
   The positive integer release ID must not belong to an existing release.
3. Upload only the exact ZIP/DMG to that new ID. Verify returned names, integer
   sizes and `uploaded` state.

There is **no update, overwrite, clobber, deletion, rollback or automatic retry**.
Failures retain partial tags, releases and assets. Inspect the error's retained
state and verify the remote state before manual recovery; do not simply rerun
Build against an occupied version. Offline tests execute actual helper/scripts
with local Git and closed-PATH native/credential/API stubs only. They do not prove
hosted toolchain, signing, notarization or 4D service behavior.
