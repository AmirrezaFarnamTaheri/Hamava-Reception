# Hamava shared web interface

[فارسی](README.fa.md) | [Project](../README.md) | [Development guide](../docs/development.md)

The React/TypeScript/Vite application supplies the Persian RTL staff console and public caller flows. It connects to the FastAPI `/api/v1` service and never substitutes imaginary success after a failed network operation.

## Work locally

With the backend listening on `http://127.0.0.1:8000`, run in `frontend/`:

~~~sh
npm ci
npm run dev
~~~

For the production-style static bundle use `npm run typecheck` and `npm run build`. The server serves built assets from `frontend/dist/` when present. Browser journeys must use an isolated synthetic API: `python scripts/ci_ui.py test:ui test:workflows test:conversation test:privacy-notice` from repository root after building.

## Navigation and limits

Staff workflows include Today, Appointments, Tasks, Calls, management and permission-gated controls. The public `/talk/:slug` asks for processing consent before session creation. The `/respond/:id#secret` link keeps the response secret in memory. Mobile navigation emphasizes Today / Tasks / Calls / More. Connection setup never sends credentials before the compatibility check; Android uses HTTPS. Permission and appointment authority remain on the server. Text stays usable if speech or RTC is unavailable; the UI does not claim offline booking or native-device qualification.

Consult [product behavior](../docs/product.md), [API semantics](../docs/api.md) and [native packaging](../docs/clients-and-releases.md) for the full maintained contracts.
