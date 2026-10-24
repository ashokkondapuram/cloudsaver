'use client';

import {ENTITLEMENT_KEYS, PROVIDERS, SCAN_FREQUENCIES, entitlementLabel, entitlementValueText, providerLabel, scanFrequencyLabel} from '../../lib/labels';
import type {EntitlementKey, Entitlements, Provider, ScanFrequency} from '../../lib/types';

type NumberKey = 'max_subscriptions' | 'max_resources_per_scan' | 'retention_days' | 'max_workspaces' | 'max_active_keys_per_workspace' | 'max_key_lifetime_days';
type BoolKey = 'can_export_terraform' | 'can_use_keyvault' | 'can_dispatch_automated_alerts' | 'can_use_ai_advisory';

export type EntitlementDraft = Record<NumberKey, string> & Record<BoolKey, boolean> & {
  allowed_scan_frequencies: ScanFrequency[]; allowed_providers: Provider[];
};

const NUMBER_RULES: Record<NumberKey, {min: number; max?: number}> = {
  max_subscriptions: {min: 0},
  max_resources_per_scan: {min: 1},
  retention_days: {min: 1, max: 3650},
  max_workspaces: {min: 1},
  max_active_keys_per_workspace: {min: 1, max: 20},
  max_key_lifetime_days: {min: 1, max: 365},
};
const BOOL_KEYS: BoolKey[] = ['can_export_terraform', 'can_use_keyvault', 'can_dispatch_automated_alerts', 'can_use_ai_advisory'];
const isNumberKey = (key: EntitlementKey): key is NumberKey => key in NUMBER_RULES;
const isBoolKey = (key: EntitlementKey): key is BoolKey => (BOOL_KEYS as EntitlementKey[]).includes(key);

export const DEFAULT_ENTITLEMENTS: Entitlements = {
  max_subscriptions: 1, max_resources_per_scan: 500, allowed_scan_frequencies: ['manual'], can_export_terraform: false,
  can_use_keyvault: false, can_dispatch_automated_alerts: false, can_use_ai_advisory: false, retention_days: 30, allowed_providers: [...PROVIDERS],
  max_workspaces: 1, max_active_keys_per_workspace: 5, max_key_lifetime_days: 365,
};

export function toDraft(values: Partial<Entitlements>, base: Entitlements = DEFAULT_ENTITLEMENTS): EntitlementDraft {
  const merged = {...base, ...values};
  return {
    max_subscriptions: String(merged.max_subscriptions), max_resources_per_scan: String(merged.max_resources_per_scan),
    retention_days: String(merged.retention_days), max_workspaces: String(merged.max_workspaces),
    max_active_keys_per_workspace: String(merged.max_active_keys_per_workspace), max_key_lifetime_days: String(merged.max_key_lifetime_days),
    can_export_terraform: merged.can_export_terraform, can_use_keyvault: merged.can_use_keyvault, can_dispatch_automated_alerts: merged.can_dispatch_automated_alerts,
    can_use_ai_advisory: merged.can_use_ai_advisory,
    allowed_scan_frequencies: [...merged.allowed_scan_frequencies], allowed_providers: [...merged.allowed_providers],
  };
}

export function fromDraft(draft: EntitlementDraft, keys: EntitlementKey[] = ENTITLEMENT_KEYS): Partial<Entitlements> {
  const result: Record<string, unknown> = {};
  for (const key of keys) {
    if (isNumberKey(key)) result[key] = Number(draft[key]);
    else if (key === 'allowed_scan_frequencies') result[key] = SCAN_FREQUENCIES.filter(item => draft.allowed_scan_frequencies.includes(item));
    else if (key === 'allowed_providers') result[key] = PROVIDERS.filter(item => draft.allowed_providers.includes(item));
    else result[key] = draft[key];
  }
  return result as Partial<Entitlements>;
}

