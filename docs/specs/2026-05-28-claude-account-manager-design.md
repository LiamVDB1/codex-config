# Claude/ChatGPT Account Manager Design

## Purpose

Build a server-owned Claude/ChatGPT account management control plane that makes accounts easy to add, refresh, probe, route, inspect, and use from LiteLLM, Nexus, and local clients.

The key design correction is that the account manager should not become a custom OpenAI-compatible data-plane proxy. LiteLLM already handles ChatGPT provider behavior, `/v1/responses` compatibility, streaming fixes, request shaping, response transformation, retries, spend logs, virtual keys, aliases, and ongoing provider updates. Reimplementing that in a new service would be fragile.

Instead, LiteLLM remains the data plane. The account manager becomes the control plane. A thin LiteLLM callback asks the account manager which account lease to activate before each ChatGPT-backed provider call, then LiteLLM's native `chatgpt/gpt-*` provider performs the actual request.

## Current State

Local Codex account switching is implemented in `/Users/liamvdb/.codex`:

- `bin/codex-account.mjs` provides `save`, `list`, `rename`, `switch`, `probe`, `best`, `switch-best`, and `run`.
- `lib/codex-account-switcher/store.mjs` snapshots and restores `auth.json`, optional `.codex-global-state.json`, and per-account homes.
- `lib/codex-account-switcher/probe.mjs` launches `codex app-server`, then reads account and rate-limit state over local WebSocket JSON-RPC.
- `lib/codex-account-switcher/runner.mjs` probes/ranks accounts, mutates `CODEX_HOME`, and launches Codex.

The server already has a LiteLLM deployment at `/home/opc/litellm`:

- LiteLLM runs as `litellm-litellm-1` on port `4000`.
- LiteLLM uses `config.yaml` as the source of truth with `store_model_in_db: false` to avoid DB/config drift.
- ChatGPT/Codex models are configured as `chatgpt/gpt-*` models without per-account deployments.
- `proxy_callbacks/chatgpt_account_switcher.py` switches accounts inside a LiteLLM callback.
- `chatgpt-account-probe` runs `docker/chatgpt_account_probe_refresh.py` every `900` seconds.
- LiteLLM mounts `/home/opc/.codex/accounts` and account-switcher probe code read-only, and writes active LiteLLM auth into `.litellm-chatgpt`.
- LiteLLM cooldowns are disabled for this path because it currently sees one deployment per ChatGPT model; if that deployment cools down, the whole model group goes unavailable.

The current callback proves the control-plane mechanism is viable: it uses `async_pre_call_hook` to choose and activate the best account before the native LiteLLM ChatGPT provider call. It also rotates on 401/429/5xx, refreshes the provider authenticator, and patches interactive device-code login to fail fast inside the proxy.

This works, but the responsibilities are tangled: LiteLLM callbacks, mounted token files, local Codex account snapshots, periodic probes, and manual refresh flows all share ownership of account state.

## Target Architecture

Use a LiteLLM-native data plane with an Account Manager control plane.

```text
Clients / Codex / agents / apps
        |
        | OpenAI-compatible API
        v
      LiteLLM  ------------------------------+
        |                                     |
        | native chatgpt/gpt-* provider       | thin callback asks for account lease
        v                                     v
  ChatGPT provider runtime            nginx HTTPS + API key
  responses / streaming / auth   ->   Account Manager API
  transformation stays here            |       |       |
                                      |       |       +--> probe scheduler / refresh worker
                                      |       +----------> account DB + encrypted token store
                                      +-----------> routing policy / lease service

Nexus / admin CLI  ->  nginx HTTPS + API key  ->  Account Manager API
```

LiteLLM remains the public LLM gateway for clients. It keeps model aliases, API keys, virtual keys, spend logs, retries, request logging, non-ChatGPT providers, and native ChatGPT request/response behavior. The account manager owns everything specific to account lifecycle, account health, OAuth/re-auth, policy, selection, groups, pinned accounts, and Nexus visibility.

## Core Design Principle

Do not split response compatibility across two systems.

The account manager influences account selection only. It must not rewrite request/response bodies, implement `/v1/responses`, proxy SSE streams, or duplicate LiteLLM ChatGPT provider transformations. If LiteLLM updates its ChatGPT provider behavior, this architecture should benefit automatically.

## Core Components

### 1. Account Manager API

A server API exposed through nginx over HTTPS and protected by API key authentication.

Responsibilities:

