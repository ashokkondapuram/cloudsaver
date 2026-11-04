import {api} from './api';
import type {AIState, Decision, ResourceRow} from './resources';
import {identityOf} from './resources';

export type ResourceSignal = Pick<ResourceRow, 'resource_key' | 'provider' | 'resource_id' | 'ai' | 'decision'>;

const CHUNK = 500;

function validSignal(value: unknown): value is ResourceSignal {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  const ai = row.ai;
  return typeof row.resource_key === 'string' && typeof row.provider === 'string' && typeof row.resource_id === 'string'
    && ai !== null && typeof ai === 'object' && typeof (ai as AIState).status === 'string';
}

/** Resolve AI/decision columns without walking the full resource catalog. */
export async function lookupResourceSignals(
  scanId: string,
  token: string,
  identities: {provider: string; resource_id: string}[],
  signal?: AbortSignal,
): Promise<ResourceSignal[]> {
  const unique: {provider: string; resource_id: string}[] = [];
  const seen = new Set<string>();
  for (const item of identities) {
    const id = identityOf(item.provider, item.resource_id);
    if (seen.has(id)) continue;
    seen.add(id);
    unique.push(item);
  }
  const out: ResourceSignal[] = [];
  for (let i = 0; i < unique.length; i += CHUNK) {
    const chunk = unique.slice(i, i + CHUNK);
    const raw = await api<{items: unknown[]}>(
      `/scans/${encodeURIComponent(scanId)}/resource-signals/lookup`,
      token,
      {method: 'POST', body: {identities: chunk}, signal},
    );
    if (!Array.isArray(raw.items) || !raw.items.every(validSignal)) {
      throw new Error('Resource signal lookup returned an invalid response.');
    }
    out.push(...raw.items);
  }
  return out;
}
