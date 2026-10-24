import importlib.util
from pathlib import Path


def load():
    path = Path(__file__).resolve().parents[2] / "deploy/asterisk/hamava_register.py"
    spec = importlib.util.spec_from_file_location("hamava_agi", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pbx_destination_requires_independent_literal_allowlist(monkeypatch):
    module = load()
    monkeypatch.setenv("HUMAN_TRANSFER_TARGETS", "PJSIP/reception,Local/100@staff-only")
    assert module.approved_target("PJSIP/reception")
    assert module.approved_target("Local/100@staff-only")
    for value in [None, "PJSIP/paid-number", "PJSIP/reception&Local/evil", "PJSIP/${SYSTEM(id)}", "PJSIP/reception\nEXEC System id", "PJSIP/reception,30"]:
        assert not module.approved_target(value)


def test_even_allowlisted_injection_and_unknown_channels_are_rejected(monkeypatch):
    module = load()
    for value in ["System/command", "PJSIP/${shell}", "PJSIP/a,b", "PJSIP/a;System(id)"]:
        monkeypatch.setenv("HUMAN_TRANSFER_TARGETS", value)
        assert not module.approved_target(value)
