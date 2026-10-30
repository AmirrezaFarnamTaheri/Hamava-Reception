# Deployment and recovery

[فارسی](deployment.fa.md) | [Documentation](README.md)

## Preconditions

Production requires an operator-owned HTTPS hostname, **PostgreSQL 16**, approved clinic and processor configuration, an on-call/staffed fallback route, independent privacy/clinical review and recoverable secrets. Demo mode must be off. Never start real traffic using sample accounts, a synthetic calendar, unsigned test packages or unreviewed vendor credentials.

The sample `.env.production.example` enumerates configuration without usable secrets. Generate unique private values:

~~~sh
python scripts/generate_env.py --host reception.your-domain.example
docker compose --env-file .env.production build
docker compose --env-file .env.production --profile https up -d
docker compose --env-file .env.production exec api python scripts/admin.py --email owner@your-domain.example --clinic-name 'نام مرکز' --slug your-clinic
~~~

Use a hostname you control; protect `.env.production` and preserve encryption keys, lookup-HMAC key and recovery material in the operator vault. `scripts/generate_env.py` refuses to overwrite an existing generated file. The compose migration service applies/validates schema **0002** before normal traffic. Fresh owner settings must be published and reviewed before opening reception.

## Optional integrations

Speech is separately installed and supplied with reviewed Faster-Whisper/Piper model weights. AudioSocket/Asterisk provides the selected PSTN path, while LiveKit serves browser RTC; neither implies a live carrier or SIP trunk. Deployment templates are under `deploy/` and optional compose profiles include `speech`, `pbx` and `webrtc`. Distinct tokens, approved origins/hosts, transport routes, pricing policy, consent, retention and real health observations are required before enabling SMS, payment, calendar, media or outbound calls. Screened Asterisk transfers require an actual accepted staff leg and verified two-way bridge, not just an event or initiated dial.

## Maintenance and recovery

Before migrations or deployment upgrades, pause API writers and background/media workers, take an encrypted database and configuration backup, verify decryption and restoration in an isolated environment, then run `python scripts/migrate.py` against the intended database. Validate version and business records before resuming work. There is no general reversible downgrade path; restore a tested backup rather than attempting ad hoc reverse SQL.

Use `scripts/backup.py`, `scripts/backup_daily.py`, `scripts/config_backup.py` and the systemd backup timer templates only after reviewing paths, permissions, encryption and destination. Store backups outside the deployment host and periodically test recovery. Keep encryption-key rotation and previous-key retention aligned with the protected records still requiring decryption.

## Observability and launch

`/health` reports basic service/database liveness; `/ready` reports observed dependencies. Alerting templates live in `deploy/prometheus-alerts.yml`. Keep metrics private and monitor queue age, unknown provider results, calendar conflicts, failed notifications, media degradation, financial liabilities and backup status. An actual launch needs external acceptance for carrier/PBX, approved clinic workflow, payment/SMS/calendar, privacy, physical device and signing as applicable; see [operations](operations.md).
