# Desktop, Android and release engineering

[فارسی](clients-and-releases.fa.md) · [Documentation](README.md)

Hamava has one shared React application and two native hosts, not three separate reception engines. The web interface lives in `frontend/`; `apps/desktop/` packages it with Electron, and `apps/mobile/` packages it with Capacitor for Android. Appointments, permissions, conversations and payment outcomes remain on the clinic server.

## What the native client adds

On first launch, a companion asks for the clinic's server address. It sends a **credential-free compatibility request** to `/api/v1/client-info` and only then allows sign-in. Android requires an HTTPS server. The desktop client uses a sandboxed Electron preload bridge and OS-backed session protection where available; Android uses a Keystore-based credential vault and restrictive networking/backup policy.

A client may retain a valid session across temporary connection failures, but it must not claim an offline booking or reconstruct a revoked login from a stale local vault entry. Explicit sign-out should revoke the server session when reachable and block automatic restoration locally even if the server cannot be contacted at that moment.

The same responsive RTL interface supplies desktop daily work and mobile Today / Tasks / Calls / More navigation. Permissions come from the current server membership; changing clinics must refresh the selected scope, not merely update the title in the UI.

## Prepare the shared web bundle

From the repository root with **Node.js 24**:

~~~sh
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
node scripts/check-versions.mjs
~~~

Web assets are generated in `frontend/dist/`. Build them before packaging either native host. Each package has its own lockfile; do not copy `node_modules` between projects or mix npm versions casually.

## Desktop builds

On a supported Windows build host:

~~~sh
npm --prefix apps/desktop ci
npm --prefix apps/desktop test
npm --prefix apps/desktop run prepare:web
npm --prefix apps/desktop run test:launch
npm --prefix apps/desktop run build:win
~~~

The builder can produce an NSIS installer and a portable Windows executable. The Electron bridge tests verify security-related application behavior; the launch test exercises a real packaged host path. Successful compilation on a CI runner does not substitute for installing, upgrading and uninstalling on supported physical Windows versions.

Linux AppImage/tar.gz packaging is available as a separate local target through the desktop package, but it is not the same as the Windows release workflow.

## Android builds

Install Java **21**, an Android SDK and the required build tools. Then:

~~~sh
npm --prefix apps/mobile ci
npm --prefix apps/mobile run sync
npm --prefix apps/mobile run test
npm --prefix apps/mobile run build:debug
~~~

The Capacitor host consumes the built web assets. Use the Android Gradle wrapper in `apps/mobile/android/` rather than an arbitrary system Gradle version. The debug application ID differs from release; do not confuse a debug APK with the production application or release certificate. The release workflow also compiles the release APK and AAB.

## CI, signing and publishing

| Workflow | Responsibility |
| --- | --- |
| `.github/workflows/verify.yml` | Backend, PostgreSQL, browser, desktop bridge and container checks |
| `.github/workflows/release-apps.yml` | Depend on verification; build Windows packages and Android bundles; collect hashes and manifests |

The release workflow accepts explicit signing switches. Windows publishing needs the authorized certificate and password; Android publishing needs the operator's keystore and aliases. When signing is requested, the workflow checks the resulting signatures rather than treating the presence of a file as sufficient. A signed, tagged run can optionally create a **draft** GitHub Release with [release notes](release-notes.md); publishing a public release or a store listing remains a separate owner decision.

Release versions are aligned across the root package, web, native apps, Python metadata and Compose image. `node scripts/check-versions.mjs` checks parity and that the English and Persian release notes match the version.

## Acceptance matrix before giving an installer to users

| Test | Windows | Android |
| --- | --- | --- |
| Signed package identity and checksum | Authenticode, setup and portable executable | APK/AAB signing identity and version |
| First launch | Clinic HTTPS address, compatibility check, login | HTTPS address, Android network policy and login |
| Session and sign-out | Secure storage, disconnected sign-out, relaunch | Keystore storage, backup restrictions, relaunch |
| Daily workflow | Keyboard, windows, calls/tasks, network interruption | 320/390 px layouts, keyboard, permission and app lifecycle |
| Upgrade and recovery | Fresh install, in-place upgrade, uninstall and rollback | Existing install upgrade, logout and reinstallation |
| Media | Microphone, actual staff handoff where used | Microphone permissions, background/foreground and network changes |

Record exact OS versions, installed artifact digests, result and operator for every tested device. Unsigned or debug builds are useful for engineering validation, but they are not a publisher-approved distribution.

## Troubleshooting packaging

If `prepare:web` fails, check whether `frontend/dist/` exists and matches the current source. If the version gate fails, update all version-bearing manifests together, including the release notes. If Android compilation fails, inspect the SDK/Java/Gradle wrapper configuration before changing application code. If a signed build fails, check credential availability and expected certificate identity without printing secrets into CI logs.

For browser behavior use [the frontend guide](../frontend/README.md); for environment ownership and recovery see [Deployment](deployment.md).
