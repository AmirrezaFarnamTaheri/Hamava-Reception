"""Server version must match the maintained release version."""
from pathlib import Path
import tomllib

def test_fastapi_and_health_version_match_pyproject():
    from receptionist.main import app, health, client_info
    version = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())["project"]["version"]
    assert app.version == version
    assert health()["version"] == version
    assert client_info()["app_version"] == version
