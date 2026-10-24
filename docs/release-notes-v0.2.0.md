# Hamava Reception 0.2.0

## Reception workspace and companions

- Revised Persian right-to-left desktop workspace, responsive appointment cards, phone navigation, accessible feedback and role-aware administration.
- Native Electron desktop application with Windows NSIS installer and portable executable targets.
- Native Android companion with a server-bound Keystore vault, HTTPS networking and separate debug/release application IDs.
- Explicit clinic connection setup, compatibility handshake, per-device session restoration and server-side sign-out revocation.
- Shared cost, privacy, service connection and operational health controls backed by tenant-scoped APIs.

## Core and operations

- Additive schema migration `0002`, with drift checks, transactional rollback and preservation of existing records.
- Versioned clinic facts, service policies, calendar authority and routing configuration.
- Durable provider operations and reconciliation, observed dependency readiness and bounded recovery jobs.
- Monetary reservations and usage records, statement reconciliation, purpose controls, processor evidence and encrypted artifact handling.
- Governed messaging and outbound voice jobs, operational alerts, on-call assignments and research/configuration recovery tools.
- Privacy-minimized per-tool duration/outcome records that preserve deadline/rollback and queued-external semantics.
- Offline teacher-output comparison and content-bound human-adjudication validation with current rights/withdrawal checks and no automatic promotion to ground truth.

## Delivery

Verification precedes Windows and Android packaging. Release artifacts include checksums and a manifest. Publisher signing is optional and must be explicitly configured; the workflow verifies signatures when requested. The workflow can create a signed draft release but does not publish it automatically.

## Upgrade and acceptance

Back up the database and encryption configuration, stop writers, run `python scripts/migrate.py`, verify the `0002` schema and review the clinic's approved facts, calendar authority, processor settings and budgets before enabling live work. Legacy plaintext billing notes are moved into encrypted audit evidence without changing financial amounts.

The companion interface requires a deployed Hamava HTTPS API and real staff accounts. Unsigned desktop/release packages and development-signed Android APKs are test artifacts. Physical device behavior, real provider contracts, telephone routing, business/clinical acceptance and representative speech evidence remain subject to the exact gates in the implementation report and requirement register.
