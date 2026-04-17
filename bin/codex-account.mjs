#!/usr/bin/env node

import { spawn } from 'node:child_process';

import { formatRateLimits, sortSavedAccounts } from '../lib/codex-account-switcher/rank.mjs';
import { probeAuthRateLimits } from '../lib/codex-account-switcher/probe.mjs';
import { chooseBestAccount, runCodexWithBestAccount } from '../lib/codex-account-switcher/runner.mjs';
import {
  getCurrentAccountContext,
  listSavedAccounts,
  loadSavedAccount,
  renameSavedAccount,
  resolveCodexHome,
  saveCurrentAccount,
  switchToSavedAccount,
  updateProbeResult,
} from '../lib/codex-account-switcher/store.mjs';

function printHelp() {
  console.log(`Usage: codex-account <command> [options]

Commands:
  current                 Show the currently active Codex account
  save [label]            Save the current auth.json as a switchable snapshot
  list [--no-probe]       List saved accounts and refresh live rate limits by default
  rename <old> <new>      Rename a saved account label
  switch <label>          Replace auth.json with a saved account snapshot
  probe [label|all]       Refresh live rate-limit data for one or all saved accounts
  best [--no-probe]       Show which saved account would be selected
  switch-best [--no-probe]
                         Switch to the best saved account
  run [label] [--no-probe] [--] [codex args...]
                         Launch codex with a specific saved account label, or the best account if no label matches

Environment:
  CODEX_HOME              Override the Codex home directory (default: ~/.codex)
`);
}

const ANSI = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
};

function supportsColor() {
  if (process.env.NO_COLOR) {
    return false;
  }

  if (process.env.FORCE_COLOR && process.env.FORCE_COLOR !== '0') {
    return true;
  }

  return Boolean(process.stdout.isTTY);
}

function colorize(text, ...styles) {
  if (!supportsColor() || !styles.length) {
    return text;
  }

  return `${styles.map((style) => ANSI[style] ?? '').join('')}${text}${ANSI.reset}`;
}

function formatDateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'unknown';
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

function formatRelativeTime(value) {
  const target = value instanceof Date ? value.getTime() : new Date(value).getTime();
  if (!Number.isFinite(target)) {
    return 'unknown';
  }

  let remainingMs = target - Date.now();
  const tense = remainingMs >= 0 ? 'future' : 'past';
  remainingMs = Math.abs(remainingMs);

  const minuteMs = 60 * 1000;
  const hourMs = 60 * minuteMs;
  const dayMs = 24 * hourMs;
  const weekMs = 7 * dayMs;

  const parts = [];
  const units = [
    ['w', weekMs],
    ['d', dayMs],
    ['h', hourMs],
    ['m', minuteMs],
  ];

  for (const [suffix, unitMs] of units) {
    if (parts.length === 2) {
      break;
    }

    const amount = Math.floor(remainingMs / unitMs);
    if (!amount) {
      continue;
    }

    parts.push(`${amount}${suffix}`);
    remainingMs -= amount * unitMs;
  }

  if (!parts.length) {
    return tense === 'future' ? 'in <1m' : '<1m ago';
  }

  return tense === 'future' ? `in ${parts.join(' ')}` : `${parts.join(' ')} ago`;
}

function formatPlanBadge(planType) {
  const normalized = String(planType ?? 'unknown').toLowerCase();
  const color =
    normalized === 'enterprise' || normalized === 'business' || normalized === 'team'
      ? 'green'
      : normalized === 'pro' || normalized === 'plus'
        ? 'cyan'
        : normalized === 'free'
          ? 'yellow'
          : 'gray';
  return colorize(`[${normalized.toUpperCase()}]`, color);
}

function formatStatusBadge(account) {
  if (account.isCurrent) {
    return colorize('[current]', 'green');
  }

  return colorize('[saved]', 'gray');
}

function formatProbeBadge(account) {
  if (account.lastProbe?.success) {
    if (account.probeSource === 'live') {
      return colorize('[live probe]', 'green');
    }

    return colorize('[saved probe]', 'blue');
  }

  if (account.lastProbe?.success === false) {
    return colorize('[probe failed]', 'red');
  }

  return colorize('[no probe]', 'gray');
}

function getLimitHealthColor(account) {
  const remaining = typeof account.bottleneckRemaining === 'number' ? account.bottleneckRemaining : null;
  if (remaining === null || remaining < 0) {
    return 'gray';
  }

  if (remaining >= 50) {
    return 'green';
  }

  if (remaining >= 20) {
    return 'yellow';
  }

  return 'red';
}

