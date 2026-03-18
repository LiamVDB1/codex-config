#!/usr/bin/env node

import { formatRateLimits, sortSavedAccounts } from '../lib/codex-account-switcher/rank.mjs';
import { probeAuthRateLimits } from '../lib/codex-account-switcher/probe.mjs';
import { chooseBestAccount, runCodexWithBestAccount } from '../lib/codex-account-switcher/runner.mjs';
import {
  getCurrentAccountContext,
  listSavedAccounts,
  loadSavedAccount,
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
  list [--probe]          List saved accounts, optionally refreshing live rate limits
  switch <label>          Replace auth.json with a saved account snapshot
  probe [label|all]       Refresh live rate-limit data for one or all saved accounts
  best [--probe]          Show which saved account would be selected
  switch-best [--probe]   Switch to the best saved account
  run [--no-probe] [--]   Switch to the best saved account, then launch codex

Environment:
  CODEX_HOME              Override the Codex home directory (default: ~/.codex)
`);
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
  console.log(`Active account: ${summary.email ?? 'api-key login'} (${summary.planType ?? summary.authType})`);
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

  for (const account of sortSavedAccounts(accounts)) {
    const marker = account.isCurrent ? '*' : ' ';
    const email = account.summary?.email ?? 'api-key login';
    const plan = account.summary?.planType ?? account.summary?.authType ?? 'unknown';
    const limits = formatRateLimits(account.lastProbe?.rateLimits);
    console.log(`${marker} ${account.label}  ${email}  ${plan}  ${limits}`);
  }
}

async function probeOne(codexHome, label) {
  const saved = await loadSavedAccount(codexHome, label);
  const probe = await probeAuthRateLimits(saved.auth, { cwd: codexHome });
  await updateProbeResult(codexHome, saved.label, probe);
  return {
    ...saved,
    lastProbe: probe,
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

  const [command = 'help', firstArg] = parsed.positionals;
  const asJson = parsed.flags.has('--json');
  const codexHome = resolveCodexHome(parsed.values.get('codexHome'));
  const probe = parsed.flags.has('--probe');

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
        refreshed.push(await probeOne(codexHome, account.label));
      }
      printAccounts(refreshed, asJson);
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
          console.log(`${saved.label}: ${saved.lastProbe.success ? formatRateLimits(saved.lastProbe.rateLimits) : saved.lastProbe.error}`);
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
        console.log(`Best account: ${best.label} (${best.summary?.email ?? 'api-key login'})`);
        console.log(`Reason: ${best.summary?.planType ?? best.summary?.authType}, ${formatRateLimits(best.lastProbe?.rateLimits)}`);
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
      const result = await runCodexWithBestAccount(codexHome, parsed.passthrough, {
        probe: !parsed.flags.has('--no-probe'),
        dryRun: parsed.flags.has('--dry-run'),
      });

      if (parsed.flags.has('--dry-run')) {
        if (asJson) {
          console.log(JSON.stringify(result, null, 2));
        } else if (result.best) {
          console.log(`Would launch Codex with ${result.best.label} (${result.best.summary?.email ?? 'api-key login'})`);
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
