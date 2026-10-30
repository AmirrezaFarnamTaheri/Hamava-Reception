# Reading the original requirements register

[فارسی](requirements-register.fa.md) · [Documentation](README.md)

The original detailed register is [`requirements.json`](requirements.json). It has **263 requirement IDs**, their acceptance criteria, phase assignments, owners by role and links to code or test evidence. This is a useful map of the work that shaped Hamava, but it is not a fresh audit of the current branch.

## What the register represents

The JSON identifies its edition as **Hamava Reception 0.2.0** and records a reconciliation on **23 October 2026**. The project source has since advanced to **0.2.2**. The status counts below describe that *earlier snapshot*, not the current state of the product:

| Recorded status | Count | How to read it |
| --- | ---: | --- |
| `verified_local` | 212 | Local source/test evidence was recorded at the snapshot date |
| `implemented_unverified` | 26 | Code existed, but the stated acceptance was not completely demonstrated |
| `blocked_external` | 22 | An outside dependency or real-world acceptance remained open |
| `deferred_by_product_gate` | 3 | Work was intentionally held behind a product or operational decision |
| **Total** | **263** | All original IDs are retained |

The status of one item must never be promoted merely because a synthetic test ran or a form was filled in. For example, a simulated payment confirms a programming path, not the clinic's actual merchant settlement; a browser RTC test does not show that a caller could hear a receptionist through a carrier.

## Why some evidence paths no longer resolve

The previous reporting workflow wrote large validation files into `docs/validation/`. The cleanup removed those generated files from the maintained branch so the documentation would not grow with obsolete screenshots, logs and repeated snapshots. The original JSON still has **681 references** to **71 distinct validation files** in that retired directory. Those strings are *historical pointers*. They have deliberately not been rewritten into fictional current files.

Retrieve an older evidence file from the **pre-cleanup commit**:

~~~sh
git show d19714bcccad1145291f717eebc0cb90072f10be:docs/validation/restore-drill.json
~~~

Or browse that commit in GitHub at [the pre-cleanup tree](https://github.com/AmirrezaFarnamTaheri/Hamava-Reception/tree/d19714bcccad1145291f717eebc0cb90072f10be). Some of the snapshot's source links also refer to earlier blueprint or review documents; retrieve those from the original history instead of restoring them to the live documentation directory.

## Investigating a requirement

Suppose you need to understand `FOUNDATION-002`, the durable relational-state requirement:

1. Search for its ID in `docs/requirements.json` and read the *acceptance condition*, not just the status.
2. Find the corresponding implementation under `backend/receptionist/` and its regression tests.
3. If its evidence references `docs/validation/restore-drill.json`, inspect the archived version using the command above; note the revision, environment and what it actually established.
4. Run the **current branch's** relevant tests and inspect the current CI result. A previously passing test does not prove a new commit.
5. If the claim depends on a real customer, carrier, bank, physical device or clinical/privacy review, seek independent acceptance from its accountable owner.

This separates three questions that are often confused: *was the feature planned?*, *does the code implement it?* and *has the actual operating environment accepted it?*

## Updating requirements without creating a second source of truth

Keep the original JSON as an historical register and refer to IDs when useful. Put the current, reader-facing explanation in the [Product](product.md), [Architecture](architecture.md), [API](api.md) or [Operations](operations.md) guide. For a new or changed acceptance condition, record the exact implementation change, regression test, current run and unresolved external dependency in the PR. Avoid modifying the archived status fields merely to make a progress count look better.

CI artifacts should be generated outside the tracked documentation tree and identified by commit and workflow run. If a future machine-readable live acceptance register is needed, design it explicitly as a separately versioned artifact with independently checked evidence rather than turning this historical JSON into an unreviewed dashboard.
