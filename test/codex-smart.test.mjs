import test from 'node:test';
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import path from 'node:path';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const smartCliPath = path.resolve('bin/codex-smart.mjs');

test('codex-smart dry-run launches Codex through LiteLLM without local account switching', async () => {
  const { stdout } = await execFileAsync(
    process.execPath,
    [smartCliPath, '--no-probe', '--dry-run', '--', '--version'],
    { cwd: path.dirname(smartCliPath) },
  );

  const result = JSON.parse(stdout);
  assert.equal(result.provider, 'litellm');
  assert.equal(result.baseUrl, 'https://litellm.juphorizon.com/v1');
  assert.equal(result.envKey, 'LITELLM_API_KEY');
  assert.deepEqual(result.command, ['codex', '--version']);
  assert.deepEqual(result.ignoredFlags, ['--no-probe']);
  assert.equal(result.localAccountSwitching, false);
});
