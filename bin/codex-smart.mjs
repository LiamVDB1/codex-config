#!/usr/bin/env node

import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const rawArgs = process.argv.slice(2);
const codexArgs = [];
const ignoredFlags = [];
let dryRun = false;
let passthrough = false;

for (const arg of rawArgs) {
  if (arg === '--') {
    passthrough = true;
    continue;
  }

  if (!passthrough && (arg === '--no-probe' || arg === '--dry-run')) {
    if (arg === '--dry-run') {
      dryRun = true;
    } else {
      ignoredFlags.push(arg);
    }
    continue;
  }

  codexArgs.push(arg);
}

const codexHome = process.env.CODEX_HOME ?? path.resolve(scriptDir, '..');
const launchEnv = {
  ...process.env,
  CODEX_HOME: codexHome,
};

if (dryRun) {
  console.log(JSON.stringify({
    provider: 'litellm',
    baseUrl: 'https://litellm.juphorizon.com/v1',
    envKey: 'LITELLM_API_KEY',
    codexHome,
    command: ['codex', ...codexArgs],
    ignoredFlags,
    localAccountSwitching: false,
  }, null, 2));
  process.exit(0);
}

if (!process.env.LITELLM_API_KEY) {
  console.error('LITELLM_API_KEY is not set; Codex will not be able to authenticate with the LiteLLM provider.');
}

const child = spawn('codex', codexArgs, {
  cwd: process.cwd(),
  stdio: 'inherit',
  env: launchEnv,
});

const exitCode = await new Promise((resolve) => child.once('exit', resolve));
process.exit(exitCode ?? 1);
