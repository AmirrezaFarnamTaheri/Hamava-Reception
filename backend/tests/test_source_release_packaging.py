"""Source delivery must be reproducible, complete, and free of private build state."""
from pathlib import Path
from zipfile import ZipFile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import hashlib
import json

from scripts.make_source_release import package_source


def test_source_packaging_includes_code_not_credentials(tmp_path):
    root = tmp_path / 'voice-receptionist'
    (root / 'backend' / 'receptionist').mkdir(parents=True)
    (root / '.github' / 'workflows').mkdir(parents=True)
    (root / 'backend' / 'receptionist' / 'app.py').write_text('print("hello")\n')
    (root / '.github' / 'workflows' / 'verify.yml').write_text('name: Verify\n')
    (root / '.env.example').write_text('AUTH_TOKEN=\n')
    (root / '.env').write_text('AUTH_TOKEN=REAL_SECRET\n')
    (root / 'private.key').write_text('PRIVATE_KEY')
    (root / 'node_modules').mkdir()
    (root / 'node_modules' / 'bad.js').write_text('junk')
    (root / 'pytest.db').write_text('STATE')
    out = tmp_path / 'delivery.zip'
    manifest = package_source(root, out)
    with ZipFile(out) as archive:
        names = set(archive.namelist())
        assert 'voice-receptionist/backend/receptionist/app.py' in names
        assert 'voice-receptionist/.github/workflows/verify.yml' in names
        assert 'voice-receptionist/.env.example' in names
        assert 'voice-receptionist/PACKAGE-MANIFEST.json' in names
        assert 'voice-receptionist/.env' not in names
        assert 'voice-receptionist/private.key' not in names
        assert 'voice-receptionist/node_modules/bad.js' not in names
        assert 'voice-receptionist/pytest.db' not in names
        packaged = json.loads(archive.read('voice-receptionist/PACKAGE-MANIFEST.json'))
        assert packaged['file_count'] == 3
        assert packaged['files']['backend/receptionist/app.py']['sha256'] == hashlib.sha256(b'print("hello")\n').hexdigest()
    assert manifest['file_count'] == 3


def test_package_rejects_symlink_escape_and_self_packaging(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'README.md').write_text('safe')
    (root / 'outside.py').symlink_to(tmp_path / 'outside.py')
    (tmp_path / 'outside.py').write_text('NOT IN SOURCE')
    out = tmp_path / 'delivery.zip'
    package_source(root, out)
    with ZipFile(out) as archive:
        assert all(not x.endswith('outside.py') for x in archive.namelist())
    try:
        package_source(root, root / 'archive.zip')
    except ValueError as exc:
        assert 'OUTPUT_INSIDE_SOURCE' in str(exc)
    else:
        raise AssertionError('Cannot package an output stored under the input root')


def test_packages_are_deterministic(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'file.txt').write_text('stable')
    a, b = tmp_path / 'a.zip', tmp_path / 'b.zip'
    assert package_source(root, a) == package_source(root, b)
    assert hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()
