"""Module reachability audit must not delete dynamic registries or test-only compatibility."""
from pathlib import Path
import importlib.util
import tempfile

spec = importlib.util.spec_from_file_location("audit_dead_code", Path(__file__).resolve().parents[2] / "scripts/audit_dead_code.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf8")


def test_importing_model_registry_marks_dependent_models_live():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "backend/receptionist/main.py", "from . import model_registry\n")
        write(root, "backend/receptionist/model_registry.py", "from . import models\n")
        write(root, "backend/receptionist/models.py", "class Example: pass\n")
        write(root, "backend/receptionist/unused.py", "def ghost(): pass\n")
        results = audit.python_inventory(root)
        assert results["unreachable"] == ["backend/receptionist/unused.py"]
        assert results["entrypoint_reachable"] == 3


def test_dynamic_literal_imports_and_npm_script_roots_are_followed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "frontend/src/main.tsx", "import('./pages/Used').then(x => x.Used)\n")
        write(root, "frontend/src/pages/Used.tsx", "export const Used = 1\n")
        write(root, "frontend/src/pages/Orphan.tsx", "export const Orphan = 2\n")
        write(root, "frontend/scripts/suite.mjs", "import '../src/main.tsx';\n")
        write(root, "frontend/scripts/manual.mjs", "console.log('one off');\n")
        write(root, "frontend/package.json", '{"scripts":{"test:ui":"node scripts/suite.mjs"}}')
        results = audit.javascript_inventory(root)
        assert results["unreachable_application"] == ["frontend/src/pages/Orphan.tsx"]
        assert results["unreferenced_tooling"] == ["frontend/scripts/manual.mjs"]


def test_test_only_python_module_is_not_automatically_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "backend/receptionist/main.py", "")
        write(root, "backend/receptionist/compat.py", "")
        write(root, "backend/tests/test_compat.py", "import receptionist.compat\n")
        results = audit.python_inventory(root)
        assert results["test_only"] == ["backend/receptionist/compat.py"]
        assert results["unreachable"] == []
