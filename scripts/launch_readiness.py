#!/usr/bin/env python3
"""Evidence inventory for external Hamava release/clinic acceptance.

NEVER outputs production_ready=true: bytes and self-attestation cannot prove
clinical/legal approval, carrier coverage or real device behavior. An authorized
human must separately verify the genuine records and decide on deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


GATES = {
    "remote_ci": "Completed authorized repository CI run, source commit and logs",
    "windows_publisher_signing": "Real publisher certificate and Authenticode-verified installer",
    "android_release_signing": "Owner-controlled Android signing and Play/AppGallery key provenance",
    "windows_device": "Windows install/upgrade/launch/uninstall on target version",
    "android_device": "Android installs, secure storage, microphone and lifecycle on real devices",
    "store_acceptance": "Store account owner approval, listing, review and release state",
    "carrier_pstn": "Contracted Iranian trunk/PBX inbound/outbound, voice frames and human transfer",
    "staff_screening_and_bridge": "Provisioned pre-bridge acceptance prompt, staff DTMF 1, reject/timeout handling, actual caller/staff bridge and intelligible two-way media on the deployed PBX",
    "clinic_uat": "Clinic owner signoff of identity, policy, booking integrity and staff escalation",
    "privacy_and_clinical_review": "Qualified local privacy and clinical safety review of actual deployment",
    "speech_and_payment_providers": "Executed provider contracts, processing region and signed webhook trials",
    "public_rtc_network": "TLS, ICE, TURN and representative mobile-network failure recovery",
    "research_rights": "Separate recording, training, model licensing and retention authorization",
    "research_evaluation": "Held-out Persian phone corpus, reviewed labels, model/compute results",
}


def _validate_evidence(directory: Path, evidence: object) -> str:
    if not isinstance(evidence, dict):
        return "INVALID_EVIDENCE"
    relative, expected = evidence.get("file"), evidence.get("sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or not isinstance(expected, str):
        return "INVALID_EVIDENCE"
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        return "INVALID_EVIDENCE"
    root = directory.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 16_000_000:
        return "INVALID_EVIDENCE"
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        return "INVALID_EVIDENCE"
    return "EVIDENCE_SUBMITTED_REVIEW_REQUIRED"


def check_readiness(directory: Path, manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("Expected object of external evidence references")
    checks = {}
    for key, instruction in GATES.items():
        checks[key] = {"state": _validate_evidence(directory, manifest[key]) if key in manifest else "MISSING",
                       "external_acceptance": instruction}
    return {"product": "Hamava Reception", "environment": "external_acceptance",
            "production_ready": False, "human_independent_verification_required": True,
            "explanation": "The system only validates evidence-file identity. It cannot establish real-world approval, validity or service eligibility.",
            "gates": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text()) if args.manifest else {}
    report = check_readiness(args.evidence_dir, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("External production acceptance: unverified; independent sign-off required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