export function draftErrors(draft: EntitlementDraft, keys: EntitlementKey[] = ENTITLEMENT_KEYS) {
  const errors: Partial<Record<EntitlementKey, string>> = {};
  for (const key of keys) {
    if (isNumberKey(key)) {
      const {min, max} = NUMBER_RULES[key];
      const text = draft[key].trim();
      const value = Number(text);
      if (!/^\d+$/.test(text) || value < min || (max !== undefined && value > max)) {
        errors[key] = max !== undefined ? `Enter a whole number from ${min} to ${max.toLocaleString('en-US')}.` : `Enter a whole number of ${min} or more.`;
      }
    }
  }
  if (keys.includes('allowed_scan_frequencies') && !draft.allowed_scan_frequencies.includes('manual')) errors.allowed_scan_frequencies = 'Scan frequencies must include Manual.';
  if (keys.includes('allowed_providers') && !draft.allowed_providers.length) errors.allowed_providers = 'Select at least one cloud provider.';
  return errors;
}

function toggle<T>(list: T[], item: T) {
  return list.includes(item) ? list.filter(value => value !== item) : [...list, item];
}

/**
 * Every entitlement as a field. With `overrides`, each one has an "Override the plan value" checkbox and
 * unchecked entitlements show the plan value instead of an editable control.
 */
export function EntitlementFields({draft, onChange, errors, showErrors, overrides, planValues, disabled}: {
  draft: EntitlementDraft; onChange: (draft: EntitlementDraft) => void; errors: Partial<Record<EntitlementKey, string>>; showErrors: boolean;
  overrides?: {selected: EntitlementKey[]; onToggle: (key: EntitlementKey) => void}; planValues?: Entitlements; disabled?: boolean;
}) {
  return <div className="form-grid">{ENTITLEMENT_KEYS.map(key => {
    const selected = !overrides || overrides.selected.includes(key);
    const locked = disabled || !selected;
    const error = showErrors && selected ? errors[key] : '';
    const wide = key === 'allowed_providers' || key === 'allowed_scan_frequencies';
    let control: React.ReactNode;
    if (overrides && !selected) {
      control = <span className="muted">Plan value: {entitlementValueText(key, planValues?.[key])}</span>;
    } else if (isNumberKey(key)) {
      const {min, max} = NUMBER_RULES[key];
      control = <input type="number" inputMode="numeric" min={min} max={max} step={1} value={draft[key]} disabled={locked} aria-label={entitlementLabel[key]} aria-invalid={!!error}
        onChange={event => onChange({...draft, [key]: event.target.value})}/>;
    } else if (isBoolKey(key)) {
      control = <label className="checkbox-row"><input type="checkbox" checked={draft[key]} disabled={locked} onChange={event => onChange({...draft, [key]: event.target.checked})}/>Included</label>;
    } else if (key === 'allowed_scan_frequencies') {
      control = <div className="choices">{SCAN_FREQUENCIES.map(item => <label key={item} className="checkbox-row">
        <input type="checkbox" checked={draft.allowed_scan_frequencies.includes(item)} disabled={locked} onChange={() => onChange({...draft, allowed_scan_frequencies: toggle(draft.allowed_scan_frequencies, item)})}/>{scanFrequencyLabel[item]}
      </label>)}</div>;
    } else {
      control = <div className="choices">{PROVIDERS.map(item => <label key={item} className="checkbox-row">
        <input type="checkbox" checked={draft.allowed_providers.includes(item)} disabled={locked} onChange={() => onChange({...draft, allowed_providers: toggle(draft.allowed_providers, item)})}/>{providerLabel[item]}
      </label>)}</div>;
    }
    return <fieldset key={key} className={`choice-group ${wide ? 'full' : ''}`}>
      <legend>{entitlementLabel[key]}</legend>
      {overrides && <label className="checkbox-row"><input type="checkbox" checked={selected} disabled={disabled} onChange={() => overrides.onToggle(key)}/>Override the plan value</label>}
      {control}
      {error && <span className="field-error">{error}</span>}
    </fieldset>;
  })}</div>;
}