function findFiveHourResetWindow(rateLimits) {
  const windows = [rateLimits?.primary, rateLimits?.secondary].filter(
    (window) => window && typeof window.resetsAt === 'number',
  );
  if (!windows.length) {
    return null;
  }

  const exactFiveHour = windows.find((window) => window.windowDurationMins === 300);
  if (exactFiveHour) {
    return exactFiveHour;
  }

  const shortWindow = windows
    .filter((window) => typeof window.windowDurationMins === 'number' && window.windowDurationMins < 1_440)
    .sort((left, right) => Math.abs(left.windowDurationMins - 300) - Math.abs(right.windowDurationMins - 300));

  return shortWindow[0] ?? windows[0];
}

function findWeeklyResetWindow(rateLimits) {
  const windows = [rateLimits?.primary, rateLimits?.secondary].filter(
    (window) => window && typeof window.resetsAt === 'number',
  );
  if (!windows.length) {
    return null;
  }

  const exactWeekly = windows.find((window) => window.windowDurationMins === 10_080);
  if (exactWeekly) {
    return exactWeekly;
  }

  const multiDay = windows
    .filter((window) => typeof window.windowDurationMins === 'number' && window.windowDurationMins >= 1_440)
    .sort((left, right) => Math.abs(left.windowDurationMins - 10_080) - Math.abs(right.windowDurationMins - 10_080));

  return multiDay[0] ?? windows[0];
}

function formatResetAt(window) {
  if (!window) {
    return colorize('unavailable', 'gray');
  }

  const resetAt = window.resetsAt > 1_000_000_000_000 ? window.resetsAt : window.resetsAt * 1000;
  return `${colorize(formatDateTime(resetAt), 'blue')} ${colorize(`(${formatRelativeTime(resetAt)})`, 'dim')}`;
}

function formatFiveHourReset(rateLimits) {
  return formatResetAt(findFiveHourResetWindow(rateLimits));
}

function formatWeeklyReset(rateLimits) {
  return formatResetAt(findWeeklyResetWindow(rateLimits));
}

function renderSavedAccount(account, { showProbeError = false } = {}) {
  const enriched = account.sortKey === undefined ? sortSavedAccounts([account])[0] : account;
  const email = enriched.summary?.email ?? 'api-key login';
  const plan = enriched.summary?.planType ?? enriched.summary?.authType ?? 'unknown';
  const limits = enriched.lastProbe?.success
    ? colorize(formatRateLimits(enriched.lastProbe?.rateLimits), getLimitHealthColor(enriched))
    : enriched.lastProbe?.success === false
      ? colorize('probe failed', 'red')
      : colorize('no live limit data', 'gray');
  const lines = [
    `${enriched.isCurrent ? colorize('*', 'green') : colorize('-', 'gray')} ${colorize(enriched.label, 'bold', 'cyan')} ${formatPlanBadge(plan)} ${formatStatusBadge(enriched)} ${formatProbeBadge(enriched)}`,
    `  ${colorize('Email', 'dim')}        ${email}`,
    `  ${colorize('Limits', 'dim')}       ${limits}`,
    `  ${colorize('5h reset', 'dim')}     ${formatFiveHourReset(enriched.lastProbe?.rateLimits)}`,
    `  ${colorize('Weekly reset', 'dim')} ${formatWeeklyReset(enriched.lastProbe?.rateLimits)}`,
  ];

  if (enriched.lastProbe?.probedAt) {
    lines.push(`  ${colorize('Last probe', 'dim')}   ${formatDateTime(enriched.lastProbe.probedAt)}`);
  }

  if (showProbeError && enriched.lastProbe?.success === false && enriched.lastProbe.error) {
    lines.push(`  ${colorize('Probe error', 'dim')} ${colorize(enriched.lastProbe.error, 'red')}`);
  }

  return lines.join('\n');
}

function parseCommandLine(argv) {
  const flags = new Set();
  const values = new Map();
  const positionals = [];
  let passthrough = [];
  let afterSeparator = false;

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (afterSeparator) {
      passthrough.push(arg);
      continue;
    }

    if (arg === '--') {
      afterSeparator = true;
      continue;
    }

    if (arg === '--json' || arg === '--probe' || arg === '--dry-run' || arg === '--no-probe') {
      flags.add(arg);
      continue;
    }

    if (arg === '--codex-home') {
      const value = argv[index + 1];
      if (!value) {
        throw new Error('--codex-home requires a value');
      }
      values.set('codexHome', value);
      index += 1;
      continue;
    }

    positionals.push(arg);
  }

  return {
    flags,
    values,
    positionals,
    passthrough,
  };
}

