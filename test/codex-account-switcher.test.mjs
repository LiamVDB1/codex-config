import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  decodeJwtPayload,
  extractAuthSummary,
  fingerprintAuth,
} from '../lib/codex-account-switcher/auth.mjs';
import {
  rankSavedAccount,
  sortSavedAccounts,
  slugifyLabel,
} from '../lib/codex-account-switcher/rank.mjs';
import {
  normalizeCodexHome,
  getStorePaths,
  saveCurrentAccount,
  switchToSavedAccount,
} from '../lib/codex-account-switcher/store.mjs';

function makeJwt(payload) {
  const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${header}.${body}.`;
}

async function makeTempCodexHome() {
  return fs.mkdtemp(path.join(os.tmpdir(), 'codex-account-switcher-'));
}

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

test('rankSavedAccount uses live quota headroom as the tie-breaker within the same plan', () => {
  const nearlySpent = rankSavedAccount({
    label: 'busy',
    summary: { planType: 'pro', email: 'busy@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 92, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 40, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  });
  const roomy = rankSavedAccount({
    label: 'roomy',
    summary: { planType: 'pro', email: 'roomy@example.com' },
    lastProbe: {
      success: true,
      rateLimits: {
        primary: { usedPercent: 18, windowDurationMins: 300, resetsAt: 1_900_000_000 },
        secondary: { usedPercent: 15, windowDurationMins: 10_080, resetsAt: 1_900_000_000 },
      },
    },
  });

  assert.ok(roomy.sortKey > nearlySpent.sortKey);
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
        timestamp: '2026-03-17T00:34:20.000Z',
        type: 'session_meta',
        payload: {
          id: sessionId,
          timestamp: '2026-03-17T00:34:20.000Z',
        },
      }),
      JSON.stringify({
        timestamp: '2026-03-17T00:34:21.000Z',
        type: 'response_item',
        payload: {
          type: 'message',
          role: 'user',
          content: [{ type: 'input_text', text: 'Recover old chats from the split profile home' }],
        },
      }),
      '',
    ].join('\n'),
  );
  await fs.mkdir(shellSnapshotsPath, { recursive: true });
  await fs.writeFile(path.join(shellSnapshotsPath, `${sessionId}.sh`), 'echo test\n');

  await switchToSavedAccount(codexHome, 'saved');

  assert.match(await fs.readFile(path.join(codexHome, 'history.jsonl'), 'utf8'), /Recover old chats/);
  assert.equal(
    JSON.parse(await fs.readFile(path.join(codexHome, 'session_index.jsonl'), 'utf8').then((text) =>
      text
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .find((line) => line.includes(sessionId)),
    )).thread_name,
    'Recover old chats from the split profile home',
  );
  await fs.access(path.join(codexHome, 'sessions', sessionRelativePath));
  await fs.access(path.join(codexHome, 'shell_snapshots', `${sessionId}.sh`));
  assert.equal(await fs.readlink(historyPath), path.join(codexHome, 'history.jsonl'));
  assert.equal(await fs.readlink(sessionsPath), path.join(codexHome, 'sessions'));
  assert.equal(await fs.readlink(shellSnapshotsPath), path.join(codexHome, 'shell_snapshots'));
});
