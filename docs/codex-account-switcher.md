# Codex Account Switcher

This adds two local CLIs:

- `bin/codex-account.mjs`: save, inspect, probe, and switch saved Codex accounts
- `bin/codex-smart.mjs`: pick the best saved account, switch saved state, then launch `codex`

## What Codex stores today

- Main user config lives in `~/.codex/config.toml`
- Managed ChatGPT auth is currently file-backed in `~/.codex/auth.json`
- The active auth file contains an `access_token`, `id_token`, `refresh_token`, `account_id`, and `last_refresh`
- This setup appears to be single-account by default: one active `auth.json`, not a native multi-account store

## What this tool stores

Saved account snapshots live under `~/.codex/accounts/`:

- `accounts/manifest.json`: labels, email, plan, fingerprints, and last probe result
- `accounts/snapshots/<label>.auth.json`: full auth snapshot for that account
- `accounts/snapshots/<label>.global-state.json`: saved `.codex-global-state.json` when present
- `accounts/homes/<label>/`: per-account snapshot directory containing auth/global-state files plus symlinks back into the shared `~/.codex` runtime

These files are intentionally gitignored and written with restrictive permissions because they contain live tokens.

## What switches now

Each saved account can now carry:

- `auth.json`
- `.codex-global-state.json`
- a per-account snapshot directory under `accounts/homes/<label>/`

The smart launcher now always launches Codex with the shared `~/.codex` as `CODEX_HOME`. Before launching, it restores the chosen account's auth/global-state and consolidates any stranded session/history data from older per-account homes back into the shared runtime.

## What I could verify about upstream identifiers

By inspecting local Codex request logs:

- normal ChatGPT websocket traffic includes `chatgpt-account-id`
- the auth token itself includes an OpenAI auth session claim `session_id` such as `authsess_...`
- the websocket `session_id` header is a Codex thread/session UUID, not a device fingerprint

I did not find evidence that normal Codex request traffic sends a separate stable `device-id` header. The per-account home isolation is therefore the practical way to make any hidden account/device-related client state switch with the account.

## Basic flow

1. Log into account A with normal Codex login
2. Run `bin/codex-account.mjs save work`
3. Log into account B with normal Codex login
4. Run `bin/codex-account.mjs save personal`
5. Run `bin/codex-account.mjs list`
6. Switch manually with `bin/codex-account.mjs switch work`

## Automatic selection

`bin/codex-smart.mjs` runs this sequence:

1. Load saved accounts
2. Probe live rate limits when possible via a temporary local `codex app-server`
3. Rank accounts by plan tier first, then by remaining live headroom
4. Restore the saved account snapshot into the shared home
5. Launch `codex` with the shared `CODEX_HOME`

You can preview the choice without launching Codex:

```bash
bin/codex-account.mjs best --probe
bin/codex-account.mjs switch-best --probe --dry-run
bin/codex-smart.mjs --no-probe --dry-run
```

## Notes

- Existing Codex sessions may need a restart after a manual `switch`, because the running process may already have loaded credentials.
- `codex-smart.mjs` is the preferred entrypoint if you want one shared chat/session history while still swapping account auth automatically.
- Live probing uses the local app-server protocol exposed by the installed Codex build. If that protocol changes, probing can fail; the tool then falls back to saved plan metadata for ranking.
