import { spawn } from 'node:child_process';
import { performance } from 'node:perf_hooks';

import { formatRateLimits, sortSavedAccounts } from './rank.mjs';
import { probeAuthRateLimits } from './probe.mjs';
import {
  listSavedAccounts,
  loadSavedAccount,
  switchToSavedAccount,
  updateProbeResult,
} from './store.mjs';

function getProbeConcurrency() {
  const raw = Number.parseInt(process.env.CODEX_ACCOUNT_PROBE_CONCURRENCY ?? '', 10);
  if (!Number.isFinite(raw) || raw < 1) {
    return 4;
  }

  return raw;
}

async function measureProbeStep(label, name, diagnostics, action) {
  const startedAt = performance.now();
  try {
    return await action();
  } finally {
    if (diagnostics) {
      diagnostics.steps.push({
        label,
        name,
        durationMs: Math.round((performance.now() - startedAt) * 1000) / 1000,
      });
    }
  }
}

async function probeAccount(codexHome, entry, diagnostics = null) {
  try {
    const saved = await measureProbeStep(entry.label, 'loadSavedAccount', diagnostics, () =>
      loadSavedAccount(codexHome, entry.label),
    );
    const probe = await measureProbeStep(entry.label, 'probeAuthRateLimits', diagnostics, () =>
      probeAuthRateLimits(saved.auth, { cwd: codexHome }),
    );
    const result = {
      ...entry,
      ...saved,
      lastProbe: probe,
      probeSource: 'live',
      persistLabel: saved.label,
    };

    if (diagnostics) {
      diagnostics.results.push({
        label: result.label,
        success: probe.success,
        error: probe.success ? null : probe.error ?? null,
      });
    }

    return result;
  } catch (error) {
    const result = {
      ...entry,
      lastProbe: {
        success: false,
        probedAt: new Date().toISOString(),
        error: error.message,
      },
      probeSource: 'live',
      persistLabel: entry.label,
    };

    if (diagnostics) {
      diagnostics.results.push({
        label: result.label,
        success: false,
        error: error.message,
      });
    }

    return result;
  }
}

async function safeUpdateProbeResult(codexHome, entry) {
  await updateProbeResult(codexHome, entry.persistLabel ?? entry.label, entry.lastProbe).catch(() => {});
}

async function persistProbeResults(codexHome, updated) {
  for (const entry of updated) {
    await safeUpdateProbeResult(codexHome, entry);
  }
}

export async function enrichWithLiveProbe(codexHome, accounts, enabled, { diagnostics = false } = {}) {
  if (!enabled) {
    return diagnostics ? { accounts, diagnostics: null } : accounts;
  }

  const concurrency = Math.min(getProbeConcurrency(), accounts.length || 1);
  const updated = new Array(accounts.length);
  const probeDiagnostics = diagnostics
    ? {
        enabled: true,
        accountCount: accounts.length,
        concurrency,
        steps: [],
        results: [],
        totalDurationMs: 0,
      }
    : null;
  const startedAt = performance.now();
  let cursor = 0;

  async function worker() {
    while (true) {
      const index = cursor;
      cursor += 1;
      if (index >= accounts.length) {
        return;
      }

      updated[index] = await probeAccount(codexHome, accounts[index], probeDiagnostics);
    }
  }

  await Promise.all(Array.from({ length: concurrency }, () => worker()));
  await persistProbeResults(codexHome, updated.filter(Boolean));
  const sortedAccounts = sortSavedAccounts(updated);

  if (!probeDiagnostics) {
    return sortedAccounts;
  }

  probeDiagnostics.totalDurationMs = Math.round((performance.now() - startedAt) * 1000) / 1000;
  return {
    accounts: sortedAccounts,
    diagnostics: probeDiagnostics,
  };
}

export async function chooseBestAccount(codexHome, { probe = true } = {}) {
  const accounts = await listSavedAccounts(codexHome);
  const enriched = await enrichWithLiveProbe(codexHome, accounts, probe);
  const sortedAccounts = Array.isArray(enriched) ? enriched : enriched.accounts;
  return sortSavedAccounts(sortedAccounts)[0] ?? null;
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
