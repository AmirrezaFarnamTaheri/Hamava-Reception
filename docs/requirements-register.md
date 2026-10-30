# Requirement history and source of truth

[فارسی](requirements-register.fa.md) | [Documentation](README.md)

The machine-readable `requirements.json` is retained as the original detailed requirements inventory. It is **historical scope metadata**, not an up-to-date claim that every listed feature is verified. The source tree, tests, current CI and independent provider/clinic acceptance determine implementation and readiness.

Earlier duplicate exports, task summaries and intermediary reports have been removed from the maintained tree. Their prior contents remain recoverable from Git history. Do not rebuild the retired CSV summaries as competing sources of truth. Use the product, architecture, API and operations guides for maintained narrative specifications. When changing requirements, update the JSON record intentionally and supply code/test/acceptance evidence per item, without automatically labeling external dependencies as complete.
