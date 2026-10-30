# Native clients and release process

[فارسی](clients-and-releases.fa.md) | [Documentation](README.md)

## Shared application and hosts

The React frontend is reused in the web deployment, the Electron desktop host under `apps/desktop/`, and the Capacitor Android host under `apps/mobile/`. Hosts connect to a clinic's HTTPS API; they do not contain an operational patient database or guarantee offline appointment writes. Initial connection uses `/api/v1/client-info` without staff credentials; sign-in follows only after a valid server is selected.

Desktop uses an isolated Electron bridge and OS-encrypted session storage. Android uses an Android Keystore-backed credential vault and network policy. Temporary connectivity loss should offer retry without reporting a successful operation; logout must block credential restoration even when remote revocation cannot be delivered.

## Local build

Install frontend dependencies and run `npm --prefix frontend run build` first. Then:

~~~sh
npm --prefix apps/desktop ci
npm --prefix apps/desktop run prepare:web
npm --prefix apps/desktop test
npm --prefix apps/desktop run build:win
npm --prefix apps/mobile ci
npm --prefix apps/mobile run sync
npm --prefix apps/mobile run build:debug
~~~

Windows packaging requires a suitable Windows build host. Android requires Java 21, Android SDK and Gradle wrapper; do not assume all these commands run on every machine. Artifacts are generated below `artifacts/`, not committed.

## CI and distribution

`.github/workflows/verify.yml` runs the main quality gates. `.github/workflows/release-apps.yml` consumes the verified web bundle and builds Windows NSIS/portable and Android APK/AAB packages. Its opt-in signing flags require real publisher credentials/keystores and signature verification. It can prepare a signed **draft** release, not automatic store publication or unrestricted production rollout.

Check `node scripts/check-versions.mjs` against the package, Python and compose image metadata. Treat unsigned packages as test artifacts. Before distribution, verify signed hashes, fresh install, upgrade, login/logout, microphone permission, connection failure, uninstall, rollback and representative physical devices. Maintain separate permissioned secrets for release signing and backend operation.
