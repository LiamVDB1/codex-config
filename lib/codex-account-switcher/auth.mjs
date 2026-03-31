import crypto from 'node:crypto';

export function decodeJwtPayload(token) {
  if (typeof token !== 'string' || !token) {
    throw new Error('JWT token is missing');
  }

  const parts = token.split('.');
  if (parts.length < 2 || !parts[1]) {
    throw new Error('JWT token is malformed');
  }

  return JSON.parse(Buffer.from(parts[1], 'base64url').toString('utf8'));
}

export function safeDecodeJwtPayload(token) {
  try {
    return decodeJwtPayload(token);
  } catch {
    return null;
  }
}

export function extractAuthSummary(auth) {
  const lastRefreshAt = auth?.last_refresh ?? null;

  if (typeof auth?.OPENAI_API_KEY === 'string' && auth.OPENAI_API_KEY) {
    return {
      authType: 'apiKey',
      email: null,
      planType: null,
      chatgptAccountId: null,
      tokenExpiresAt: null,
      lastRefreshAt,
    };
  }

  const accessPayload = safeDecodeJwtPayload(auth?.tokens?.access_token);
  const idPayload = safeDecodeJwtPayload(auth?.tokens?.id_token);
  const authClaims =
    accessPayload?.['https://api.openai.com/auth'] ??
    idPayload?.['https://api.openai.com/auth'] ??
    {};
  const profileClaims = accessPayload?.['https://api.openai.com/profile'] ?? {};

  const exp =
    typeof accessPayload?.exp === 'number'
      ? accessPayload.exp
      : typeof idPayload?.exp === 'number'
        ? idPayload.exp
        : null;

  return {
    authType: 'chatgpt',
    email: profileClaims.email ?? idPayload?.email ?? null,
    planType: authClaims.chatgpt_plan_type ?? null,
    chatgptAccountId: authClaims.chatgpt_account_id ?? auth?.tokens?.account_id ?? null,
    authSessionId: accessPayload?.session_id ?? idPayload?.session_id ?? null,
    tokenExpiresAt: exp ? new Date(exp * 1000).toISOString() : null,
    lastRefreshAt,
  };
}

export function extractGlobalStateSummary(globalState) {
  const environment =
    globalState?.['electron-persisted-atom-state']?.environment ??
    globalState?.electronPersistedAtomState?.environment ??
    null;

  return {
    environmentId: environment?.id ?? null,
    machineId: environment?.machine_id ?? environment?.machineId ?? null,
  };
}

export function sameAccountIdentity(leftSummary, rightSummary) {
  if (!leftSummary || !rightSummary) {
    return false;
  }

  if (leftSummary.authType !== rightSummary.authType) {
    return false;
  }

  if (leftSummary.authType === 'chatgpt') {
    if (leftSummary.chatgptAccountId && rightSummary.chatgptAccountId) {
      return leftSummary.chatgptAccountId === rightSummary.chatgptAccountId;
    }

    if (leftSummary.email && rightSummary.email) {
      return leftSummary.email.toLowerCase() === rightSummary.email.toLowerCase();
    }

    return false;
  }

  if (leftSummary.email && rightSummary.email) {
    return leftSummary.email.toLowerCase() === rightSummary.email.toLowerCase();
  }

  return false;
}

export function fingerprintAuth(auth) {
  const stableSecret =
    auth?.tokens?.refresh_token ??
    auth?.tokens?.access_token ??
    auth?.OPENAI_API_KEY ??
    JSON.stringify(auth ?? {});

  return crypto.createHash('sha256').update(stableSecret).digest('hex');
}

export function buildProbeLoginParams(auth) {
  if (typeof auth?.OPENAI_API_KEY === 'string' && auth.OPENAI_API_KEY) {
    return {
      type: 'apiKey',
      apiKey: auth.OPENAI_API_KEY,
    };
  }

  const summary = extractAuthSummary(auth);
  const accessToken = auth?.tokens?.access_token;

  if (!accessToken || !summary.chatgptAccountId) {
    throw new Error('Saved ChatGPT auth is missing an access token or account id');
  }

  return {
    type: 'chatgptAuthTokens',
    accessToken,
    chatgptAccountId: summary.chatgptAccountId,
    chatgptPlanType: summary.planType ?? null,
  };
}
