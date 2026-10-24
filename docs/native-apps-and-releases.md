# Desktop and Android companions

Hamava 0.2.0 contains one Persian, right-to-left reception application and two native hosts. The web application, Windows desktop app and Android companion use the same tenant-scoped API and permission checks. The native packages contain the interface, not a clinic database or an embedded server.

## Product experience

The desktop workspace groups daily reception work separately from clinic management. The phone interface provides Today, Tasks, Calls and More navigation, readable appointment cards, visible connection state and a connection-setup screen. Both expose only the routes and actions allowed by the signed-in staff member's permissions. The server remains the authority for every action.

First launch asks for the clinic's HTTPS server origin. A public compatibility check must identify the Hamava API before sign-in becomes available. No staff credential is sent by that check. Production login starts with blank fields; the synthetic demo account is offered only when the connected server explicitly advertises demo mode.

A temporary connection failure preserves an existing session and offers retry. When connected, explicit sign-out revokes that device's server session and clears its local vault. Offline sign-out immediately prevents automatic restoration, even if the native vault also fails to delete its record; it cannot establish remote revocation while the server is unreachable. The old server token then remains subject to its existing expiry and administrative revocation. Signing out one device does not revoke other devices unless the all-devices operation is selected through the API. Expired or revoked sessions require a fresh login.

Patient records remain on the server. The companions do not promise offline writes, background calling or push notifications. Appointment and task changes require connectivity, and the interface refreshes when it resumes or reconnects. Provider-side work and reminders run in the server worker rather than relying on a phone staying open.

## Connect a clinic

1. Deploy the API behind valid HTTPS, apply schema migration `0002`, provision real staff accounts and turn off `DEMO_MODE`.
2. Add the exact native origins to `CORS_ORIGINS`: `app://hamava` for Electron and `https://localhost` for Android. Keep the actual web origin as well. A wildcard is not accepted in production.
3. Launch the companion, enter only the server origin (for example, `https://reception.your-clinic.example`), check the connection and sign in.
4. Review clinic facts, active calendar authority, staff permissions and provider approvals in the administration views before enabling real workflows.

The web and desktop development setup accepts HTTP only on literal loopback hosts. The Android companion requires HTTPS in both debug and release builds; an Android device's `localhost` refers to that device. Use a reachable, trusted HTTPS development endpoint for device testing rather than disabling certificate checks or cleartext protections.

The server must allow the microphone through its HTTPS permissions policy for browser calls. Native hosts request microphone access only for a trusted local application frame. Device microphone and real clinic connectivity still require physical-device acceptance.

## Desktop security and packaging

`apps/desktop` is an Electron application with a sandboxed, isolated renderer and Node integration disabled. Its preload exposes five bounded operations: app information, read/write/clear a session and open an approved external URL. It exposes no raw IPC, shell or filesystem interface. Window navigation, new windows, webviews, local-file URLs and encoded asset traversal are restricted.

The session vault binds ciphertext to the selected server. It uses the operating system's secure storage through Electron's asynchronous `safeStorage` API. If secure storage is unavailable, including a Linux plaintext fallback, the app keeps the session in memory and does not silently persist it in browser storage. The server address itself is not a secret and is stored separately. No authentication token is placed in native `localStorage` or `sessionStorage`.

Windows packaging produces an assisted, per-user NSIS installer and a portable executable. The installer allows choosing the destination and does not request administrator elevation. Uninstallation does not erase app data automatically. A portable executable still uses the operating system's application-data directory for its encrypted vault; it does not carry clinic credentials beside the executable.

Build from the repository root with Node 24:

```sh
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix apps/desktop ci
npm --prefix apps/desktop test
npm --prefix apps/desktop run prepare:web
npm --prefix apps/desktop run test:launch
npm --prefix apps/desktop run build:win
node scripts/collect-release.mjs desktop
```

The Windows CI job runs on `windows-2025`, so its launch check exercises Windows Electron directly. A Linux development launch check is separate evidence and does not establish Windows installer behavior. Linux AppImage/tar and macOS DMG/ZIP targets are present for maintainers, but only Windows and Android are included in the supported release workflow in this version. No macOS signing or notarization is claimed.

