# Hamava documentation

[فارسی](README.fa.md) | [Project home](../README.md)

This is the maintained documentation set for source version **0.2.2**. Read English and Persian versions side by side; technical identifiers and executable commands intentionally remain unchanged in translation.

| Guide | Purpose |
| --- | --- |
| [Product](product.md) | Users, workflows, functional boundaries and modes |
| [Architecture](architecture.md) | Components, authority, state, security and media |
| [API](api.md) | API discovery, authorization and result semantics |
| [Development](development.md) | Toolchain, tests, conventions and safe migrations |
| [Deployment](deployment.md) | Configuration, production topology and restoration |
| [Operations](operations.md) | Onboarding, daily work, incidents and live acceptance |
| [Clients and releases](clients-and-releases.md) | Desktop, Android, signing and publishing |
| [Research](research.md) | Speech evaluation, governance, capacity and economics |

The repository intentionally excludes historical per-run screenshots, JUnit XML and test logs from the maintained docs. They belong in ephemeral **GitHub Actions artifacts** or operator-controlled evidence storage, linked to an exact commit/run. Git history retains previous reports without presenting obsolete results as current.

Generated reference data under `docs/evidence/` and `fixtures/research/` are **synthetic**, not project status reports. The bundled `docs/licenses/` notice is upstream legal text and is not translated or modified.

## Authority hierarchy

1. Code, versioned migrations and tests define implemented behavior.
2. A running server's `/openapi.json` documents the actual deployed API shape.
3. This handbook explains intended use, boundaries and operator procedures.
4. The exact CI run and qualified external acceptance evidence determine what has been verified. Neither historical claims nor this handbook can attest a live clinic.

## Updating documentation

Change English and Persian counterparts in the same PR. Keep paths, commands, endpoint names, flags and limitations consistent. Run `node scripts/check-docs.mjs` and `node --test scripts/check-docs.test.mjs` before proposing changes. Where behavior is uncertain, state the missing verification rather than inventing success.
