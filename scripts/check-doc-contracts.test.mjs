import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { checkContracts } from './check-doc-contracts.mjs';

async function fixture(files) {
  const root = await mkdtemp(join(tmpdir(), 'hamava-contracts-'));
  for (const [path, data] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), data);
  }
  return root;
}

const base = {
  'backend/receptionist/api.py': 'router = APIRouter(prefix="/api/v1")\n@router.get("/items/{item_id}")\n@router.post("/items")\n',
  'backend/receptionist/main.py': '@app.get("/health")\n',
  'scripts/backup.py': 'save.add_argument("--output", required=True)\nsave.add_argument("--recipient", required=True)\n',
  'frontend/package.json': JSON.stringify({scripts:{build:'vite build',test:'node --test'}}),
};

async function withFixture(files, fn) {
  const root = await fixture({ ...base, ...files });
  try { await fn(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('accepts registered routes, path variables, CLI options, and package commands', async () => {
  await withFixture({'docs/guide.md': '~~~http\nGET /api/v1/items/<item-id>?date=<future-YYYY-MM-DD>\nPOST /api/v1/items\nGET /health\n~~~\n~~~sh\npython scripts/backup.py backup \\\n  --output /tmp/a \\\n  --recipient ABCD\nnpm --prefix frontend run build\n~~~'}, async root => {
    assert.deepEqual(await checkContracts(root), []);
  });
});

test('rejects an HTTP method that a router does not expose', async () => {
  await withFixture({'README.md': '~~~http\nDELETE /api/v1/items/42\n~~~'}, async root => {
    assert.ok((await checkContracts(root)).some(e => e.includes('DELETE /api/v1/items/42')));
  });
});

test('rejects a missing documented HTTP route', async () => {
  await withFixture({'README.md': '~~~http\nGET /api/v1/ghost\n~~~'}, async root => {
    assert.ok((await checkContracts(root)).some(e => e.includes('/api/v1/ghost')));
  });
});

test('rejects stale argparse options in multiline shell examples', async () => {
  await withFixture({'docs/guide.fa.md':'~~~sh\npython scripts/backup.py backup \\\n --output /tmp/a \\\n --invalid-flag x\n~~~'}, async root => {
    assert.ok((await checkContracts(root)).some(e => e.includes('--invalid-flag')));
  });
});

test('rejects a renamed script or a package command', async () => {
  await withFixture({'README.md':'~~~sh\npython scripts/missing.py --help\nnpm --prefix frontend run vanished\n~~~'}, async root => {
    const errors = await checkContracts(root);
    assert.ok(errors.some(e => e.includes('missing.py')));
    assert.ok(errors.some(e => e.includes('vanished')));
  });
});

test('ignores prose and API examples in non-executable documentation code fences', async () => {
  await withFixture({'README.md':'~~~text\nGET /api/v1/nonexistent\npython scripts/missing.py --bad\n~~~\n`GET /api/v1/nonexistent` is a hypothetical example.'}, async root => {
    assert.deepEqual(await checkContracts(root), []);
  });
});
