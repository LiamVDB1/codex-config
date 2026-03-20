import { spawn } from 'node:child_process';

import { formatRateLimits, sortSavedAccounts } from './rank.mjs';
import { probeAuthRateLimits } from './probe.mjs';
import {
  listSavedAccounts,
  loadSavedAccount,
  switchToSavedAccount,
  updateProbeResult,
} from './store.mjs';

async function enrichWithLiveProbe(codexHome, accounts, enabled) {
  if (!enabled) {
    return accounts;
  }

  const updated = [];
  for (const entry of accounts) {
    const saved = await loadSavedAccount(codexHome, entry.label);
    const probe = await probeAuthRateLimits(saved.auth, { cwd: codexHome });
    await updateProbeResult(codexHome, entry.label, probe);
    updated.push({
      ...entry,
      lastProbe: probe,
      probeSource: 'live',
    });
  }

  return updated;
}

export async function chooseBestAccount(codexHome, { probe = true } = {}) {
  const accounts = await listSavedAccounts(codexHome);
  const enriched = await enrichWithLiveProbe(codexHome, accounts, probe);
  return sortSavedAccounts(enriched)[0] ?? null;
}

export async function runCodexWithBestAccount(codexHome, codexArgs, { probe = true, dryRun = false } = {}) {
  const best = await chooseBestAccount(codexHome, { probe });

  if (!best) {
    if (dryRun) {
      return { best: null, spawned: false, launchCodexHome: codexHome };
    }

    const child = spawn('codex', codexArgs, {
      cwd: process.cwd(),
      stdio: 'inherit',
      env: {
        ...process.env,
        CODEX_HOME: codexHome,
      },
    });
    const exitCode = await new Promise((resolve) => child.once('exit', resolve));
    return { best: null, spawned: true, exitCode: exitCode ?? 1 };
  }

  const saved = await switchToSavedAccount(codexHome, best.label);
  const launchCodexHome = codexHome;

  if (dryRun) {
    return {
      best,
      spawned: false,
      launchCodexHome,
      summary: `${best.label} (${best.summary?.email ?? 'unknown'}) ${formatRateLimits(best.lastProbe?.rateLimits)}`,
    };
  }

  const child = spawn('codex', codexArgs, {
    cwd: process.cwd(),
    stdio: 'inherit',
    env: {
      ...process.env,
      CODEX_HOME: launchCodexHome,
    },
  });
  const exitCode = await new Promise((resolve) => child.once('exit', resolve));
  return { best, spawned: true, exitCode: exitCode ?? 1 };
}