- List accounts and account groups.
- Add accounts through OAuth/browser login flow.
- Refresh or re-auth accounts.
- Enable, disable, rename, tag, group, and annotate accounts.
- Expose account health, quota, plan, last probe, and last error.
- Expose routing policy configuration.
- Issue account leases for LiteLLM callbacks.
- Accept lease outcome reports from LiteLLM callbacks.
- Emit structured logs and operational events.

Initial admin/control endpoints:

- `GET /healthz`
- `GET /api/accounts`
- `POST /api/accounts/oauth/start`
- `POST /api/accounts/oauth/complete`
- `POST /api/accounts/{account_id}/refresh`
- `POST /api/accounts/{account_id}/disable`
- `POST /api/accounts/{account_id}/enable`
- `PATCH /api/accounts/{account_id}`
- `GET /api/groups`
- `POST /api/groups`
- `PATCH /api/groups/{group_id}`
- `GET /api/routes`
- `PATCH /api/routes/{route_id}`
- `GET /api/reports/account-health`

Initial LiteLLM callback endpoints:

- `POST /api/leases/acquire`
- `POST /api/leases/{lease_id}/success`
- `POST /api/leases/{lease_id}/failure`
- `POST /api/leases/{lease_id}/release`
- `POST /api/leases/{lease_id}/invalidate`

The `/api/*` endpoints are control-plane endpoints. They are not OpenAI-compatible model endpoints.

### 2. Lease Contract

The safest callback contract is lease-based.

The LiteLLM callback sends:

- `provider`: initially `chatgpt`.
- `model`: requested LiteLLM model or model group.
- `request_id`: generated by LiteLLM/callback for traceability.
- `attempt`: first attempt or retry attempt number when available.
- `policy`: optional requested pool, group, pinned account, or exclusion set.
- `previous_lease_id`: when retrying after a failure.
- `failure_reason`: when acquiring after 401/403/429/5xx.

The account manager returns:

- `lease_id`: opaque durable identifier.
- `account_id`: opaque internal account id.
- `label`: human-readable account label for logs/UI.
- `expires_at`: short lease expiry.
- `activation`: one of `already_active`, `activate_label`, or future service-owned activation mode.
- `activation_ref`: non-secret activation reference, such as a label understood by the local LiteLLM callback.
- `policy_explanation`: concise reason for selection.

Do not pass full OAuth tokens, refresh tokens, raw auth payloads, or arbitrary file paths through the callback API. If token/file activation is still required during migration, the account manager and LiteLLM callback should share a tightly scoped server-side trust boundary where the callback receives only an opaque activation reference.

### 3. Thin LiteLLM Callback

The LiteLLM callback remains installed in `litellm_settings.callbacks`, but becomes deterministic and small.

Responsibilities that stay in the callback:

- Detect whether a request targets a ChatGPT-backed model.
- Acquire a fresh lease before the provider call.
- Activate the selected account context for LiteLLM's native ChatGPT provider.
- Attach non-secret metadata such as `lease_id` and `account_label` for logs.
- On success, report lease success.
- On 401/403/429/5xx, report failure/invalidate to the account manager.
- Refresh LiteLLM's ChatGPT authenticator after account activation when needed.
- Keep the device-code login guard so dead refresh tokens fail fast inside the proxy.

Responsibilities moved out of the callback:

- Ranking accounts.
- Reading and reconciling the full account manifest.
- Owning probe cadence.
- Deciding cooldowns and re-auth status.
- Managing groups and pinned aliases.
- Providing user-facing account controls.
- Generating reports.

Callback failure policy:

- If the account-manager API is unavailable for a ChatGPT-backed request, fail closed with a clear account-selection error rather than falling back to an arbitrary stale account.
- Callback failures must not affect unrelated non-ChatGPT providers.
- Callback logs must never include token material or raw auth files.

### 4. Account Store

A server-side account registry backed by a real database plus encrypted token storage.

Account fields:

- `id`
- `label`
- `email`
- `account_id`
- `plan_type`
- `status`: `active`, `disabled`, `needs_reauth`, `cooling_down`, `error`
- `groups`
- `dedicated_proxy_slug`
- `priority`
- `created_at`
- `updated_at`
- `last_selected_at`
- `last_probe_at`
- `last_refresh_at`
- `last_error`
- `probe_snapshot`
- `token_ref`

Lease fields:

