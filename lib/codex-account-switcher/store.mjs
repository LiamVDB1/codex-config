import { constants as fsConstants } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  extractAuthSummary,
  extractGlobalStateSummary,
  fingerprintAuth,
  sameAccountIdentity,
} from './auth.mjs';
import { slugifyLabel } from './rank.mjs';

const STORE_VERSION = 1;
const SHARED_PROFILE_ENTRIES = [
  '.env',
  '.env.example',
  'agents',
  'archived_sessions',
  'config.toml',
  'history.jsonl',
  'internal_storage.json',
  'memories',
  'models_cache.json',
  'models_catalog.json',
  'rules',
  'session_index.jsonl',
  'sessions',
  'shell_snapshots',
  'skills',
  'vendor_imports',
  'version.json',
];
const SHARED_RUNTIME_DIRECTORIES = ['archived_sessions', 'sessions', 'shell_snapshots'];
const SHARED_RUNTIME_FILES = ['history.jsonl', 'session_index.jsonl'];

function defaultManifest() {
  return {
    version: STORE_VERSION,
    snapshots: {},
  };
}

async function pathExists(targetPath) {
  try {
    await fs.access(targetPath);
    return true;
  } catch {
    return false;
  }
}

async function readJsonFile(filePath) {
  return JSON.parse(await fs.readFile(filePath, 'utf8'));
}

async function writeSensitiveJson(filePath, payload) {
  const tempPath = `${filePath}.tmp-${process.pid}-${Date.now()}`;
  const text = `${JSON.stringify(payload, null, 2)}\n`;

  await fs.writeFile(tempPath, text, { mode: 0o600 });
  await fs.chmod(tempPath, 0o600).catch(() => {});
  await fs.rename(tempPath, filePath);
}

