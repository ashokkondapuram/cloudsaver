/** Query hints so the API can load one resource from Postgres without the full scan payload. */
export type ResourceIdentity = {provider: string; resourceId: string};

export function resourceDetailQuery(identity?: ResourceIdentity | null): string {
  if (!identity?.provider || !identity.resourceId) return '';
  const q = new URLSearchParams({
    provider: identity.provider,
    resource_id: identity.resourceId,
  });
  return `?${q}`;
}

export function resourceInsightPageHref(scanId: string, resourceKey: string, identity: ResourceIdentity): string {
  const q = new URLSearchParams({
    scan_id: scanId,
    resource: resourceKey,
    provider: identity.provider,
    resource_id: identity.resourceId,
  });
  return `/resources/insight?${q}`;
}

export function resourceListHref(resourceKey: string, identity?: ResourceIdentity | null): string {
  const q = new URLSearchParams({resource: resourceKey});
  if (identity?.provider) q.set('provider', identity.provider);
  if (identity?.resourceId) q.set('resource_id', identity.resourceId);
  return `/resources?${q}`;
}
