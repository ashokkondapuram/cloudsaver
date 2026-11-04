'use client';

import {useEffect, useMemo, useState} from 'react';
import type {Finding} from './types';
import {identityOf, type ResourceRow} from './resources';
import {lookupResourceSignals, type ResourceSignal} from './resource-signals';

/** AI/decision lookup for findings grids — one lightweight POST instead of the full resource catalog. */
export function useFindingResourceSignals(scanId: string | undefined, token: string, enabled: boolean, findings: Finding[]) {
  const identities = useMemo(() => {
    const seen = new Set<string>();
    const list: {provider: string; resource_id: string}[] = [];
    for (const finding of findings) {
      const provider = finding.cloud_provider || 'azure';
      const id = identityOf(provider, finding.resource_id);
      if (seen.has(id)) continue;
      seen.add(id);
      list.push({provider, resource_id: finding.resource_id});
    }
    return list;
  }, [findings]);

  const [signals, setSignals] = useState<Map<string, ResourceSignal>>(new Map());
  const [error, setError] = useState('');

  useEffect(() => {
    if (!enabled || !scanId || !token || !identities.length) {
      setSignals(new Map());
      setError('');
      return;
    }
    const request = new AbortController();
    setError('');
    lookupResourceSignals(scanId, token, identities, request.signal)
      .then(rows => {
        if (request.signal.aborted) return;
        setSignals(new Map(rows.map(row => [identityOf(row.provider, row.resource_id), row])));
      })
      .catch(cause => {
        if (!request.signal.aborted) setError((cause as Error).message);
      });
    return () => request.abort();
  }, [enabled, scanId, token, identities]);

  const resources = useMemo(() => {
    const map = new Map<string, Pick<ResourceRow, 'resource_key' | 'provider' | 'resource_id' | 'ai' | 'decision'>>();
    for (const row of signals.values()) {
      map.set(identityOf(row.provider, row.resource_id), row);
    }
    return map;
  }, [signals]);

  return {resources, error};
}
