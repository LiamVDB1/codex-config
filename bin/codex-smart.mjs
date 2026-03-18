#!/usr/bin/env node

import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const accountCli = path.join(scriptDir, 'codex-account.mjs');
const rawArgs = process.argv.slice(2);
const wrapperFlags = [];
const codexArgs = [];
let passthrough = false;

for (const arg of rawArgs) {
  if (arg === '--') {
    passthrough = true;
    continue;
  }

  if (!passthrough && (arg === '--no-probe' || arg === '--dry-run')) {
    wrapperFlags.push(arg);
    continue;
  }

  codexArgs.push(arg);
}

const child = spawn(process.execPath, [accountCli, 'run', ...wrapperFlags, '--', ...codexArgs], {
  cwd: process.cwd(),
  stdio: 'inherit',
});

const exitCode = await new Promise((resolve) => child.once('exit', resolve));
process.exit(exitCode ?? 1);
