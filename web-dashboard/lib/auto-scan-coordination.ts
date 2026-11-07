export const AUTO_SCAN_CHANNEL = 'cloudsaver:auto-scan';
export const COOLDOWN_MS = 10 * 60 * 1000;

export type AutoScanRecord = {tenantId: string; attemptedAt: number; accepted?: boolean};

export function storageKey(tenantId: string) {
  return `cloudsaver:auto-scan:${tenantId}`;
}

export function readCooldown(tenantId: string): AutoScanRecord | null {
  try {
    const raw = sessionStorage.getItem(storageKey(tenantId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AutoScanRecord;
    if (parsed?.tenantId !== tenantId || typeof parsed.attemptedAt !== 'number') return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeCooldown(record: AutoScanRecord) {
  try {
    sessionStorage.setItem(storageKey(record.tenantId), JSON.stringify(record));
  } catch {
    /* ignore quota */
  }
}

export function cooldownActive(tenantId: string, now = Date.now()): boolean {
  const record = readCooldown(tenantId);
  if (!record) return false;
  return now - record.attemptedAt < COOLDOWN_MS;
}

export function postTabAttempt(tenantId: string, attemptedAt: number) {
  try {
    const channel = new BroadcastChannel(AUTO_SCAN_CHANNEL);
    channel.postMessage({tenantId, attemptedAt} satisfies AutoScanRecord);
    channel.close();
  } catch {
    /* BroadcastChannel unavailable */
  }
}
