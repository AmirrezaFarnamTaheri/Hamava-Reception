# Complete backend verification in three isolated processes

The retained controller and plugin are the exact files used for the final verification. Their SHA-256 digests are pinned in the retained plan and evidence index. The controller does not change application or test code, and does not stop other test processes.

- `hamava-final-pytest-controller.py` performs collection, balances whole test files using a prior JUnit duration baseline, launches three processes, and checks source and exact node coverage.
- `hamava_final_shard_plugin.py` makes each process collect the entire backend suite before selecting its assigned files. It records actual selected, started, completed, and per-phase outcomes.
- Each process has its own pytest base temporary directory, cache, operating-system temporary directory, log, JUnit XML, and observation record. Existing fixtures independently isolate SQLite databases and use unique PostgreSQL schemas.
- The normal supervisor gate requires every planned node to execute exactly once, all call phases to pass, no skips or errors, all processes to exit zero, and the frozen Python/test/script sources to remain unchanged. A collection-only pass does not execute tests. The explicitly labeled supervisor-recovery case below has a separate evidence boundary.

## Reproduce

Use the project's installed test environment and an isolated disposable PostgreSQL instance. Set `TEST_DATABASE_URL` to that test instance; do not point it at an application database. The controller refuses to run without an explicit PostgreSQL test URL. It redacts that URL and its password from retained worker logs and JUnit before hashing.

Run the following from the project root, replacing the Python command with the intended installed virtual environment if necessary. Use fresh output directories; neither phase overwrites an existing result directory.

```bash
export TEST_DATABASE_URL='postgresql+psycopg://TEST_USER@TEST_HOST/TEST_DATABASE'
export TOOL_TIMEOUT_MS=30000
python docs/validation/build-support/hamava-final-pytest-controller.py plan \
  --project "$PWD" \
  --python "$(command -v python)" \
  --prior-junit "$PWD/docs/validation/v2-pytest-final.xml" \
  --output /tmp/hamava-pytest-reproduction-plan
python docs/validation/build-support/hamava-final-pytest-controller.py run \
  --plan /tmp/hamava-pytest-reproduction-plan/plan.json \
  --output "$PWD/artifacts/backend-pytest-reproduction"
```

`--supersedes-session` and `--serial-log` are optional provenance parameters used in this delivery to preserve an earlier interrupted serial attempt. They do not stop a process and are not needed for a new reproduction. Generate a new plan on the target machine rather than running a retained plan whose absolute execution paths describe the original host.

The supplied duration baseline is historical scheduling input. It does not determine whether a test passes, and summed historical durations do not guarantee a particular wall-clock time under CPU contention. `TOOL_TIMEOUT_MS=30000` is the test-run environment used on the busy build host; these results do not establish the production default tool deadline or an acoustic latency SLO.

## Read the evidence

The canonical final result is `docs/validation/v2-pytest-current-shards/aggregate.json`, with delivered file references and hashes in the adjacent `evidence-index.json`. The aggregate reports planned files/nodes, per-outcome counts, per-process exit codes and finished-node counts, every exact-coverage check, and frozen source hashes. The index uses paths relative to the delivered project. Absolute paths inside verbatim plans, observations and aggregates describe the original execution environment and are not extra delivered files.

The first complete 444-node run is preserved separately under `docs/validation/v2-pytest-before-consent-fixture-fix/`: it had 442 passes and two failures because the non-demo deposit fixture omitted the newly required displayed processing-notice fingerprint. The correction fetches the public disclosure and submits that exact fingerprint, preserving the payment and consent assertions. Its minimal diff, before/after source hashes, and four-case focused verification are retained. The failed run is not reclassified as passed, and the canonical final run must independently execute all 444 nodes.

## Recovery of the same original workers

The final run's exec-server connection was lost after the three original workers had started. Its supervisor could no longer be observed, while the last original worker continued to completion. No replacement test process was launched. The canonical aggregate therefore uses `status: passed_recovered_supervisor` and `completion_mode: same_original_three_workers_after_exec_transport_loss`.

`pytest-shard-recovery.py` independently verifies the original frozen plan, every worker's full collection, assigned/started/finished identities, all setup/call/teardown phase outcomes, exact JUnit classname/name identities, complete worker summaries, the pinned controller/plugin, and unchanged source hashes. Each original observer recorded `pytest_sessionfinish` exit status zero. An independent agent checked the same original records without executing tests or changing files. The recovery script itself performs no test execution.

The per-worker `exit_code` fields and supervisor OS exit code remain `null`: those wait observations were lost and are not inferred from passing tests. The separate `pytest_exit_status` fields are zero and identify their observer-record source. Exact supervisor wall time is also unavailable; individual worker durations and their maximum are retained without presenting them as uninterrupted overall timing. The interruption, independent check and recovery-verifier hash are delivered alongside the raw phase/JUnit/collection evidence.

Only explicit JSON, XML, sanitized logs, and the controller/plugin/recovery-verifier files are curated. Temporary SQLite files, PostgreSQL credentials, cryptographic keys, generated audio/data fixtures, and pytest temporary/cache trees are excluded. Local synthetic adapters and isolated database tests do not constitute live supplier, carrier, acoustic, signing, clinical, or physical-device acceptance.
