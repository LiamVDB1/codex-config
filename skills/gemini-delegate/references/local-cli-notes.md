# Local Gemini CLI Notes

These notes were derived from the locally installed Gemini CLI entrypoint and bundled source on this machine.

Observed install:

- Binary: `/opt/homebrew/bin/gemini`
- Package path: `/opt/homebrew/Cellar/gemini-cli/0.32.1/...`

Relevant flags found in the local source:

- `-p`, `--prompt`: non-interactive headless mode
- `-i`, `--prompt-interactive`: execute a prompt and continue interactively
- `-m`, `--model`: choose model
- `--approval-mode`: `default`, `auto_edit`, `yolo`, `plan`
- `-o`, `--output-format`: `text`, `json`, `stream-json`
- `--include-directories`: add directories to the workspace
- `-r`, `--resume`: resume an existing session

Important assumptions used by the wrappers:

- `--prompt` with `--output-format json` returns JSON containing a `response` field.
- `--approval-mode plan` is the safe read-only default for consultation.
- `--approval-mode auto_edit` is the default for isolated worker sessions.
- The CLI can be launched inside tmux with `--prompt-interactive` for a persistent thread.
- The default wrapper allowlist is `context7,memory,sequential-thinking,stitch` because the local `magic` server currently exposes tool names that Gemini's API rejects.

If future versions break these assumptions, patch [scripts/common.py](../scripts/common.py) first, then adjust the caller scripts only if needed.
