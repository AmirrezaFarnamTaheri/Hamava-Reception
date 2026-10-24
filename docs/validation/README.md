# Reading the validation evidence

Files prefixed `v2-` describe the 0.2.0 implementation pass. The final release
report identifies the exact successful runs and their limits; a retained failed
diagnostic run is not passing evidence. `docs/history/implementation-0.2.0.md` in the project
archive and `requirements.json` are the release-level reconciliation.

Older, unprefixed files are retained baseline history from 0.1.0. They include
the actual local speech and loopback AudioSocket/LiveKit experiments. They are
not a new run of those experiments against the final 0.2.0 tree. Do not add
overlapping targeted-test counts together and describe the result as one suite.

All included patient, clinic, financial, carrier, model-evaluation and research
fixtures are synthetic. PostgreSQL contention demonstrates transaction
invariants, not an acoustic capacity or latency claim. Browser and backend
functional CI may use a 30000 ms tool budget to avoid shared-host timing
interference; production still defaults to 3000 ms, and dedicated deadline
regressions exercise their own smaller bounds.

Native source/bridge tests, a Linux Electron launch, Android compilation, and
generated EXE/APK/AAB files are distinct from Windows install/upgrade/uninstall,
physical Android acceptance, publisher signing, remote GitHub Actions, or a
production deployment. Read the release report before attributing any of those
outcomes to a local artifact.
