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


def test_native_preload_and_browser_fixture_loaded_by_literal_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "apps/desktop/src/main.cjs", 'const x = {preload: path.join(__dirname, "preload.cjs")};')
        write(root, "apps/desktop/src/preload.cjs", 'console.log("bridge");')
        write(root, "frontend/src/main.tsx", 'const value = 1;')
        write(root, "frontend/scripts/test.mjs", 'const f = new URL("./fixtures/rtc-room.mjs", import.meta.url);')
        write(root, "frontend/scripts/fixtures/rtc-room.mjs", 'export const x = 1;')
        write(root, "frontend/package.json", '{"scripts":{"test:ui":"node scripts/test.mjs"}}')
        result = audit.javascript_inventory(root)
        assert result["unreachable_desktop"] == []
        assert result["unreferenced_tooling"] == []


def test_android_manifest_and_capacitor_plugin_are_reachable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "apps/mobile/android/app/src/main/AndroidManifest.xml", '<activity android:name=".MainActivity" />')
        prefix = "apps/mobile/android/app/src/main/java/ir/hamava/reception/"
        write(root, prefix + "MainActivity.java", "public class MainActivity { HamavaDevicePlugin plugin; }")
        write(root, prefix + "HamavaDevicePlugin.java", "public class HamavaDevicePlugin { ServerPolicy p; }")
        write(root, prefix + "ServerPolicy.java", "public class ServerPolicy {}")
        write(root, prefix + "Dead.java", "public class Dead {}")
        result = audit.java_inventory(root)
        assert result["unreachable"] == [prefix + "Dead.java"]


def test_unused_export_and_top_level_function_are_reported_advisory_only():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "backend/receptionist/helpers.py", "def orphan(): pass\ndef used(): pass\nused()\n")
        write(root, "frontend/src/used.ts", "export function usedValue() {return 1;}\n")
        write(root, "frontend/src/other.ts", "export const deadValue = 2;\n")
        report = audit.symbol_inventory(root)
        assert any("orphan" in s for s in report["python_top_level_candidates"])
        assert not any(":used" in s for s in report["python_top_level_candidates"])
        assert any("deadValue" in s for s in report["frontend_export_candidates"])


def test_test_only_python_module_is_not_automatically_deleted():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "backend/receptionist/main.py", "")
        write(root, "backend/receptionist/compat.py", "")
        write(root, "backend/tests/test_compat.py", "import receptionist.compat\n")
        results = audit.python_inventory(root)
        assert results["test_only"] == ["backend/receptionist/compat.py"]
        assert results["unreachable"] == []
