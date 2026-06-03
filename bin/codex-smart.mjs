#!/usr/bin/env node

import path from 'node:path';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
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
const dotenvPath = path.join(codexHome, '.env');

if (fs.existsSync(dotenvPath)) {
  const dotenv = fs.readFileSync(dotenvPath, 'utf8');
  for (const line of dotenv.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const separator = trimmed.indexOf('=');
    if (separator === -1) continue;

    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    if (!key || process.env[key]) continue;

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    process.env[key] = value;
  }
}

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
