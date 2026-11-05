import type {Entitlements, Workspace} from './types';
import type {AtlasNotice} from './atlas-contracts';
import {billingBanner} from './plan';
import {dedupeNotices} from './notices';

const NO_PROVIDERS = "This workspace key doesn't include any cloud providers. Ask your administrator for a new key.";
const EXPIRY_WARNING_DAYS = 14;

/** Map workspace + billing state into AtlasNotice contracts for KeyNotices / toasts. */
export function workspaceAtlasNotices(workspace: Workspace, entitlements: Entitlements | null): AtlasNotice[] {
  const items: AtlasNotice[] = [];
  const billing = billingBanner(entitlements);
  if (billing) {
    items.push({
      id: `billing:${entitlements?.tenant_id ?? workspace.tenant_id}:${entitlements?.billing_state ?? 'unknown'}`,
      severity: 'warning',
      title: 'Billing attention',
      description: billing,
      persistent: true,
    });
  }
  const expires = workspace.key_expires_at ? new Date(workspace.key_expires_at) : null;
  const soon =
    expires && !Number.isNaN(expires.valueOf()) && expires.getTime() - Date.now() <= EXPIRY_WARNING_DAYS * 86400000;
  if (soon && workspace.key_expires_at) {
    items.push({
      id: `key-expiry:${workspace.key_id ?? workspace.tenant_id}`,
      severity: 'warning',
      title: 'Workspace key expiring',
      description: `This workspace key expires on ${workspace.key_expires_at.slice(0, 10)}. Ask your administrator for a new key.`,
    });
  }
  if (workspace.allowed_providers && !workspace.allowed_providers.length) {
    items.push({
      id: `no-providers:${workspace.tenant_id}`,
      severity: 'warning',
      title: 'No cloud providers',
      description: NO_PROVIDERS,
    });
  }
  if (workspace.scope_restrictions) {
    items.push({
      id: `scoped-key:${workspace.key_id ?? workspace.tenant_id}`,
      severity: 'info',
      title: 'Scoped workspace key',
      description: 'Some cloud scopes are hidden by your key restrictions.',
    });
  }
  return dedupeNotices(items);
}
