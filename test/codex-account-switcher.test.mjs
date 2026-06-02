import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { promisify } from 'node:util';

import {
  decodeJwtPayload,
  extractAuthSummary,
  fingerprintAuth,
} from '../lib/codex-account-switcher/auth.mjs';
import { probeAuthRateLimits } from '../lib/codex-account-switcher/probe.mjs';
import {
  rankSavedAccount,
  sortSavedAccounts,
  slugifyLabel,
} from '../lib/codex-account-switcher/rank.mjs';
import {
  normalizeCodexHome,
  getStorePaths,
  listSavedAccounts,
  loadSavedAccount,
  loadManifest,
  saveCurrentAccount,
  switchToSavedAccount,
  updateProbeResult,
} from '../lib/codex-account-switcher/store.mjs';

const execFileAsync = promisify(execFile);
const cliPath = path.resolve('bin/codex-account.mjs');

function makeJwt(payload) {
  const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${header}.${body}.`;
}

async function makeTempCodexHome() {
  return fs.mkdtemp(path.join(os.tmpdir(), 'codex-account-switcher-'));
}

function buildChatGptAuth({ accountId, planType, email, refreshToken, sessionId = null }) {
  return {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: makeJwt({
        exp: 1_900_000_000,
        ...(sessionId ? { session_id: sessionId } : {}),
        'https://api.openai.com/auth': {
          chatgpt_account_id: accountId,
          chatgpt_plan_type: planType,
        },
        'https://api.openai.com/profile': {
          email,
        },
      }),
      refresh_token: refreshToken,
      account_id: accountId,
    },
  };
}

function stripAnsi(text) {
  return text.replace(/\x1b\[[0-9;]*m/g, '');
}

function withProbeStubs(stubs) {
  return {
    ...process.env,
    CODEX_ACCOUNT_PROBE_CONCURRENCY: '2',
    CODEX_ACCOUNT_PROBE_STUBS: JSON.stringify(stubs),
  };
}

test('probeAuthRateLimits reports the known macOS codex panic as an unavailable live probe', async () => {
  const codexBin = (await execFileAsync('which', ['codex'])).stdout.trim();
  const result = await probeAuthRateLimits({}, {
    codexBin,
    cwd: path.dirname(cliPath),
    timeoutMs: 500,
  });

  assert.equal(result.success, false);
  assert.match(result.error, /Live probing is unavailable/);
  assert.match(result.error, /Attempted to create a NULL object\./);
});

test('decodeJwtPayload reads base64url JWT payloads', () => {
  const token = makeJwt({ sub: 'user-123', exp: 1_900_000_000 });
  assert.deepEqual(decodeJwtPayload(token), { sub: 'user-123', exp: 1_900_000_000 });
});

test('extractAuthSummary derives chatgpt account metadata from stored oauth tokens', () => {
  const accessToken = makeJwt({
    exp: 1_900_000_000,
    'https://api.openai.com/auth': {
      chatgpt_account_id: 'acct-work',
      chatgpt_plan_type: 'pro',
    },
    'https://api.openai.com/profile': {
      email: 'work@example.com',
    },
  });
  const idToken = makeJwt({
    email: 'work@example.com',
  });
  const auth = {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: accessToken,
      id_token: idToken,
      refresh_token: 'refresh-secret',
      account_id: 'acct-work',
    },
    last_refresh: '2026-03-16T09:00:00.000Z',
  };

  assert.deepEqual(extractAuthSummary(auth), {
    authType: 'chatgpt',
    email: 'work@example.com',
    planType: 'pro',
    chatgptAccountId: 'acct-work',
    authSessionId: null,
    tokenExpiresAt: '2030-03-17T17:46:40.000Z',
    lastRefreshAt: '2026-03-16T09:00:00.000Z',
  });
});

test('fingerprintAuth prefers the refresh token for stable chatgpt identity', () => {
  const auth = {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: makeJwt({ sub: 'x' }),
      refresh_token: 'refresh-secret',
    },
  };

  assert.equal(fingerprintAuth(auth).length, 64);
  assert.equal(fingerprintAuth(auth), fingerprintAuth(auth));
});

test('slugifyLabel keeps account labels filesystem-safe', () => {
  assert.equal(slugifyLabel('Work / Plus'), 'work-plus');
  assert.equal(slugifyLabel('  Team__Account  '), 'team-account');
});

test('normalizeCodexHome collapses nested account homes back to the shared root', () => {
  assert.equal(
    normalizeCodexHome('/Users/example/.codex/accounts/homes/work'),
    '/Users/example/.codex',
  );
  assert.equal(normalizeCodexHome('/Users/example/.codex'), '/Users/example/.codex');
});

test('sortSavedAccounts prefers higher plan tiers when live limits are unavailable', () => {
  const sorted = sortSavedAccounts([
    {
      label: 'personal',
      summary: { planType: 'plus', email: 'me@example.com' },
    },
    {
      label: 'work',
      summary: { planType: 'team', email: 'me@work.com' },
    },
  ]);

  assert.equal(sorted[0].label, 'work');
  assert.equal(sorted[1].label, 'personal');
});

test('sortSavedAccounts prefers the more-drained account within the same plan tier', () => {
  const nearlySpent = {
    label: 'busy',
    summary: { planType: 'pro', email: 'busy@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 92, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 40, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  };
  const roomy = {
    label: 'roomy',
    summary: { planType: 'pro', email: 'roomy@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 18, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 15, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  };

  assert.ok(rankSavedAccount(nearlySpent).sortKey > rankSavedAccount(roomy).sortKey);
  assert.equal(sortSavedAccounts([nearlySpent, roomy])[0].label, 'busy');
  assert.equal(sortSavedAccounts([roomy, nearlySpent])[0].label, 'busy');
});

test('sortSavedAccounts drains weekly quota before switching within the same plan tier', () => {
  const weeklyDrained = {
    label: 'weekly-drained',
    summary: { planType: 'pro', email: 'weekly-drained@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 20, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 90, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  };
  const weeklyRoomy = {
    label: 'weekly-roomy',
    summary: { planType: 'pro', email: 'weekly-roomy@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 30, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 55, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  };

  assert.equal(sortSavedAccounts([weeklyRoomy, weeklyDrained])[0].label, 'weekly-drained');
});

test('sortSavedAccounts prefers the account whose quota is closer to reset', () => {
  const now = Math.floor(Date.now() / 1000);
  const closeReset = {
    label: 'close-reset',
    summary: { planType: 'pro', email: 'close-reset@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 60, windowDurationMins: 300, resetsAt: now + 30 * 60 },
        secondary: { usedPercent: 15, windowDurationMins: 10_080, resetsAt: now + 5 * 24 * 60 * 60 },
      },
    },
  };
  const slowerReset = {
    label: 'slower-reset',
    summary: { planType: 'pro', email: 'slower-reset@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 75, windowDurationMins: 300, resetsAt: now + 4 * 60 * 60 },
        secondary: { usedPercent: 15, windowDurationMins: 10_080, resetsAt: now + 5 * 24 * 60 * 60 },
      },
    },
  };

  assert.equal(sortSavedAccounts([slowerReset, closeReset])[0].label, 'close-reset');
});

test('sortSavedAccounts switches away once a live window is fully drained', () => {
  const weeklySpent = {
    label: 'weekly-spent',
    summary: { planType: 'pro', email: 'weekly-spent@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 20, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 100, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  };
  const weeklyRoomy = {
    label: 'weekly-roomy',
    summary: { planType: 'pro', email: 'weekly-roomy@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 30, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 55, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  };

  assert.equal(rankSavedAccount(weeklySpent).isDrained, true);
  assert.equal(sortSavedAccounts([weeklyRoomy, weeklySpent])[0].label, 'weekly-roomy');
});

test('codex-account run --dry-run accepts an explicit saved account label', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const workAuth = buildChatGptAuth({
    accountId: 'acct-work',
    planType: 'team',
    email: 'work@example.com',
    refreshToken: 'refresh-work',
    sessionId: 'authsess_work',
  });
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(workAuth, null, 2));
  await saveCurrentAccount(codexHome, 'work');

  const personalAuth = buildChatGptAuth({
    accountId: 'acct-personal',
    planType: 'plus',
    email: 'personal@example.com',
    refreshToken: 'refresh-personal',
    sessionId: 'authsess_personal',
  });
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(personalAuth, null, 2));
  await saveCurrentAccount(codexHome, 'personal');

  const { stdout } = await execFileAsync(
    process.execPath,
    [cliPath, 'run', 'work', '--dry-run', '--json', '--codex-home', codexHome],
    { cwd: path.dirname(cliPath) },
  );

  const result = JSON.parse(stdout);
  assert.equal(result.selectionMode, 'explicit');
  assert.equal(result.selected.label, 'work');
  assert.equal(result.selected.summary.email, 'work@example.com');
  assert.equal(result.launchCodexHome, codexHome);
});

test('codex-account list shows 5h and weekly reset info in formatted output', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const workAuth = buildChatGptAuth({
    accountId: 'acct-work',
    planType: 'team',
    email: 'work@example.com',
    refreshToken: 'refresh-work',
    sessionId: 'authsess_work',
  });
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(workAuth, null, 2));
  await saveCurrentAccount(codexHome, 'work');
  await updateProbeResult(codexHome, 'work', {
    success: true,
    probedAt: '2026-03-18T10:00:00.000Z',
    rateLimits: {
      primary: { usedPercent: 12, windowDurationMins: 300, resetsAt: 1_900_000_000 },
      secondary: { usedPercent: 30, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
    },
  });

  const { stdout } = await execFileAsync(
    process.execPath,
    [cliPath, 'list', '--no-probe', '--codex-home', codexHome],
    {
      cwd: path.dirname(cliPath),
      env: {
        ...process.env,
        FORCE_COLOR: '1',
      },
    },
  );

  const output = stripAnsi(stdout);
  assert.match(output, /\* work \[TEAM\] \[current\] \[saved probe\]/);
  assert.match(output, /Limits\s+5h 88% free, 7d 70% free/);
  assert.match(output, /5h reset\s+Mar 17, 2030/);
  assert.match(output, /Weekly reset\s+Mar 17, 2030/);
  assert.match(output, /Last probe\s+Mar 18, 2026/);
});

test('codex-account rename updates the saved label', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const workAuth = buildChatGptAuth({
    accountId: 'acct-work',
    planType: 'team',
    email: 'work@example.com',
    refreshToken: 'refresh-work',
    sessionId: 'authsess_work',
  });
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(workAuth, null, 2));
  await saveCurrentAccount(codexHome, 'work');

  const { stdout } = await execFileAsync(
    process.execPath,
    [cliPath, 'rename', 'work', 'work-main', '--json', '--codex-home', codexHome],
    { cwd: path.dirname(cliPath) },
  );

  const renamed = JSON.parse(stdout);
  assert.equal(renamed.label, 'work-main');

  const accounts = await listSavedAccounts(codexHome);
  assert.deepEqual(accounts.map((account) => account.label), ['work-main']);
});

test('saveCurrentAccount snapshots auth and global state and seeds a profile home', async () => {
  const codexHome = await makeTempCodexHome();
  const accessToken = makeJwt({
    exp: 1_900_000_000,
    session_id: 'authsess_personal',
    'https://api.openai.com/auth': {
      chatgpt_account_id: 'acct-personal',
      chatgpt_plan_type: 'plus',
    },
    'https://api.openai.com/profile': {
      email: 'personal@example.com',
    },
  });
  const auth = {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: accessToken,
      refresh_token: 'refresh-personal',
      account_id: 'acct-personal',
    },
    last_refresh: '2026-03-16T09:00:00.000Z',
  };
  const globalState = {
    electronPersistedAtomState: {
      environment: {
        id: 'env-personal',
        machine_id: 'machine-personal',
      },
    },
  };

  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(auth, null, 2));
  await fs.writeFile(path.join(codexHome, '.codex-global-state.json'), JSON.stringify(globalState, null, 2));
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const saved = await saveCurrentAccount(codexHome, 'personal');
  const paths = getStorePaths(codexHome);
  const snapshotAuth = JSON.parse(await fs.readFile(path.join(paths.accountsDir, saved.snapshotFile), 'utf8'));
  const snapshotGlobalState = JSON.parse(await fs.readFile(path.join(paths.accountsDir, saved.globalStateFile), 'utf8'));
  const profileAuth = JSON.parse(await fs.readFile(path.join(paths.accountsDir, saved.profileHomeDir, 'auth.json'), 'utf8'));
  const profileGlobalState = JSON.parse(
    await fs.readFile(path.join(paths.accountsDir, saved.profileHomeDir, '.codex-global-state.json'), 'utf8'),
  );
  const linkedConfigPath = path.join(paths.accountsDir, saved.profileHomeDir, 'config.toml');

  assert.equal(saved.label, 'personal');
  assert.equal(saved.summary.authSessionId, 'authsess_personal');
  assert.equal(saved.globalStateSummary.environmentId, 'env-personal');
  assert.equal(saved.globalStateSummary.machineId, 'machine-personal');
  assert.deepEqual(snapshotAuth, auth);
  assert.deepEqual(snapshotGlobalState, globalState);
  assert.deepEqual(profileAuth, auth);
  assert.deepEqual(profileGlobalState, globalState);
  assert.equal(await fs.readlink(linkedConfigPath), path.join(codexHome, 'config.toml'));
});

test('listSavedAccounts refreshes a saved snapshot after the same account re-authenticates', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const originalAuth = buildChatGptAuth({
    accountId: 'acct-personal',
    planType: 'plus',
    email: 'personal@example.com',
    refreshToken: 'refresh-original',
    sessionId: 'authsess_original',
  });
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(originalAuth, null, 2));
  await saveCurrentAccount(codexHome, 'personal');

  const refreshedAuth = {
    ...buildChatGptAuth({
      accountId: 'acct-personal',
      planType: 'plus',
      email: 'personal@example.com',
      refreshToken: 'refresh-rotated',
      sessionId: 'authsess_rotated',
    }),
    last_refresh: '2026-03-25T20:01:24.712798Z',
  };
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(refreshedAuth, null, 2));

  const accounts = await listSavedAccounts(codexHome);

  assert.equal(accounts.length, 1);
  assert.equal(accounts[0].label, 'personal');
  assert.equal(accounts[0].isCurrent, true);
  assert.equal(accounts[0].fingerprint, fingerprintAuth(refreshedAuth));
  assert.equal(accounts[0].summary.authSessionId, 'authsess_rotated');
  assert.equal(accounts[0].summary.lastRefreshAt, '2026-03-25T20:01:24.712798Z');

  const manifest = await loadManifest(codexHome);
  assert.equal(manifest.snapshots.personal.fingerprint, fingerprintAuth(refreshedAuth));
  assert.equal(manifest.snapshots.personal.summary.authSessionId, 'authsess_rotated');
});

test('loadSavedAccount returns the refreshed auth after the current account rotates tokens', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const originalAuth = buildChatGptAuth({
    accountId: 'acct-personal',
    planType: 'plus',
    email: 'personal@example.com',
    refreshToken: 'refresh-original',
    sessionId: 'authsess_original',
  });
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(originalAuth, null, 2));
  await saveCurrentAccount(codexHome, 'personal');

  const refreshedAuth = {
    ...buildChatGptAuth({
      accountId: 'acct-personal',
      planType: 'plus',
      email: 'personal@example.com',
      refreshToken: 'refresh-rotated',
      sessionId: 'authsess_rotated',
    }),
    last_refresh: '2026-03-25T20:01:24.712798Z',
  };
  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(refreshedAuth, null, 2));

  const saved = await loadSavedAccount(codexHome, 'personal');

  assert.deepEqual(saved.auth, refreshedAuth);
  assert.equal(saved.fingerprint, fingerprintAuth(refreshedAuth));
  assert.equal(saved.summary.authSessionId, 'authsess_rotated');
});

test('switchToSavedAccount restores both auth.json and .codex-global-state.json', async () => {
  const codexHome = await makeTempCodexHome();
  const originalAuth = {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: makeJwt({
        exp: 1_900_000_000,
        session_id: 'authsess_saved',
        'https://api.openai.com/auth': {
          chatgpt_account_id: 'acct-saved',
          chatgpt_plan_type: 'plus',
        },
      }),
      refresh_token: 'refresh-saved',
      account_id: 'acct-saved',
    },
  };
  const originalGlobalState = {
    electronPersistedAtomState: {
      environment: {
        id: 'env-saved',
        machine_id: 'machine-saved',
      },
    },
  };

  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(originalAuth, null, 2));
  await fs.writeFile(path.join(codexHome, '.codex-global-state.json'), JSON.stringify(originalGlobalState, null, 2));

  await saveCurrentAccount(codexHome, 'saved');

  const replacedAuth = {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: makeJwt({
        exp: 1_900_000_100,
        session_id: 'authsess_replaced',
        'https://api.openai.com/auth': {
          chatgpt_account_id: 'acct-replaced',
          chatgpt_plan_type: 'plus',
        },
      }),
      refresh_token: 'refresh-replaced',
      account_id: 'acct-replaced',
    },
  };
  const replacedGlobalState = {
    electronPersistedAtomState: {
      environment: {
        id: 'env-replaced',
        machine_id: 'machine-replaced',
      },
    },
  };

  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(replacedAuth, null, 2));
  await fs.writeFile(path.join(codexHome, '.codex-global-state.json'), JSON.stringify(replacedGlobalState, null, 2));

  await switchToSavedAccount(codexHome, 'saved');

  const currentAuth = JSON.parse(await fs.readFile(path.join(codexHome, 'auth.json'), 'utf8'));
  const currentGlobalState = JSON.parse(await fs.readFile(path.join(codexHome, '.codex-global-state.json'), 'utf8'));

  assert.deepEqual(currentAuth, originalAuth);
  assert.deepEqual(currentGlobalState, originalGlobalState);
});

test('switchToSavedAccount consolidates stranded profile-home sessions back into the shared home', async () => {
  const codexHome = await makeTempCodexHome();
  const savedAuth = {
    OPENAI_API_KEY: null,
    tokens: {
      access_token: makeJwt({
        exp: 1_900_000_000,
        session_id: 'authsess_saved',
        'https://api.openai.com/auth': {
          chatgpt_account_id: 'acct-saved',
          chatgpt_plan_type: 'plus',
        },
        'https://api.openai.com/profile': {
          email: 'saved@example.com',
        },
      }),
      refresh_token: 'refresh-saved',
      account_id: 'acct-saved',
    },
  };

  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(savedAuth, null, 2));
  await saveCurrentAccount(codexHome, 'saved');

  const paths = getStorePaths(codexHome);
  const profileHomePath = path.join(paths.accountsDir, 'homes', 'saved');
  const historyPath = path.join(profileHomePath, 'history.jsonl');
  const sessionsPath = path.join(profileHomePath, 'sessions');
  const shellSnapshotsPath = path.join(profileHomePath, 'shell_snapshots');
  const sessionId = '019cf900-1dc4-7dd3-be15-e19adfa96b84';
  const sessionRelativePath = path.join('2026', '03', '17', `rollout-2026-03-17T00-34-20-${sessionId}.jsonl`);
  const sessionPath = path.join(sessionsPath, sessionRelativePath);

  await fs.rm(historyPath, { force: true });
  await fs.rm(sessionsPath, { recursive: true, force: true });
  await fs.rm(shellSnapshotsPath, { recursive: true, force: true });
  await fs.writeFile(
    historyPath,
    `${JSON.stringify({
      session_id: sessionId,
      ts: 1_773_704_124,
      text: 'Recover old chats from the split profile home',
    })}\n`,
  );
  await fs.mkdir(path.dirname(sessionPath), { recursive: true });
  await fs.writeFile(
    sessionPath,
    [
      JSON.stringify({
        parent_id: null,
        is_sidechain: false,
        user_type: 'external',
        cwd: '/Users/example/project',
        session_id: sessionId,
        version: '1.0.0',
        git_branch: 'main',
        type: 'summary',
        summary: 'Recovered archived session',
      }),
      JSON.stringify({
        parent_id: null,
        is_sidechain: false,
        user_type: 'external',
        cwd: '/Users/example/project',
        session_id: sessionId,
        version: '1.0.0',
        git_branch: 'main',
        type: 'assistant',
        message: { role: 'assistant', content: [{ type: 'text', text: 'Recovered archived session' }] },
      }),
    ].join('\n'),
  );
  await fs.mkdir(path.join(profileHomePath, 'shell_snapshots'), { recursive: true });
  await fs.writeFile(path.join(profileHomePath, 'shell_snapshots', `${sessionId}.json`), JSON.stringify({ session_id: sessionId }, null, 2));

  await switchToSavedAccount(codexHome, 'saved');

  const sharedHistory = await fs.readFile(path.join(codexHome, 'sessions', sessionRelativePath), 'utf8');
  const sharedSnapshot = await fs.readFile(path.join(codexHome, 'shell_snapshots', `${sessionId}.json`), 'utf8');

  assert.match(sharedHistory, /Recovered archived session/);
  assert.match(sharedSnapshot, /session_id/);
});

test('codex-account list can return opt-in probe diagnostics for the real probe path', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  const accountDefs = [
    { label: 'work', email: 'work@example.com', planType: 'team', refreshToken: 'refresh-work' },
    { label: 'personal', email: 'personal@example.com', planType: 'plus', refreshToken: 'refresh-personal' },
    { label: 'shared', email: 'shared@example.com', planType: 'pro', refreshToken: 'refresh-shared' },
  ];

  for (const def of accountDefs) {
    await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(buildChatGptAuth({
      accountId: `acct-${def.label}`,
      planType: def.planType,
      email: def.email,
      refreshToken: def.refreshToken,
      sessionId: `authsess_${def.label}`,
    }), null, 2));
    await saveCurrentAccount(codexHome, def.label);
    await fs.mkdir(path.join(codexHome, 'accounts', 'homes', def.label, 'shell_snapshots'), { recursive: true });
  }

  const startedAt = Date.now();
  const { stdout } = await execFileAsync(
    process.execPath,
    [cliPath, 'list', '--json', '--codex-home', codexHome],
    {
      cwd: path.dirname(cliPath),
      env: {
        ...withProbeStubs({
          work: { delayMs: 250, rateLimits: { primary: { usedPercent: 20, windowDurationMins: 300, resetsAt: 1_900_000_000 } } },
          personal: { delayMs: 250, rateLimits: { primary: { usedPercent: 50, windowDurationMins: 300, resetsAt: 1_900_000_000 } } },
          shared: { delayMs: 250, rateLimits: { primary: { usedPercent: 70, windowDurationMins: 300, resetsAt: 1_900_000_000 } } },
        }),
        CODEX_ACCOUNT_DEBUG_PROBE: '1',
      },
    },
  );

  const payload = JSON.parse(stdout);
  assert.ok(payload.accounts, stdout);
  assert.ok(payload.diagnostics, stdout);
  assert.equal(payload.accounts.length, 3);
  assert.deepEqual(payload.accounts.map((account) => account.label).sort(), ['personal', 'shared', 'work']);
  assert.ok(payload.accounts.every((account) => account.probeSource === 'live'));
  assert.equal(payload.diagnostics.enabled, true);
  assert.equal(payload.diagnostics.accountCount, 3);
  assert.equal(payload.diagnostics.concurrency, 2);
  assert.ok(payload.diagnostics.totalDurationMs >= 250);
  assert.ok(payload.diagnostics.totalDurationMs < 1000);
  assert.ok(payload.diagnostics.totalDurationMs <= Date.now() - startedAt + 200);
  assert.deepEqual(
    payload.diagnostics.steps.map((step) => step.name).sort(),
    ['loadSavedAccount', 'loadSavedAccount', 'loadSavedAccount', 'probeAuthRateLimits', 'probeAuthRateLimits', 'probeAuthRateLimits'],
  );
  assert.ok(payload.diagnostics.steps.every((step) => step.durationMs >= 0));
  assert.ok(payload.diagnostics.steps.filter((step) => step.name === 'probeAuthRateLimits').every((step) => step.durationMs >= 200));
  assert.deepEqual(
    payload.diagnostics.results.map((result) => ({ label: result.label, success: result.success })).sort((left, right) => left.label.localeCompare(right.label)),
    [
      { label: 'personal', success: true },
      { label: 'shared', success: true },
      { label: 'work', success: true },
    ],
  );
});

test('codex-account best defaults to live probing for saved accounts', async () => {
  const codexHome = await makeTempCodexHome();
  await fs.writeFile(path.join(codexHome, 'config.toml'), 'model = "gpt-5.4"\n');

  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(buildChatGptAuth({
    accountId: 'acct-work',
    planType: 'team',
    email: 'work@example.com',
    refreshToken: 'refresh-work',
    sessionId: 'authsess_work',
  }), null, 2));
  await saveCurrentAccount(codexHome, 'work');

  await fs.writeFile(path.join(codexHome, 'auth.json'), JSON.stringify(buildChatGptAuth({
    accountId: 'acct-personal',
    planType: 'plus',
    email: 'personal@example.com',
    refreshToken: 'refresh-personal',
    sessionId: 'authsess_personal',
  }), null, 2));
  await saveCurrentAccount(codexHome, 'personal');

  const { stdout } = await execFileAsync(
    process.execPath,
    [cliPath, 'best', '--json', '--codex-home', codexHome],
    {
      cwd: path.dirname(cliPath),
      env: withProbeStubs({
        work: { delayMs: 250, rateLimits: { primary: { usedPercent: 20, windowDurationMins: 300, resetsAt: 1_900_000_000 } } },
        personal: { delayMs: 250, rateLimits: { primary: { usedPercent: 70, windowDurationMins: 300, resetsAt: 1_900_000_000 } } },
      }),
    },
  );

  const best = JSON.parse(stdout);
  assert.equal(best.label, 'work');
  assert.equal(best.probeSource, 'live');
});
