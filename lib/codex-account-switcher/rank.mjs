const PLAN_RANKS = {
  unknown: 0,
  free: 1,
  go: 2,
  plus: 3,
  pro: 4,
  team: 5,
  business: 6,
  enterprise: 7,
  edu: 5,
};

function clampPercent(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null;
  }

  return Math.max(0, Math.min(100, value));
}

function listWindows(rateLimits) {
  return [rateLimits?.primary, rateLimits?.secondary].filter(
    (window) => window && typeof window.usedPercent === 'number',
  );
}

export function slugifyLabel(label) {
  const normalized = String(label ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

  return normalized || 'account';
}

export function getPlanRank(planType) {
  return PLAN_RANKS[String(planType ?? 'unknown').toLowerCase()] ?? PLAN_RANKS.unknown;
}

export function summarizeRateLimits(rateLimits) {
  const windows = listWindows(rateLimits);

  if (!windows.length) {
    return {
      liveWindowCount: 0,
      bottleneckRemaining: -1,
      averageRemaining: -1,
    };
  }

  const remaining = windows
    .map((window) => clampPercent(100 - window.usedPercent))
    .filter((value) => value !== null);

  return {
    liveWindowCount: remaining.length,
    bottleneckRemaining: Math.min(...remaining),
    averageRemaining: remaining.reduce((sum, value) => sum + value, 0) / remaining.length,
  };
}

export function rankSavedAccount(savedAccount) {
  const planRank = getPlanRank(savedAccount?.summary?.planType);
  const hasLiveProbe = Boolean(savedAccount?.lastProbe?.success && savedAccount?.lastProbe?.rateLimits);
  const live = summarizeRateLimits(savedAccount?.lastProbe?.rateLimits);

  const sortKey =
    planRank * 1_000_000_000 +
    (hasLiveProbe ? 1 : 0) * 100_000_000 +
    Math.round((live.bottleneckRemaining + 1) * 1_000_000) +
    Math.round((live.averageRemaining + 1) * 10_000);

  return {
    ...savedAccount,
    planRank,
    hasLiveProbe,
    ...live,
    sortKey,
  };
}

export function sortSavedAccounts(savedAccounts) {
  return [...savedAccounts]
    .map(rankSavedAccount)
    .sort((left, right) => {
      if (right.sortKey !== left.sortKey) {
        return right.sortKey - left.sortKey;
      }

      const leftLabel = String(left.label ?? '').toLowerCase();
      const rightLabel = String(right.label ?? '').toLowerCase();
      return leftLabel.localeCompare(rightLabel);
    });
}

function describeWindow(window) {
  if (!window || typeof window.usedPercent !== 'number') {
    return null;
  }

  const duration = typeof window.windowDurationMins === 'number' ? window.windowDurationMins : null;
  let label = 'window';

  if (duration && duration % 1440 === 0) {
    label = `${duration / 1440}d`;
  } else if (duration && duration % 60 === 0) {
    label = `${duration / 60}h`;
  } else if (duration) {
    label = `${duration}m`;
  }

  return `${label} ${Math.max(0, 100 - window.usedPercent)}% free`;
}

export function formatRateLimits(rateLimits) {
  const parts = [describeWindow(rateLimits?.primary), describeWindow(rateLimits?.secondary)].filter(Boolean);
  return parts.length ? parts.join(', ') : 'no live limit data';
}
