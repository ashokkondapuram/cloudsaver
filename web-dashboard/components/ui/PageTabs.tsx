'use client';

import type {KeyboardEvent} from 'react';
import type {LucideIcon} from 'lucide-react';

export type PageTab = {id: string; label: string; icon?: LucideIcon};

export function PageTabs({id, label, tabs, value, onChange, className = 'page-tabs', icons = true}: {id: string; label: string; tabs: PageTab[]; value: string; onChange: (value: string) => void; className?: string; icons?: boolean}) {
  function onKeyDown(event: KeyboardEvent) {
    if (!tabs.length || !['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const active = document.activeElement as HTMLElement | null;
    const focusedIndex = tabs.findIndex(tab => active?.id === `${id}-${tab.id}-tab`);
    const index = focusedIndex >= 0 ? focusedIndex : tabs.findIndex(tab => tab.id === value);
    const base = index >= 0 ? index : 0;
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (base + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
    onChange(tabs[next].id);
    document.getElementById(`${id}-${tabs[next].id}-tab`)?.focus();
  }
  if (!tabs.length) return null;
  return <div className={className} role="tablist" aria-label={label} onKeyDown={onKeyDown}>{tabs.map(tab => <button type="button" key={tab.id} role="tab" id={`${id}-${tab.id}-tab`} aria-controls={`${id}-${tab.id}`} aria-selected={value === tab.id} tabIndex={value === tab.id ? 0 : -1} onClick={() => onChange(tab.id)}>{icons && tab.icon && <tab.icon size={16}/>}{tab.label}</button>)}</div>;
}
