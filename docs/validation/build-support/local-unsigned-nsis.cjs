'use strict';

// Local Linux build-only adapter for electron-builder's own, inspected Catalina
// NSIS extraction path. This does not run Windows code or simulate Wine success.
// Native Windows CI must not preload this adapter.
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

function abort(code) { throw new Error(`LOCAL_NSIS_EXTRACTOR_${code}`); }
function requiredPath(name) {
  const value = process.env[name];
  if (!value || !path.isAbsolute(value)) abort(`REQUIRES_${name}`);
  return value;
}
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
if (process.platform !== 'linux' || process.env.HAMAVA_LOCAL_UNSIGNED_NSIS_EXTRACTION !== '1') abort('EXPLICIT_LINUX_OPT_IN_REQUIRED');
const desktopRoot = fs.realpathSync(requiredPath('HAMAVA_DESKTOP_BUILD_ROOT'));
const outputRoot = fs.realpathSync(requiredPath('HAMAVA_NSIS_OUTPUT_DIR'));
const evidenceFile = requiredPath('HAMAVA_NSIS_EVIDENCE_FILE');
const project = JSON.parse(fs.readFileSync(path.join(desktopRoot, 'package.json'), 'utf8'));
if (project.name !== 'hamava-reception-desktop' || !/^\d+\.\d+\.\d+$/.test(project.version)) abort('UNEXPECTED_PROJECT');
const libraryRoot = path.join(desktopRoot, 'node_modules/app-builder-lib');
const library = JSON.parse(fs.readFileSync(path.join(libraryRoot, 'package.json'), 'utf8'));
if (library.version !== '26.15.3') abort('UNREVIEWED_BUILDER_VERSION');
const extractorPath = path.join(libraryRoot, 'out/targets/nsis/nsisUtil.js');
const extractorSha256 = sha(fs.readFileSync(extractorPath));
if (extractorSha256 !== 'fca86cb65c9a9e63744204379cad053ad14b774bff4f33eafec797227dd0dbf1') abort('EXTRACTOR_HASH_CHANGED');
const { UninstallerReader } = require(extractorPath);
const { WineVmManager } = require(path.join(libraryRoot, 'out/vm/WineVm.js'));
const expectedName = `Hamava-Reception-${project.version}-windows-x64-setup.exe`;
const certificateKeys = ['CSC_LINK', 'WIN_CSC_LINK', 'CSC_NAME', 'WIN_CSC_NAME', 'CSC_KEY_PASSWORD', 'WIN_CSC_KEY_PASSWORD'];

function requireUnsigned() {
  if (certificateKeys.some(key => Boolean(process.env[key])) || project.build?.forceCodeSigning || project.build?.win?.forceCodeSigning) abort('UNSIGNED_ONLY');
}

function validatePe32(data) {
  if (data.length < 256 || data.length > 8 * 1024 * 1024 || data.readUInt16LE(0) !== 0x5a4d) abort('INVALID_BOUNDED_PE');
  const offset = data.readUInt32LE(0x3c);
  if (offset < 64 || offset + 26 > data.length || data.readUInt32LE(offset) !== 0x4550 || data.readUInt16LE(offset + 4) !== 0x14c || data.readUInt16LE(offset + 24) !== 0x10b) abort('EXPECTED_NSIS_PE32');
}

WineVmManager.prototype.execWine = async function ({ file, appArgs = [], options = {} }) {
  requireUnsigned();
  if (typeof file !== 'string' || !path.isAbsolute(file) || path.basename(file) !== expectedName
      || !Array.isArray(appArgs) || appArgs.length !== 0 || options.env?.__COMPAT_LAYER !== 'RunAsInvoker') abort('UNEXPECTED_EXECUTABLE_REQUEST');
  if (await fsp.realpath(path.dirname(file)) !== outputRoot || !(await fsp.lstat(file)).isFile()) abort('UNEXPECTED_INTERMEDIATE_PATH');
  const input = await fsp.readFile(file);
  validatePe32(input);
  // The original extractor verifies the NSIS signature, total size and unique
  // embedded uninstaller block, and rejects a non-intermediate PE.
  const temporary = path.join(outputRoot, `.nsis-extract-${crypto.randomUUID()}.tmp`);
  const destination = path.join(outputRoot, `${path.basename(file, 'exe')}__uninstaller.exe`);
  try {
    await UninstallerReader.exec(file, temporary);
    const output = await fsp.readFile(temporary);
    validatePe32(output);
    if (sha(await fsp.readFile(file)) !== sha(input)) abort('INTERMEDIATE_CHANGED');
    await fsp.rename(temporary, destination);
    const evidence = {
      schema_version: 1,
      observed_at: new Date().toISOString(),
      method: 'installed_electron_builder_UninstallerReader',
      builder_version: library.version,
      extractor_sha256: extractorSha256,
      input_name: path.basename(file),
      input_sha256: sha(input),
      input_bytes: input.length,
      uninstaller_name: path.basename(destination),
      uninstaller_sha256: sha(output),
      uninstaller_bytes: output.length,
      host_platform: process.platform,
      windows_code_executed: false,
      signed: false,
      native_windows_install_tested: false,
    };
    await fsp.appendFile(evidenceFile, `${JSON.stringify(evidence)}\n`, { mode: 0o600 });
    console.info(`HAMAVA_UNSIGNED_NSIS_EXTRACTION ${JSON.stringify(evidence)}`);
    return '';
  } finally {
    await fsp.rm(temporary, { force: true });
  }
};

// Calls to exec() flow through execWine(). Every unexpected Windows request
// fails explicitly; this adapter has no fallback that pretends it executed.