## Android security and packaging

`apps/mobile` is a Capacitor 8 Android project, with a checked-in Gradle wrapper and native Java implementation of the `HamavaDevice` plugin. It targets SDK 36 and uses Java 21. The Gradle distribution is pinned with its published SHA-256 checksum.

The native vault uses an Android Keystore AES-GCM key, fresh IVs and authenticated metadata. The encrypted record includes the server origin. A corrupt, invalidated or mismatched record does not restore a session. Android backup and device transfer of app data are disabled. The app trusts system TLS certificates, rejects cleartext networking, disables WebView debugging in its shipping configuration and prevents OS screenshots/recents thumbnails of its authenticated surface. Screenshot-based browser validation therefore does not claim a physical Android capture.

Build after the web build:

```sh
npm --prefix apps/mobile ci
npm --prefix apps/mobile run sync
cd apps/mobile/android
./gradlew testDebugUnitTest lintDebug assembleDebug assembleRelease bundleRelease
```

On Windows use `gradlew.bat`, or run the cross-platform npm scripts from `apps/mobile`. Configure `JAVA_HOME`, `ANDROID_HOME` and the Android SDK licenses before building. The synchronization hook adds the native bundle's content security policy after every copy, so no server address or token is baked into the package.

The debug app uses `ir.hamava.reception.debug`, allowing it to coexist with the release app `ir.hamava.reception`. A debug APK has a development signature and is suitable for controlled installation tests. Without an organization's release keystore, the release APK and AAB remain unsigned. Do not distribute those as a publisher-authenticated production release.

## GitHub verification and release workflow

`.github/workflows/verify.yml` runs backend tests and lint, PostgreSQL contention checks, production startup checks, the web build, isolated browser suites, desktop security tests and a container startup check. Browser suites receive a fresh synthetic database and disabled real provider gates. No customer account or patient data is required. The verified web bundle becomes an artifact consumed by both package jobs.

`.github/workflows/release-apps.yml` runs on a version tag or manual dispatch. It first invokes the verification workflow, then builds Windows installer/portable packages and Android debug/release APK/AAB packages. Every action is pinned by commit SHA. The final job produces a combined artifact, a file manifest and SHA-256 checksums. Dependency updates are scheduled through `.github/dependabot.yml`.

The release also retains three CycloneDX inventories from the installed npm graphs: the shared interface, the Electron host and the Capacitor host. These inventories include their JavaScript build dependencies; the Android inventory does not claim to enumerate every Gradle or operating-system component. They identify dependencies and do not substitute for a vulnerability review.

All application manifests must have the same version. `scripts/check-versions.mjs` rejects drift and a tag that does not equal `v` plus that version. Update the release notes with each version before tagging. The current notes are `docs/release-notes-v0.2.0.md`.

Ordinary tag builds create test artifacts. Signing is an explicit manual workflow option, and missing signing configuration fails the requested signed build instead of producing an unsigned substitute. The workflow never automatically publishes a public release. Its optional draft-release job requires a tag on the default branch's history and both requested signatures, and only that job receives repository write permission.

| Secret                      | Purpose                                                                            |
| --------------------------- | ---------------------------------------------------------------------------------- |
| `WINDOWS_CSC_LINK`          | Publisher certificate material supported by electron-builder, such as a base64 PFX |
| `WINDOWS_CSC_KEY_PASSWORD`  | Password for that certificate                                                      |
| `ANDROID_KEYSTORE_BASE64`   | Base64 of the organization's Android release keystore                              |
| `ANDROID_KEYSTORE_PASSWORD` | Keystore password                                                                  |
| `ANDROID_KEY_ALIAS`         | Intended release signing alias                                                     |
| `ANDROID_KEY_PASSWORD`      | Password for the release signing key                                               |

For an approved signed build, run **Build desktop and Android apps** on the intended version tag with both signing inputs enabled. The Windows job verifies Authenticode status. The Android job verifies the release APK and AAB signatures. Its temporary keystore is removed in an always-run cleanup step. Enable `publish_draft` only when a draft release is wanted; final publication remains a separate repository action.