async function ensureStore(paths) {
  await fs.mkdir(paths.accountsDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(paths.snapshotsDir, { recursive: true, mode: 0o700 });
  await fs.mkdir(paths.profileHomesDir, { recursive: true, mode: 0o700 });
}

async function ensureSharedRuntimeTargets(codexHome) {
  for (const relativePath of SHARED_RUNTIME_DIRECTORIES) {
    await fs.mkdir(path.join(codexHome, relativePath), { recursive: true, mode: 0o700 });
  }

  for (const relativePath of SHARED_RUNTIME_FILES) {
    const targetPath = path.join(codexHome, relativePath);
    if (await pathExists(targetPath)) {
      continue;
    }

    await fs.writeFile(targetPath, '', { mode: 0o600 });
    await fs.chmod(targetPath, 0o600).catch(() => {});
  }
}

async function removeIfExists(targetPath) {
  await fs.rm(targetPath, { recursive: true, force: true }).catch(() => {});
}

async function writeJsonIfPresent(filePath, payload) {
  if (payload === null || payload === undefined) {
    await removeIfExists(filePath);
    return;
  }

  await writeSensitiveJson(filePath, payload);
}

async function readOptionalJsonFile(filePath) {
  if (!(await pathExists(filePath))) {
    return null;
  }

  return readJsonFile(filePath);
}

async function ensureSymlink(linkPath, targetPath) {
  const existing = await fs.lstat(linkPath).catch(() => null);
  if (existing) {
    if (existing.isSymbolicLink()) {
      const currentTarget = await fs.readlink(linkPath).catch(() => null);
      if (currentTarget === targetPath) {
        return;
      }
    }

    await removeIfExists(linkPath);
  }

  const stats = await fs.lstat(targetPath);
  const type = stats.isDirectory() ? 'dir' : 'file';
  await fs.symlink(targetPath, linkPath, type);
}

async function sameFileSystemTarget(leftPath, rightPath) {
  const [leftRealPath, rightRealPath] = await Promise.all([
    fs.realpath(leftPath).catch(() => null),
    fs.realpath(rightPath).catch(() => null),
  ]);

  return Boolean(leftRealPath && leftRealPath === rightRealPath);
}

function collapseThreadName(text) {
  const normalized = String(text ?? '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!normalized) {
    return null;
  }

  return normalized.length > 120 ? `${normalized.slice(0, 117)}...` : normalized;
}

async function readJsonLines(filePath) {
  if (!(await pathExists(filePath))) {
    return [];
  }

  const text = await fs.readFile(filePath, 'utf8');
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

async function appendUniqueLines(targetPath, sourcePath, keyFn = (line) => line) {
  if (!(await pathExists(sourcePath))) {
    return 0;
  }

  if (await sameFileSystemTarget(targetPath, sourcePath)) {
    return 0;
  }

  const existingLines = (await pathExists(targetPath))
    ? (await fs.readFile(targetPath, 'utf8'))
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    : [];
  const knownKeys = new Set(existingLines.map((line) => keyFn(line)));
  const sourceLines = (await fs.readFile(sourcePath, 'utf8'))
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  const missingLines = sourceLines.filter((line) => {
    const key = keyFn(line);
    if (knownKeys.has(key)) {
      return false;
    }

    knownKeys.add(key);
    return true;
  });

  if (!missingLines.length) {
    return 0;
  }

  await fs.appendFile(targetPath, `${missingLines.join('\n')}\n`, { mode: 0o600 });
  await fs.chmod(targetPath, 0o600).catch(() => {});
  return missingLines.length;
}

async function listFilesRecursive(rootPath) {
  if (!(await pathExists(rootPath))) {
    return [];
  }

  const filePaths = [];

  async function walk(currentPath) {
    const entries = await fs.readdir(currentPath, { withFileTypes: true });
    for (const entry of entries) {
      const entryPath = path.join(currentPath, entry.name);
      if (entry.isDirectory()) {
        await walk(entryPath);
        continue;
      }

      if (entry.isFile()) {
        filePaths.push(entryPath);
      }
    }
  }

  await walk(rootPath);
  return filePaths;
}

async function copyMissingTree(sourceRoot, targetRoot) {
  if (!(await pathExists(sourceRoot))) {
    return 0;
  }

  if (await sameFileSystemTarget(sourceRoot, targetRoot)) {
    return 0;
  }

  let copiedCount = 0;
  for (const sourcePath of await listFilesRecursive(sourceRoot)) {
    const relativePath = path.relative(sourceRoot, sourcePath);
    const targetPath = path.join(targetRoot, relativePath);
    await fs.mkdir(path.dirname(targetPath), { recursive: true, mode: 0o700 });

    try {
      await fs.copyFile(sourcePath, targetPath, fsConstants.COPYFILE_EXCL);
      copiedCount += 1;
    } catch (error) {
      if (error?.code !== 'EEXIST') {
        throw error;
      }
    }
  }

  return copiedCount;
}

async function getHistorySummary(historyPath) {
  const records = await readJsonLines(historyPath).catch(() => []);
  const bySessionId = new Map();

  for (const record of records) {
    if (!record?.session_id) {
      continue;
    }

    const threadName = collapseThreadName(record.text);
    const updatedAt =
      Number.isFinite(record.ts) || typeof record.ts === 'number'
        ? new Date(record.ts * 1000).toISOString()
        : null;
    const current = bySessionId.get(record.session_id);
    if (!current || (updatedAt && updatedAt > current.updatedAt)) {
      bySessionId.set(record.session_id, {
        threadName,
        updatedAt,
      });
    }
  }

  return bySessionId;
}

async function getSessionIndexEntriesFromSessionFiles(profileHomePath) {
  const historyBySessionId = await getHistorySummary(path.join(profileHomePath, 'history.jsonl'));
  const entries = [];

  for (const sessionPath of await listFilesRecursive(path.join(profileHomePath, 'sessions'))) {
    const text = await fs.readFile(sessionPath, 'utf8');
    const lines = text
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    let sessionId = null;
    let fallbackThreadName = null;
    let updatedAt = null;

    for (const line of lines) {
      const record = JSON.parse(line);
      if (record?.type === 'session_meta') {
        sessionId = record.payload?.id ?? sessionId;
        updatedAt = record.payload?.timestamp ?? record.timestamp ?? updatedAt;
        continue;
      }

      if (!fallbackThreadName && record?.type === 'response_item' && record.payload?.type === 'message' && record.payload?.role === 'user') {
        const content = record.payload.content?.find(
          (item) => item?.type === 'input_text' && !String(item.text ?? '').trim().startsWith('<environment_context>'),
        );
        fallbackThreadName = collapseThreadName(content?.text);
      }

      updatedAt = record?.timestamp ?? updatedAt;
    }

    if (!sessionId) {
      continue;
    }

    const historyEntry = historyBySessionId.get(sessionId);
    entries.push({
      id: sessionId,
      thread_name: historyEntry?.threadName ?? fallbackThreadName ?? sessionId,
      updated_at: historyEntry?.updatedAt ?? updatedAt ?? new Date().toISOString(),
    });
  }

  return entries;
}

async function appendMissingSessionIndexEntries(codexHome, profileHomePath) {
  const targetPath = path.join(codexHome, 'session_index.jsonl');
  const existingIds = new Set((await readJsonLines(targetPath)).map((record) => record?.id).filter(Boolean));
  const missingEntries = [];

  const sourceIndexPath = path.join(profileHomePath, 'session_index.jsonl');
  if (await pathExists(sourceIndexPath)) {
    for (const record of await readJsonLines(sourceIndexPath)) {
      if (!record?.id || existingIds.has(record.id)) {
        continue;
      }

      existingIds.add(record.id);
      missingEntries.push(record);
    }
  }

  for (const record of await getSessionIndexEntriesFromSessionFiles(profileHomePath)) {
    if (!record.id || existingIds.has(record.id)) {
      continue;
    }

    existingIds.add(record.id);
    missingEntries.push(record);
  }

  if (!missingEntries.length) {
    return 0;
  }

  await fs.appendFile(targetPath, `${missingEntries.map((record) => JSON.stringify(record)).join('\n')}\n`, { mode: 0o600 });
  await fs.chmod(targetPath, 0o600).catch(() => {});
  return missingEntries.length;
}

export async function consolidateProfileHomeData(codexHome = resolveCodexHome(), profileHomePath) {
  if (!profileHomePath || !(await pathExists(profileHomePath))) {
    return {
      archivedSessionsCopied: 0,
      historyLinesMerged: 0,
      sessionFilesCopied: 0,
      sessionIndexEntriesAdded: 0,
      shellSnapshotsCopied: 0,
    };
  }

  if (await sameFileSystemTarget(codexHome, profileHomePath)) {
    return {
      archivedSessionsCopied: 0,
      historyLinesMerged: 0,
      sessionFilesCopied: 0,
      sessionIndexEntriesAdded: 0,
      shellSnapshotsCopied: 0,
    };
  }

  await ensureSharedRuntimeTargets(codexHome);

  const historyLinesMerged = await appendUniqueLines(
    path.join(codexHome, 'history.jsonl'),
    path.join(profileHomePath, 'history.jsonl'),
  );
  const sessionFilesCopied = await copyMissingTree(path.join(profileHomePath, 'sessions'), path.join(codexHome, 'sessions'));
  const shellSnapshotsCopied = await copyMissingTree(
    path.join(profileHomePath, 'shell_snapshots'),
    path.join(codexHome, 'shell_snapshots'),
  );
  const archivedSessionsCopied = await copyMissingTree(
    path.join(profileHomePath, 'archived_sessions'),
    path.join(codexHome, 'archived_sessions'),
  );
  const sessionIndexEntriesAdded = await appendMissingSessionIndexEntries(codexHome, profileHomePath);

  return {
    archivedSessionsCopied,
    historyLinesMerged,
    sessionFilesCopied,
    sessionIndexEntriesAdded,
    shellSnapshotsCopied,
  };
}

async function seedProfileHome(paths, record, auth, globalState) {
  const profileHomePath = path.join(paths.accountsDir, record.profileHomeDir);

  await fs.mkdir(profileHomePath, { recursive: true, mode: 0o700 });
  await ensureSharedRuntimeTargets(paths.codexHome);
  for (const relativePath of SHARED_PROFILE_ENTRIES) {
    const sourcePath = path.join(paths.codexHome, relativePath);
    if (!(await pathExists(sourcePath))) {
      continue;
    }

    await ensureSymlink(path.join(profileHomePath, relativePath), sourcePath);
  }

  await writeSensitiveJson(path.join(profileHomePath, 'auth.json'), auth);
  await writeJsonIfPresent(path.join(profileHomePath, '.codex-global-state.json'), globalState);
  return profileHomePath;
}

export function normalizeCodexHome(candidate) {
  const resolvedPath = path.resolve(candidate);
  const homesDir = path.dirname(resolvedPath);
  const accountsDir = path.dirname(homesDir);
  if (path.basename(homesDir) === 'homes' && path.basename(accountsDir) === 'accounts') {
    return path.dirname(accountsDir);
  }

  return resolvedPath;
}

export function resolveCodexHome(override) {
  const candidate = override ?? process.env.CODEX_HOME ?? path.join(os.homedir(), '.codex');
  return override ? path.resolve(candidate) : normalizeCodexHome(candidate);
}

export function getStorePaths(codexHome = resolveCodexHome()) {
  const accountsDir = path.join(codexHome, 'accounts');
  const snapshotsDir = path.join(accountsDir, 'snapshots');
  const profileHomesDir = path.join(accountsDir, 'homes');

  return {
    codexHome,
    authPath: path.join(codexHome, 'auth.json'),
    globalStatePath: path.join(codexHome, '.codex-global-state.json'),
    accountsDir,
    snapshotsDir,
    profileHomesDir,
    manifestPath: path.join(accountsDir, 'manifest.json'),
  };
}

function buildDefaultLabel(summary, manifest) {
  const seed =
    summary.email?.split('@')[0] ??
    summary.chatgptAccountId ??
    summary.planType ??
    'account';
  const base = slugifyLabel(seed);
  const existingLabels = new Set(Object.keys(manifest.snapshots));

  if (!existingLabels.has(base)) {
    return base;
  }

  let index = 2;
  while (existingLabels.has(`${base}-${index}`)) {
    index += 1;
  }

  return `${base}-${index}`;
}

function resolveSnapshotRecord(manifest, label) {
  const requested = String(label ?? '').trim();
  if (!requested) {
    throw new Error('An account label is required');
  }

  const exactKey = slugifyLabel(requested);
  if (manifest.snapshots[exactKey]) {
    return manifest.snapshots[exactKey];
  }

  const lower = requested.toLowerCase();
  const match = Object.values(manifest.snapshots).find((entry) => String(entry.label).toLowerCase() === lower);
  if (!match) {
    throw new Error(`Saved account "${requested}" was not found`);
  }

  return match;
}

export async function loadManifest(codexHome = resolveCodexHome()) {
  const paths = getStorePaths(codexHome);

  if (!(await pathExists(paths.manifestPath))) {
    return defaultManifest();
  }

  const manifest = await readJsonFile(paths.manifestPath);
  if (manifest?.version !== STORE_VERSION || typeof manifest?.snapshots !== 'object') {
    throw new Error('Unsupported account manifest version');
  }

  return manifest;
}

export async function readCurrentAuth(codexHome = resolveCodexHome()) {
  const { authPath } = getStorePaths(codexHome);
  if (!(await pathExists(authPath))) {
    throw new Error(`Codex auth file was not found at ${authPath}`);
  }

  return readJsonFile(authPath);
}

export async function readCurrentGlobalState(codexHome = resolveCodexHome()) {
  const { globalStatePath } = getStorePaths(codexHome);
  return readOptionalJsonFile(globalStatePath);
}

export async function getCurrentAccountContext(codexHome = resolveCodexHome()) {
  const auth = await readCurrentAuth(codexHome);
  const globalState = await readCurrentGlobalState(codexHome);
  return {
    auth,
    globalState,
    summary: extractAuthSummary(auth),
    globalStateSummary: extractGlobalStateSummary(globalState),
    fingerprint: fingerprintAuth(auth),
  };
}

export async function saveCurrentAccount(codexHome = resolveCodexHome(), label) {
  const paths = getStorePaths(codexHome);
  const manifest = await loadManifest(codexHome);
  const { auth, globalState, summary, globalStateSummary, fingerprint } = await getCurrentAccountContext(codexHome);

  await ensureStore(paths);

  const effectiveLabel = label ? slugifyLabel(label) : buildDefaultLabel(summary, manifest);
  const existing = manifest.snapshots[effectiveLabel] ?? null;
  const snapshotFile = existing?.snapshotFile ?? path.join('snapshots', `${effectiveLabel}.auth.json`);
  const globalStateFile =
    globalState === null
      ? null
      : existing?.globalStateFile ?? path.join('snapshots', `${effectiveLabel}.global-state.json`);
  const profileHomeDir = existing?.profileHomeDir ?? path.join('homes', effectiveLabel);
  const snapshotPath = path.join(paths.accountsDir, snapshotFile);
  const profileHomePath = path.join(paths.accountsDir, profileHomeDir);

  await writeSensitiveJson(snapshotPath, auth);
  if (globalStateFile) {
    await writeSensitiveJson(path.join(paths.accountsDir, globalStateFile), globalState);
  }
  await consolidateProfileHomeData(paths.codexHome, profileHomePath);
  await seedProfileHome(paths, { profileHomeDir }, auth, globalState);

  manifest.snapshots[effectiveLabel] = {
    ...(existing ?? {}),
    label: effectiveLabel,
    fingerprint,
    summary,
    globalStateSummary,
    savedAt: new Date().toISOString(),
    snapshotFile,
    globalStateFile,
    profileHomeDir,
  };

  await writeSensitiveJson(paths.manifestPath, manifest);
  return manifest.snapshots[effectiveLabel];
}

function findMatchingSavedRecord(manifest, current) {
  if (!current) {
    return null;
  }

  return (
    Object.values(manifest.snapshots).find((entry) => entry.fingerprint === current.fingerprint) ??
    Object.values(manifest.snapshots).find((entry) => sameAccountIdentity(entry.summary, current.summary)) ??
    null
  );
}

async function refreshMatchingSavedAccountFromCurrent(codexHome, manifest, current) {
  const matchingRecord = findMatchingSavedRecord(manifest, current);
  if (!matchingRecord || matchingRecord.fingerprint === current.fingerprint) {
    return manifest;
  }

  await saveCurrentAccount(codexHome, matchingRecord.label);
  return loadManifest(codexHome);
}

export async function listSavedAccounts(codexHome = resolveCodexHome()) {
  const paths = getStorePaths(codexHome);
  let manifest = await loadManifest(codexHome);
  const current = (await pathExists(paths.authPath)) ? await getCurrentAccountContext(codexHome) : null;
  manifest = await refreshMatchingSavedAccountFromCurrent(codexHome, manifest, current);
  const currentRecord = findMatchingSavedRecord(manifest, current);

  return Object.values(manifest.snapshots)
    .sort((left, right) => String(left.label).localeCompare(String(right.label)))
    .map((entry) => ({
      ...entry,
      isCurrent: Boolean(currentRecord && currentRecord.label === entry.label),
    }));
}

export async function loadSavedAccount(codexHome = resolveCodexHome(), label) {
  const paths = getStorePaths(codexHome);
  let manifest = await loadManifest(codexHome);
  const current = (await pathExists(paths.authPath)) ? await getCurrentAccountContext(codexHome) : null;
  const initialRecord = resolveSnapshotRecord(manifest, label);
  if (current && sameAccountIdentity(initialRecord.summary, current.summary) && initialRecord.fingerprint !== current.fingerprint) {
    await saveCurrentAccount(codexHome, initialRecord.label);
    manifest = await loadManifest(codexHome);
  }

  const record = resolveSnapshotRecord(manifest, label);
  const authPath = path.join(paths.accountsDir, record.snapshotFile);
  const profileHomeDir = record.profileHomeDir ?? path.join('homes', record.label);
  const profileHomePath = path.join(paths.accountsDir, profileHomeDir);
  const auth = (await readOptionalJsonFile(path.join(profileHomePath, 'auth.json'))) ?? (await readJsonFile(authPath));
  const globalState =
    (await readOptionalJsonFile(path.join(profileHomePath, '.codex-global-state.json'))) ??
    (record.globalStateFile
      ? await readOptionalJsonFile(path.join(paths.accountsDir, record.globalStateFile))
      : null);

  return {
    ...record,
    profileHomeDir,
    fingerprint: fingerprintAuth(auth),
    summary: extractAuthSummary(auth),
    globalStateSummary: extractGlobalStateSummary(globalState),
    auth,
    globalState,
    profileHomePath,
  };
}

export async function switchToSavedAccount(codexHome = resolveCodexHome(), label) {
  const paths = getStorePaths(codexHome);
  const saved = await loadSavedAccount(codexHome, label);
  await writeSensitiveJson(paths.authPath, saved.auth);
  if (saved.globalState !== null) {
    await writeSensitiveJson(paths.globalStatePath, saved.globalState);
  }
  await ensureStore(paths);
  await consolidateProfileHomeData(paths.codexHome, saved.profileHomePath);
  await seedProfileHome(paths, { profileHomeDir: saved.profileHomeDir }, saved.auth, saved.globalState);
  return saved;
}

export async function updateProbeResult(codexHome = resolveCodexHome(), label, lastProbe) {
  const paths = getStorePaths(codexHome);
  const manifest = await loadManifest(codexHome);
  const record = resolveSnapshotRecord(manifest, label);

  manifest.snapshots[record.label] = {
    ...record,
    lastProbe,
  };

  await ensureStore(paths);
  await writeSensitiveJson(paths.manifestPath, manifest);
  return manifest.snapshots[record.label];
}

export async function renameSavedAccount(codexHome = resolveCodexHome(), label, nextLabel) {
  const paths = getStorePaths(codexHome);
  const manifest = await loadManifest(codexHome);
  const record = resolveSnapshotRecord(manifest, label);
  const renamedLabel = slugifyLabel(nextLabel);

  if (renamedLabel === record.label) {
    return manifest.snapshots[record.label];
  }

  if (manifest.snapshots[renamedLabel]) {
    throw new Error(`Saved account "${renamedLabel}" already exists`);
  }

  delete manifest.snapshots[record.label];
  manifest.snapshots[renamedLabel] = {
    ...record,
    label: renamedLabel,
  };

  await ensureStore(paths);
  await writeSensitiveJson(paths.manifestPath, manifest);
  return manifest.snapshots[renamedLabel];
}