function printCurrent(context, asJson) {
  if (asJson) {
    console.log(JSON.stringify(context, null, 2));
    return;
  }

  const summary = context.summary;
  console.log(
    `${colorize('Active account:', 'bold')} ${colorize(summary.email ?? 'api-key login', 'cyan')} ${formatPlanBadge(summary.planType ?? summary.authType)}`,
  );
  if (summary.chatgptAccountId) {
    console.log(`Account id: ${summary.chatgptAccountId}`);
  }
  if (summary.authSessionId) {
    console.log(`Auth session: ${summary.authSessionId}`);
  }
  if (summary.tokenExpiresAt) {
    console.log(`Access token expires: ${summary.tokenExpiresAt}`);
  }
  if (context.globalStateSummary?.environmentId) {
    console.log(`Environment id: ${context.globalStateSummary.environmentId}`);
  }
  if (context.globalStateSummary?.machineId) {
    console.log(`Machine id: ${context.globalStateSummary.machineId}`);
  }
}

function printAccounts(accounts, asJson) {
  if (asJson) {
    console.log(JSON.stringify(accounts, null, 2));
    return;
  }

  if (!accounts.length) {
    console.log('No saved accounts yet. Log into an account, then run `codex-account save [label]`.');
    return;
  }

  console.log(sortSavedAccounts(accounts).map((account) => renderSavedAccount(account)).join('\n\n'));
}

async function probeOne(codexHome, accountOrLabel) {
  const savedAccounts = typeof accountOrLabel === 'string' ? await listSavedAccounts(codexHome) : null;
  const account =
    typeof accountOrLabel === 'string'
      ? savedAccounts.find((entry) => entry.label === accountOrLabel) ?? { label: accountOrLabel }
      : accountOrLabel;
  const saved = await loadSavedAccount(codexHome, account.label);
  const probe = await probeAuthRateLimits(saved.auth, { cwd: codexHome });
  await updateProbeResult(codexHome, saved.label, probe);
  return {
    ...saved,
    ...account,
    lastProbe: probe,
    probeSource: 'live',
  };
}

async function findSavedAccountLabel(codexHome, requestedLabel) {
  const requested = String(requestedLabel ?? '').trim();
  if (!requested) {
    return null;
  }

  const lowerRequested = requested.toLowerCase();
  return (
    (await listSavedAccounts(codexHome)).find((account) => String(account.label).toLowerCase() === lowerRequested)?.label ??
    null
  );
}

async function runCodexWithSavedAccount(codexHome, label, codexArgs, { dryRun = false } = {}) {
  const saved = await loadSavedAccount(codexHome, label);
  const launchCodexHome = codexHome;

  if (dryRun) {
    return {
      selectionMode: 'explicit',
      selected: saved,
      spawned: false,
      launchCodexHome,
    };
  }

  await switchToSavedAccount(codexHome, saved.label);
  const child = spawn('codex', codexArgs, {
    cwd: process.cwd(),
    stdio: 'inherit',
    env: {
      ...process.env,
      CODEX_HOME: launchCodexHome,
    },
  });
  const exitCode = await new Promise((resolve) => child.once('exit', resolve));
  return {
    selectionMode: 'explicit',
    selected: saved,
    spawned: true,
    exitCode: exitCode ?? 1,
    launchCodexHome,
  };
}