Do not commit signing material, local `.env` files, API tokens, clinic databases or Android `local.properties`. The ignore rules cover the standard generated paths and key formats. Protect the release workflow and signing secrets using the repository's actual access policy.

## Artifact interpretation and acceptance

`node scripts/collect-release.mjs desktop`, `android` or `manifest` collects compiled files and records their exact sizes and SHA-256 values. The default destination is `artifacts/release`; an optional second argument selects another dedicated release directory. The collector reads the version from the root `package.json` and requires complete package sets before writing output.

| Setting                         | Default | Effect                                                                                                                                                                         |
| ------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `HAMAVA_WINDOWS_ARCH`           | `x64`   | Requires exactly that architecture's setup and portable executables. Explicit `arm64` is also accepted; the supplied Windows workflow builds only `x64`.                       |
| `HAMAVA_WINDOWS_SIGNED`         | `false` | `true` requires matching signature evidence for both exact Windows executable names. `false` rejects stale Windows signature metadata in the desktop source or release output. |
| `HAMAVA_ANDROID_RELEASE_SIGNED` | `false` | Selects the signed-build or unsigned release APK path and matching APK/AAB output names. The debug APK is required in either mode.                                             |

Signing flags accept only the literal values `true` and `false`. Pass the same architecture and signing settings to both platform collectors and the final `manifest` command. The release workflow sets these values once for all its jobs. A flag declares the intended build mode; it does not perform signature verification.

The desktop source must contain `artifacts/desktop/Hamava-Reception-<version>-windows-<arch>-setup.exe` and `...-portable.exe`. Intermediate uninstallers, other versions and other architectures in the build source are never copied. Signed Windows collection also requires `artifacts/desktop-validation/signatures.json`, containing exactly one row for each of those two names with `file`, `status: "Valid"`, the certificate `thumbprint`, and the SHA-256 `sha256` of that executable's actual bytes. The Windows workflow runs Authenticode verification on these exact files and hashes them before and after verification to reject changes during that check. The collector matches the evidence hashes to the bytes it copies; it does not itself verify cryptographic signatures.

Android source files are under `apps/mobile/android/app/build/outputs`: `apk/debug/app-debug.apk`, either `apk/release/app-release.apk` or `apk/release/app-release-unsigned.apk`, and `bundle/release/app-release.aab`. Their collected names are `Hamava-Companion-<version>-android-debug.apk` plus either `...-release.apk` and `...-release.aab`, or `...-release-unsigned.apk` and `...-release-unsigned.aab`. The signed workflow verifies the APK and AAB before collecting them. Unsigned AAB builds use the same Gradle source filename, so the explicit signing flag determines their collected label.

The final `manifest` operation requires all five packages: both Windows executables and the matching Android trio. A reused release directory must contain only the expected current-version package names, supported inventory/signature metadata, and the generated manifest/checksum files. Stale versions, mixed architectures, mixed Android signing modes, intermediate packages and unexpected files are rejected. Archive or remove an old release directory deliberately before starting a different release; collection does not silently delete or repair its contents. The checksum list covers the supplied metadata as well as the packages. Hashes establish file identity; they do not establish publisher identity, safety certification or deployment approval. Keep real signature verification evidence with signed packages.

`node scripts/test-collect-release.mjs --report docs/validation/v2-release-collector.json` exercises these collection rules using isolated temporary files. Its package bytes and signature-status rows are synthetic. The fixtures verify set membership, rejection and hash associations only; they do not prove real signatures or successful installation. The release workflow runs these fixtures before assembling its combined artifact.

Local browser contract tests cover native connection setup, credential-free handshake, vault use, session restoration, network retry, logout revocation and tampered origin rejection. Electron launch tests exercise the actual renderer and bridge. Java unit tests exercise server/URL/token validation, and Android lint checks the native project. These are separate from physical Android installation, Windows installer install/upgrade/uninstall, OS permission prompts, real microphone routing and clinic/provider acceptance.

A GitHub repository and its release secrets must be supplied before these workflow files can run remotely. A locally linted workflow is not evidence of a completed GitHub Actions run. Use `IMPLEMENTATION_REPORT.md` and the requirement register for the exact retained verification results and outstanding external acceptance.
