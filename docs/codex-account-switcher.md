# Codex Account Switcher

This keeps two local CLIs:

- `bin/codex-account.mjs`: save, inspect, probe, and switch saved Codex accounts
- `bin/codex-smart.mjs`: launch `codex` with the shared `~/.codex` home and the configured LiteLLM provider

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

## Manual switcher behavior

Each saved account can now carry:

- `auth.json`
- `.codex-global-state.json`
- a per-account snapshot directory under `accounts/homes/<label>/`

Manual `codex-account switch`, `switch-best`, and `run` commands can still restore a chosen account's auth/global-state and consolidate any stranded session/history data from older per-account homes back into the shared runtime.

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
7. Or launch directly with a specific saved account via `bin/codex-account.mjs run work -- <codex args>`
8. Rename a label later with `bin/codex-account.mjs rename work work-main`

## Current smart launcher behavior

`bin/codex-smart.mjs` no longer mutates local auth state or runs local account probes. It relies on the configured LiteLLM provider:

```toml
model_provider = "litellm"

[model_providers.litellm]
base_url = "https://litellm.juphorizon.com/v1"
env_key = "LITELLM_API_KEY"
wire_api = "responses"
```

LiteLLM owns account selection, account switching, and retry behavior behind that endpoint. Keep `LITELLM_API_KEY` in the environment; do not store it in this repository.

`--no-probe` is accepted as a compatibility no-op. You can preview the launch shape without starting Codex:

```bash
bin/codex-smart.mjs --dry-run
```

## Legacy local automatic selection

The local account switcher still supports this sequence through `bin/codex-account.mjs best`, `switch-best`, and `run`:

1. Load saved accounts
2. Probe live rate limits by default via a temporary local `codex app-server`
3. Deprioritize any account whose live limits are fully exhausted, then rank the remaining accounts by plan tier and by a reset-aware quota budget so accounts with less quota left and a nearer reset get drained first
4. Restore the saved account snapshot into the shared home
5. Launch `codex` with the shared `CODEX_HOME`

This keeps usable higher plan tiers ahead of lower ones, but it will switch away once an account has a live window at `0% free`. Within the same usable plan tier it now prefers the account whose remaining quota is most perishable, combining how much is left with how soon that window resets.

You can preview the choice without launching Codex:

```bash
bin/codex-account.mjs best
bin/codex-account.mjs switch-best --dry-run
bin/codex-account.mjs run work --dry-run
```

The `list`, `best`, and `probe` views show a cleaner per-account summary, including the live-limit snapshot and the weekly reset time when a probe is available. When you opt out with `--no-probe`, the output labels that state as a saved probe snapshot instead of calling it live.

If you re-authenticate an already-saved ChatGPT account and the refresh token rotates, the switcher now reconciles that active auth back into the matching saved label automatically before listing, probing, or loading that account.

## Notes

- Existing Codex sessions may need a restart after a manual `switch`, because the running process may already have loaded credentials.
- `codex-smart.mjs` is the preferred entrypoint if LiteLLM owns ChatGPT/Codex account switching.
- Legacy local probing uses the local app-server protocol exposed by the installed Codex build. If that protocol changes, probing can fail; the tool then falls back to saved plan metadata for ranking.