- `id`
- `account_id`
- `request_id`
- `model`
- `policy`
- `attempt`
- `status`: `acquired`, `succeeded`, `failed`, `released`, `expired`, `invalidated`
- `failure_reason`
- `created_at`
- `expires_at`
- `completed_at`

Token material should not live in LiteLLM callback files or mounted Codex snapshots as the long-term source of truth. The migration can import existing `/home/opc/.codex/accounts` snapshots, but after migration the account manager is authoritative.

### 5. OAuth And Re-auth Flow

The account manager owns account onboarding and refresh.

Flow:

1. Nexus or CLI calls `POST /api/accounts/oauth/start`.
2. The service creates a pending account session and returns a browser URL or local callback instructions.
3. Liam completes the login in a browser.
4. The service receives or imports the resulting OAuth tokens.
5. The service stores encrypted credentials, probes the account, and marks it active.
6. If refresh fails later, the account moves to `needs_reauth` and Nexus surfaces the action.

The design should preserve a manual escape hatch during migration: importing a known-good Codex auth snapshot should be supported until the full browser flow is stable.

### 6. Probe Scheduler

A worker probes every account on a standard 15-minute cadence.

Adaptive probing rules:

- Probe healthy accounts every `900` seconds.
- Probe more often when an account is near quota, near token expiry, recently failed, or recently selected.
- Back off accounts that repeatedly fail due to authentication or service errors.
- Do not let one slow probe block request-time lease acquisition.
- Keep the latest known-good probe snapshot for routing decisions.

Probe results should include plan type, quota windows, reset times, remaining usage, account identity, and probe errors when available. If the underlying Codex app-server probe remains necessary, it should move behind the service worker boundary instead of running inside LiteLLM callbacks.

### 7. Routing Policy Engine

The first routing behavior is `best available account`.

Initial selection criteria:

- Exclude disabled or `needs_reauth` accounts.
- Exclude accounts in cooldown unless no other account is usable.
- Prefer accounts with sufficient quota and better plan tier.
- Prefer accounts with fresh successful probe snapshots.
- Avoid accounts with recent rate-limit failures.
- Avoid reusing a failed `previous_lease_id` on retry.
- Track last selected account for observability and simple spreading.

Future policy requirements must be included in the data model now:

- Include/exclude specific account groups.
- Dedicated proxy per account, e.g. one LiteLLM alias or policy slug always using one account.
- Named pools, e.g. `default`, `pro-only`, `cheap`, `experimental`, `client-x`.
- Per-route constraints, such as allowed models, allowed accounts, or fallback groups.

Do not overbuild the policy UI in the first implementation. The first version should store enough structure to avoid another redesign when groups and pinned account policies are added.

### 8. LiteLLM Integration

LiteLLM should remain the client-facing gateway and ChatGPT data plane.

Recommended LiteLLM shape:

```yaml
litellm_settings:
  callbacks:
    - proxy_callbacks.chatgpt_account_lease.chatgpt_account_lease
    - proxy_callbacks.chatgpt_system_prompt_compat.chatgpt_system_prompt_compat

model_list:
  - model_name: gpt-5.5-chatgpt
    model_info:
      mode: responses
    litellm_params:
      model: chatgpt/gpt-5.5

  - model_name: gpt-5.4-chatgpt
    model_info:
      mode: responses
    litellm_params:
      model: chatgpt/gpt-5.4

router_settings:
  num_retries: 3
  timeout: 300
  disable_cooldowns: true
```

LiteLLM keeps:

- `master_key` and virtual keys.
- Spend logs and usage reporting.
- Model aliases.
- Native `chatgpt/gpt-*` provider behavior.
- Native `/v1/responses` and streaming behavior.
- System prompt compatibility callbacks.
- Fallbacks to non-ChatGPT providers where useful.
- Request logging and admin UI.

The old `chatgpt_account_switcher.py` should be replaced by a thinner lease callback after the account manager is live. During migration, both callbacks or model aliases can coexist in a controlled way until confidence is high.

Avoid making the new service continuously rewrite LiteLLM config. Config generation may be useful for bootstrap or optional dedicated aliases, but it should not be the main runtime contract.

### 9. Nexus Control Panel

Nexus should provide a read/write control panel.

Core screens:

- Account overview: labels, email, plan, status, remaining quota, reset time, last probe, last selected, last error.
- Account detail: probe history, refresh status, groups, dedicated proxy slug, notes, admin actions.
- Add account: start OAuth/re-auth flow and show progress.
- Routing policy: default pool, enabled groups, pinned accounts, disabled accounts.
- Lease history: recent selected accounts, failure reasons, invalidations, retry rotations.
- Reports: account health timeline and selection history.
- Operations: manual probe, refresh, disable, enable.

