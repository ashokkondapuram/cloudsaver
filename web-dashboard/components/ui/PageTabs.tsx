'use client';

import type {KeyboardEvent} from 'react';
import type {LucideIcon} from 'lucide-react';

export type PageTab = {id: string; label: string; icon?: LucideIcon};

export function PageTabs({id, label, tabs, value, onChange, className = 'page-tabs'}: {id: string; label: string; tabs: PageTab[]; value: string; onChange: (value: string) => void; className?: string}) {
  function onKeyDown(event: KeyboardEvent) {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = tabs.findIndex(tab => tab.id === value);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
    onChange(tabs[next].id);
    document.getElementById(`${id}-${tabs[next].id}-tab`)?.focus();
  }
  return <div className={className} role="tablist" aria-label={label} onKeyDown={onKeyDown}>{tabs.map(tab => <button key={tab.id} role="tab" id={`${id}-${tab.id}-tab`} aria-controls={`${id}-${tab.id}`} aria-selected={value === tab.id} tabIndex={value === tab.id ? 0 : -1} onClick={() => onChange(tab.id)}>{tab.icon && <tab.icon size={16}/>}{tab.label}</button>)}</div>;
}
