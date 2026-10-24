# Isolated unsigned NSIS extraction adapter

This adapter selects the existing `UninstallerReader` implementation shipped by
`app-builder-lib` 26.15.3 for the local Linux build. The installed builder already
uses that implementation for its Catalina workaround. The exact implementation
hash is pinned. No product file, installed dependency, or release workflow is
modified.

The Wine 1.0.1 bundle lacked PE builtins. Complete, signed WineHQ 11 packages
could run a 64-bit built-in command locally, but both the PE32 NSIS intermediate
and PE32 command crashed in WoW64. The signed Ubuntu i386 loader itself returned
`Exec format error`; adding more 32-bit libraries cannot repair that kernel
execution boundary. The extractor does not claim to run Wine or Windows code.

## Actual build recipe

Run only after the final frontend/desktop payload is ready. Set these variables
for the one build process, not globally. The output directory and evidence-file
parent must already exist.

```sh
HAMAVA_LOCAL_UNSIGNED_NSIS_EXTRACTION=1 \
HAMAVA_DESKTOP_BUILD_ROOT=/absolute/path/to/hamava/apps/desktop \
HAMAVA_NSIS_OUTPUT_DIR=/absolute/path/to/hamava/artifacts/desktop \
HAMAVA_NSIS_EVIDENCE_FILE=/absolute/path/to/hamava/docs/validation/windows-local-extractor-events.jsonl \
NODE_OPTIONS=--require=/absolute/path/to/hamava/docs/validation/build-support/local-unsigned-nsis.cjs \
CSC_IDENTITY_AUTO_DISCOVERY=false \
npm run build:win
```

Working directory: `/absolute/path/to/hamava/apps/desktop`.
Retain the build host's existing Electron/NSIS cache configuration. This adapter
requires no Wine installation, Wine prefix, display server or i386 host libraries.

The recorded local build also used an optional host-specific archive wrapper to
limit compression to two threads. Its executable body was:

```sh
#!/bin/sh
exec /absolute/path/to/electron-builder-cache/7zip@1.0.0/7zip-linux-x64-16wjr/bin/7zz "$@" -mmt=2
```

Make that wrapper executable, set `ELECTRON_BUILDER_7ZIP_PATH` to its absolute
path, and set `ELECTRON_BUILDER_COMPRESSION_LEVEL=5` for the build process. The
`7zz` path must point to the official tool actually installed in that host's
builder cache; the cache directory above records this build's tool version and
is not a portable installation path. These settings bound local build resources
and do not change the application. The final build staged its output outside the
synchronized workspace with `--config.directories.output=/absolute/staging/path`;
`HAMAVA_NSIS_OUTPUT_DIR` must name that same directory when an override is used.
Native Windows CI uses the standard builder path and needs neither workaround.

The adapter accepts only the expected Hamava versioned NSIS setup intermediate,
with no application arguments and the builder's `RunAsInvoker` context. It
checks a bounded PE32 header, verifies the original extractor's NSIS structure,
validates the extracted PE, rechecks that input did not change, and writes the
exact uninstaller pathname expected by `NsisTarget`. Other Windows executable
requests fail. Signing credentials or forced code signing also fail; use the
standard native Windows CI for a signed release.

The JSONL log records builder/extractor/input/output hashes and explicitly says
that Windows code execution, signing and a native install test did not occur.
Producing an installer is separate from successfully installing, upgrading or
uninstalling it on a real Windows machine. Native Windows CI remains unchanged.

## Final source and interface snapshot

The final local package build runs the unchanged `npm run build:win` command
from a temporary copy of the desktop project and the exact captured web bundle.
The installed locked dependency directory is reused. This prevents asynchronous
workspace synchronization from restoring an earlier generated interface while a
package is being assembled. `v2-windows-build-inputs.json` records every staged
desktop source hash, all 61 web asset hashes, the command and its actual exit
status. The product source and the normal Windows workflow require no such
staging arrangement.

Package verification compares the complete embedded web inventory and three
desktop host files with those captured inputs. It also extracts the application
archive from the compressed payload inside each final EXE and compares its
hash with the inspected payload. The recorded results do not rely on the
unpacked build directory alone. Android uses the same captured web bundle and
independently verifies every generated public asset in all three packages.

## Complete backend regression controller

`hamava-final-pytest-controller.py` and `hamava_final_shard_plugin.py` retain the
exact local controller and observer used for the final three-process backend
regression. Every process first collects the entire suite and then executes its
assigned whole test files in an isolated temporary directory. The aggregate
requires every planned node to be selected, started and finished exactly once,
all worker exits to succeed, and all frozen runtime/test/Python-support source
hashes to remain unchanged. This changes scheduling, not test assertions.

The retained evidence index binds the controller, observer, plan, observations,
JUnit files and sanitized logs to their hashes. Fixture databases, temporary
keys and test-created directory trees are excluded. The regular project and
GitHub command remains `pytest -q`; the separate interrupted serial attempt is
retained as incomplete history and is not described as a successful full run.