Nexus should call the Account Manager API. It should not read token files, mutate LiteLLM config directly, or own account selection logic.

### 10. Reporting

First reporting scope:

- Account inventory.
- Current health and quota status.
- Probe freshness and errors.
- Lease/selection history.
- Near-quota and needs-reauth accounts.

Future reporting extensions:

- Ingest LiteLLM spend logs from `LiteLLM_SpendLogs`.
- Join LiteLLM request logs with lease/account metadata.
- Per-model usage by account group.
- Per-client usage through LiteLLM virtual keys.
- Daily/weekly account saturation reports.

The first version should design event tables so future LiteLLM usage ingestion can be added without changing the core account model.

### 11. Security Boundary

The service is exposed through nginx over HTTPS with API key authentication.

Security requirements:

- API keys are stored as hashes, not plaintext.
- Separate admin API key from LiteLLM callback API key.
- API keys are scoped, revocable, and rotatable without redeploying the service.
- Key use is audit-logged by key id, route, source IP, and timestamp without logging secret values.
- Lease endpoint requests include bounded timestamp checks and nonce/jti replay prevention.
- Lease outcome endpoints enforce lease expiry and reject stale success, failure, release, or invalidate calls.
- Token material is encrypted at rest.
- Lease APIs never return OAuth tokens, refresh tokens, or raw auth files.
- Logs never include OAuth tokens, refresh tokens, API keys, or raw auth files.
- Admin endpoints require the admin key.
- Lease endpoints require the LiteLLM callback key.
- Nexus stores only the API key it needs to call admin endpoints.
- Failed auth attempts are logged with source IP and route but no secret values.

Tailscale-only access can remain useful for SSH and maintenance, but the intended product surface is nginx HTTPS with API keys.

## Data Flow

### Normal LiteLLM Request

1. Client calls LiteLLM with model alias, e.g. `gpt-5.5`.
2. LiteLLM maps alias to its native `chatgpt/gpt-*` provider.
3. LiteLLM callback detects this is a ChatGPT-backed request.
4. Callback calls `POST /api/leases/acquire` with model, request id, attempt, and policy inputs.
5. Account manager chooses the best eligible account and returns an opaque lease plus activation reference.
6. Callback activates that account context for LiteLLM's native ChatGPT provider.
7. LiteLLM performs the actual request and response transformation.
8. Callback reports success or failure to the account manager.
9. LiteLLM records its normal spend/request logs.
10. Client receives the normal LiteLLM response.

### Account Saturated During Request

1. Request selects an account believed healthy.
2. LiteLLM native provider receives 429/quota/rate-limit response.
3. Failure hook reports the failed lease and reason to the account manager.
4. Account manager marks the account as cooling down with reset metadata if available.
5. A retry attempt must acquire a fresh lease that excludes the failed lease/account when possible.
6. Callback activates the new account and refreshes LiteLLM's ChatGPT authenticator if required.
7. If no accounts remain, LiteLLM surfaces the failure and can use configured fallback policy to non-ChatGPT providers.

This prevents LiteLLM from getting stuck on one saturated ChatGPT account while keeping LiteLLM's native ChatGPT response path intact.

### Auth Failure During Request

1. LiteLLM native provider receives 401/403 or refresh-token failure.
2. Callback/failure hook reports invalid auth for the lease.
3. Account manager marks the account `needs_reauth` and excludes it from future leases.
4. Callback/device-code guard prevents interactive login from hanging inside the proxy.
5. Retry attempts acquire another eligible account.
6. Nexus shows the account as needing re-auth.

### OAuth Add/Re-auth

1. Admin starts OAuth from Nexus.
2. Account manager creates a pending session.
3. Browser login completes.
4. Account manager stores encrypted credentials and probes the account.
5. Nexus shows active account status or actionable failure.

## Migration Plan

### Phase 0: Baseline And Verification

- Snapshot current LiteLLM config and callback behavior.
- Confirm current ChatGPT model aliases and traffic paths.
- Confirm current `.litellm-chatgpt` and `/home/opc/.codex/accounts` state shape.
- Add read-only observability around current account selection if needed.

### Phase 1: Account Manager Read-only Service

