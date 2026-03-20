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

function normalizeResetAt(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return null;
  }

  return value > 1_000_000_000_000 ? value : value * 1000;
}

function getWindowDurationMs(window) {
  if (typeof window?.windowDurationMins !== 'number' || Number.isNaN(window.windowDurationMins) || window.windowDurationMins <= 0) {
    return null;
  }

  return window.windowDurationMins * 60 * 1000;
}

function getWindowRemainingFraction(window, nowMs) {
  const durationMs = getWindowDurationMs(window);
  if (durationMs === null || window.resetAtMs === null) {
    return 1;
  }

  return Math.max(0, Math.min(1, (window.resetAtMs - nowMs) / durationMs));
}

function listWindows(rateLimits) {
  return [rateLimits?.primary, rateLimits?.secondary]
    .filter((window) => window && typeof window.usedPercent === 'number')
    .map((window) => {
      const remaining = clampPercent(100 - window.usedPercent);
      return {
        ...window,
        remaining,
        resetAtMs: normalizeResetAt(window.resetsAt),
      };
    })
    .filter((window) => window.remaining !== null);
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
  const nowMs = Date.now();
  const windows = listWindows(rateLimits);

  if (!windows.length) {
    return {
      liveWindowCount: 0,
      bottleneckRemaining: -1,
      averageRemaining: -1,
      bottleneckQuotaBudget: -1,
      averageQuotaBudget: -1,
      isDrained: false,
      drainedResetAt: null,
    };
  }

  const remaining = windows.map((window) => window.remaining);
  const quotaBudgets = windows.map((window) => window.remaining * getWindowRemainingFraction(window, nowMs));
  const drainedWindows = windows.filter((window) => window.remaining <= 0);
  const drainedResetCandidates = drainedWindows
    .map((window) => window.resetAtMs)
    .filter((value) => value !== null)
    .sort((left, right) => left - right);

  return {
    liveWindowCount: remaining.length,
    bottleneckRemaining: Math.min(...remaining),
    averageRemaining: remaining.reduce((sum, value) => sum + value, 0) / remaining.length,
    bottleneckQuotaBudget: Math.min(...quotaBudgets),
    averageQuotaBudget: quotaBudgets.reduce((sum, value) => sum + value, 0) / quotaBudgets.length,
    isDrained: drainedWindows.length > 0,
    drainedResetAt: drainedResetCandidates[0] ?? null,
  };
}

export function rankSavedAccount(savedAccount) {
  const planRank = getPlanRank(savedAccount?.summary?.planType);
  const hasLiveProbe = Boolean(savedAccount?.lastProbe?.success && savedAccount?.lastProbe?.rateLimits);
  const live = summarizeRateLimits(savedAccount?.lastProbe?.rateLimits);
  const availabilityRank = hasLiveProbe ? (live.isDrained ? 0 : 2) : 1;
  const drainPreferenceScore =
    availabilityRank === 2
      ? Math.round((100 - live.bottleneckQuotaBudget) * 1_000_000) +
        Math.round((100 - live.averageQuotaBudget) * 10_000)
      : 0;

  const sortKey =
    availabilityRank * 100_000_000_000 +
    planRank * 1_000_000_000 +
    (hasLiveProbe ? 1 : 0) * 100_000_000 +
    drainPreferenceScore;

  return {
    ...savedAccount,
    planRank,
    hasLiveProbe,
    availabilityRank,
    ...live,
    sortKey,
  };
}

export function sortSavedAccounts(savedAccounts) {
  return [...savedAccounts]
    .map(rankSavedAccount)
    .sort((left, right) => {
      if (right.availabilityRank !== left.availabilityRank) {
        return right.availabilityRank - left.availabilityRank;
      }

      if (right.planRank !== left.planRank) {
        return right.planRank - left.planRank;
      }

      if (left.availabilityRank === 2) {
        if (left.bottleneckQuotaBudget !== right.bottleneckQuotaBudget) {
          return left.bottleneckQuotaBudget - right.bottleneckQuotaBudget;
        }

        if (left.averageQuotaBudget !== right.averageQuotaBudget) {
          return left.averageQuotaBudget - right.averageQuotaBudget;
        }

        if (left.bottleneckRemaining !== right.bottleneckRemaining) {
          return left.bottleneckRemaining - right.bottleneckRemaining;
        }

        if (left.averageRemaining !== right.averageRemaining) {
          return left.averageRemaining - right.averageRemaining;
        }
      }

      if (left.availabilityRank === 0) {
        const leftReset = left.drainedResetAt ?? Number.POSITIVE_INFINITY;
        const rightReset = right.drainedResetAt ?? Number.POSITIVE_INFINITY;
        if (leftReset !== rightReset) {
          return leftReset - rightReset;
        }
      }

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
