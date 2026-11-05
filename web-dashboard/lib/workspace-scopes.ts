import {scopeOf} from './finops';
import type {Scan, Workspace} from './types';

/** Subscription / account / project ids authorized on the workspace (from /me). */
export function workspaceScopeIds(workspace: Workspace | null | undefined): string[] {
  if (!workspace) return [];
  const ids = new Set<string>();
  for (const id of workspace.subscription_ids || []) {
    const trimmed = id?.trim();
    if (trimmed) ids.add(trimmed);
  }
  const restrictions = workspace.scope_restrictions;
  if (restrictions) {
    for (const list of Object.values(restrictions)) {
      for (const id of list || []) {
        const trimmed = id?.trim();
        if (trimmed) ids.add(trimmed);
      }
    }
  }
  return [...ids].sort((a, b) => a.localeCompare(b));
}

/** Scope ids available in the toolbar filter (configured scopes plus scopes seen in the active scan). */
export function scopeFilterOptions(workspace: Workspace | null | undefined, scan: Scan | undefined): string[] {
  const configured = workspaceScopeIds(workspace);
  const observed = [...new Set((scan?.findings || []).map(scopeOf))];
  return [...new Set([...configured, ...observed])].sort((a, b) => a.localeCompare(b));
}

/** Empty `scope` means all scopes in downstream filters. */
export function scopeFilterIncludes(scope: string[], scopeId: string): boolean {
  if (!scope.length) return true;
  return scope.includes(scopeId);
}
