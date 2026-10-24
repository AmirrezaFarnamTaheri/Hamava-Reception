#!/usr/bin/env python3
"""Create a private production environment file once; never print its secrets."""
import argparse
import os
from pathlib import Path
import secrets
from cryptography.fernet import Fernet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".env.production"))
    parser.add_argument("--host", required=True, help="Public HTTPS hostname you control")
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}", args.host):
        parser.error("host must be a DNS hostname, without a URL scheme or path")
    template = (Path(__file__).resolve().parents[1] / ".env.production.example").read_text()
    db_password = secrets.token_hex(32)  # URL-safe by construction.
    values = {"POSTGRES_PASSWORD": db_password,
              "DATABASE_URL": f"postgresql+psycopg://hamava:{db_password}@db:5432/hamava",
              "JWT_SECRET": secrets.token_urlsafe(48), "ENCRYPTION_KEY": Fernet.generate_key().decode(),
              "LOOKUP_HASH_KEY": secrets.token_urlsafe(48),
              "MEDIA_API_TOKEN": secrets.token_urlsafe(48), "PBX_EVENT_TOKEN": secrets.token_urlsafe(48),
              "METRICS_TOKEN": secrets.token_urlsafe(48),
              "SPEECH_GATEWAY_TOKEN": secrets.token_urlsafe(48),
              "CORS_ORIGINS": f"https://{args.host}", "PUBLIC_BASE_URL": f"https://{args.host}", "PUBLIC_HOST": args.host}
    lines = []
    for line in template.splitlines():
        key = line.split("=", 1)[0]
        lines.append(f"{key}={values[key]}" if key in values else line)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("\n".join(lines) + "\n")
    print(f"Created {args.output}. Save the encryption key in the approved recovery vault; review provider flags before startup.")


if __name__ == "__main__":
    main()