async function main(argv = process.argv.slice(2)) {
  let parsed;
  try {
    parsed = parseCommandLine(argv);
  } catch (error) {
    console.error(`Error: ${error.message}`);
    printHelp();
    return 1;
  }

  const [command = 'help', firstArg, ...restArgs] = parsed.positionals;
  const asJson = parsed.flags.has('--json');
  const codexHome = resolveCodexHome(parsed.values.get('codexHome'));
  const defaultsToLiveProbe = command === 'list' || command === 'best' || command === 'switch-best' || command === 'run';
  const probe = parsed.flags.has('--no-probe') ? false : parsed.flags.has('--probe') || defaultsToLiveProbe;

  try {
    if (command === 'help' || command === '--help' || command === '-h') {
      printHelp();
      return 0;
    }

    if (command === 'current') {
      printCurrent(await getCurrentAccountContext(codexHome), asJson);
      return 0;
    }

    if (command === 'save') {
      const saved = await saveCurrentAccount(codexHome, firstArg);
      if (asJson) {
        console.log(JSON.stringify(saved, null, 2));
      } else {
        console.log(`Saved current account as "${saved.label}"`);
        if (saved.profileHomeDir) {
          console.log(`Profile home: ${saved.profileHomeDir}`);
        }
      }
      return 0;
    }

    if (command === 'list') {
      const accounts = await listSavedAccounts(codexHome);
      if (!probe) {
        printAccounts(accounts, asJson);
        return 0;
      }

      const refreshed = [];
      for (const account of accounts) {
        refreshed.push(await probeOne(codexHome, account));
      }
      printAccounts(refreshed, asJson);
      return 0;
    }

    if (command === 'rename') {
      const nextLabel = restArgs[0];
      if (!firstArg || !nextLabel) {
        throw new Error('rename requires the current label and the new label');
      }

      const renamed = await renameSavedAccount(codexHome, firstArg, nextLabel);
      if (asJson) {
        console.log(JSON.stringify(renamed, null, 2));
      } else {
        console.log(`Renamed "${firstArg}" to "${renamed.label}"`);
      }
      return 0;
    }

    if (command === 'switch') {
      if (!firstArg) {
        throw new Error('switch requires a saved account label');
      }

      const saved = await switchToSavedAccount(codexHome, firstArg);
      if (asJson) {
        console.log(JSON.stringify(saved.summary, null, 2));
      } else {
        console.log(`Switched auth.json to "${saved.label}" (${saved.summary?.email ?? 'api-key login'})`);
        if (saved.profileHomePath) {
          console.log(`Profile home: ${saved.profileHomePath}`);
        }
        console.log('Existing Codex sessions may need a restart to pick up the new auth file.');
      }
      return 0;
    }

    if (command === 'probe') {
      if (firstArg && firstArg !== 'all') {
        const saved = await probeOne(codexHome, firstArg);
        if (asJson) {
          console.log(JSON.stringify(saved.lastProbe, null, 2));
        } else {
          console.log(renderSavedAccount(saved, { showProbeError: true }));
        }
        return 0;
      }

      const results = [];
      for (const account of await listSavedAccounts(codexHome)) {
        results.push(await probeOne(codexHome, account.label));
      }
      printAccounts(results, asJson);
      return 0;
    }

    if (command === 'best') {
      const best = await chooseBestAccount(codexHome, { probe });
      if (asJson) {
        console.log(JSON.stringify(best, null, 2));
      } else if (best) {
        console.log(colorize('Best saved account', 'bold'));
        console.log(renderSavedAccount(best));
      } else {
        console.log('No saved accounts available.');
      }
      return 0;
    }

    if (command === 'switch-best') {
      const best = await chooseBestAccount(codexHome, { probe });
      if (!best) {
        throw new Error('No saved accounts are available');
      }

      if (parsed.flags.has('--dry-run')) {
        if (asJson) {
          console.log(JSON.stringify(best, null, 2));
        } else {
          console.log(`Would switch to ${best.label} (${best.summary?.email ?? 'api-key login'})`);
        }
        return 0;
      }

      await switchToSavedAccount(codexHome, best.label);
      if (asJson) {
        console.log(JSON.stringify(best, null, 2));
      } else {
        console.log(`Switched to ${best.label} (${best.summary?.email ?? 'api-key login'})`);
      }
      return 0;
    }

    if (command === 'run') {
      const requestedLabel = await findSavedAccountLabel(codexHome, firstArg);
      const codexArgs = requestedLabel ? [...restArgs, ...parsed.passthrough] : [...parsed.positionals.slice(1), ...parsed.passthrough];
      const result = requestedLabel
        ? await runCodexWithSavedAccount(codexHome, requestedLabel, codexArgs, {
            dryRun: parsed.flags.has('--dry-run'),
          })
        : await runCodexWithBestAccount(codexHome, codexArgs, {
            probe,
            dryRun: parsed.flags.has('--dry-run'),
          });

      if (parsed.flags.has('--dry-run')) {
        const selected = result.selected ?? result.best ?? null;
        if (asJson) {
          console.log(JSON.stringify(result, null, 2));
        } else if (selected) {
          console.log(
            `Would launch Codex with ${selected.label} (${selected.summary?.email ?? 'api-key login'})${result.selectionMode === 'explicit' ? ' [explicit]' : ''}`,
          );
          if (result.launchCodexHome) {
            console.log(`CODEX_HOME: ${result.launchCodexHome}`);
          }
        } else {
          console.log('Would launch Codex with the current auth because no saved accounts exist.');
        }
        return 0;
      }

      return result.exitCode ?? 0;
    }

    throw new Error(`Unknown command: ${command}`);
  } catch (error) {
    console.error(`Error: ${error.message}`);
    return 1;
  }
}

const exitCode = await main();
process.exit(exitCode);