- Build service with database schema and account import from existing snapshots.
- Expose `GET /api/accounts`, `GET /api/reports/account-health`, and `GET /healthz`.
- Run probe scheduler using the existing probe logic behind the service boundary.
- Build initial Nexus read-only account dashboard.

### Phase 2: Lease API Without Runtime Cutover

- Add `POST /api/leases/acquire` and outcome endpoints.
- Implement lease selection using the same ranking semantics as the existing callback.
- Add a dry-run mode where the current callback logs what the account manager would have selected without changing behavior.
- Compare current callback selections against account-manager lease decisions.

### Phase 3: OAuth And Admin Controls

- Add OAuth/re-auth start and complete flow.
- Add enable/disable, rename, groups, and manual probe/refresh actions.
- Make Nexus a read/write control panel.

### Phase 4: Thin LiteLLM Lease Callback

- Replace ranking/manifest logic in the callback with calls to the account manager lease API.
- Keep LiteLLM's native `chatgpt/gpt-*` model configuration.
- Keep retry rotation, provider authenticator refresh, and device-code guard behavior.
- Gate the new callback behind a separate model alias or environment flag for initial testing.

### Phase 5: Gradual LiteLLM Cutover

- Test new callback path with manual traffic.
- Move one low-risk ChatGPT alias to lease-backed selection.
- Compare failures, latency, and probe behavior against the old callback path.
- Move primary aliases after confidence.
- Remove local ranking/manifest/probe logic from the callback once unused.

### Phase 6: Groups, Pinned Accounts, And Reports

- Add group-aware lease policies.
- Add pinned-account policies for dedicated aliases.
- Add Nexus routing controls.
- Add richer reports and optional LiteLLM spend-log ingestion.

## Error Handling

- Account with auth failure becomes `needs_reauth` immediately and is excluded from lease acquisition.
- Account with rate-limit/quota failure becomes `cooling_down` until reset or next successful probe.
- Account with transient upstream failure gets short cooldown and retry rules.
- Stale probe data is allowed for routing only if the account is otherwise healthy; stale data should lower rank.
- Probe failures should not delete the last known-good state.
- Callback must acquire a fresh lease on retry boundaries rather than reusing a failed account.
- Lease acquisition must be atomic and idempotent by `request_id` + `attempt`.
- Concurrent requests may share an account only if policy allows sharing; otherwise lease acquisition must enforce exclusivity.
- Streaming failures should be reported, but the callback should not attempt to salvage a partially emitted stream.
- If all accounts fail, return a clear account-exhaustion error and let LiteLLM fallback policies run if configured.
- OAuth failures should be visible in Nexus with a retry action.

## Testing Strategy

Unit tests:

- Account ranking and eligibility.
- Lease acquisition idempotency.
- Retry lease exclusion.
- Group include/exclude rules.
- Pinned account routing.
- Probe state transitions.
- Auth failure and quota cooldown transitions.
- API key auth middleware.

Integration tests:

- Import existing account snapshot metadata without exposing secrets.
- Probe worker updates account state.
- Lease API selects an eligible account.
- LiteLLM callback activates the leased account before native provider call.
- Request-time 429/401 response invalidates lease and rotates on retry.
- Nexus API actions update service state.
- LiteLLM continues to handle `/v1/responses` through its native ChatGPT provider.

Manual verification:

- Add account from Nexus.
- Force manual probe.
- Disable an account and verify it is excluded from leases.
- Simulate saturated account and verify clean switch on retry.
- Send LiteLLM request through lease-backed alias.
- Confirm `/v1/responses` behavior still matches LiteLLM native provider behavior.
- Confirm logs do not contain token material.

## Open Questions To Resolve During Implementation

- Exact framework and runtime for the account manager service should follow Nexus/server conventions after inspecting that repo.
- Exact OAuth callback mechanics depend on how Codex/ChatGPT login can be driven reliably on the server.
- Exact token encryption method should match existing server secret-management practice.
- Exact lease activation mechanism should minimize shared mutable auth files, but can start by formalizing the current active-auth-file mechanism behind a lease contract.
- Exact LiteLLM model names should be chosen during cutover to avoid disrupting current clients.

## Non-goals For First Version

- Replacing LiteLLM as the primary LLM gateway.
- Reimplementing LiteLLM's OpenAI-compatible `/v1/responses` or streaming transformations.
- Building full cost analytics before basic account health and lease reporting works.
- Supporting arbitrary external users.
- Automatically rewriting LiteLLM config as the main runtime mechanism.
- Removing the old callback path before the new lease-backed path is proven.
