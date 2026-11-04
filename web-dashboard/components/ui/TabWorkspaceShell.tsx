'use client';

import type {ReactNode} from 'react';
import {PageTabs, type PageTab} from './PageTabs';

export type WorkspaceTab = PageTab & {lead?: string};

type Props = {
  id: string;
  label: string;
  tabs: WorkspaceTab[];
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  className?: string;
  panelClassName?: string;
  tabIcons?: boolean;
};

/** Shared tab chrome for multi-section workspace pages and drawers. */
export function TabWorkspaceShell({id, label, tabs, value, onChange, children, className, panelClassName, tabIcons = true}: Props) {
  const active = tabs.find(tab => tab.id === value);
  return (
    <div className={`workspace-tab-shell${className ? ` ${className}` : ''}`}>
      <PageTabs id={id} label={label} tabs={tabs} value={value} onChange={onChange} className="page-tabs workspace-tab-list" icons={tabIcons}/>
      {active?.lead ? <p className="tab-lead">{active.lead}</p> : null}
      <div
        className={`tab-panel-stack${panelClassName ? ` ${panelClassName}` : ''}`}
        role="tabpanel"
        id={`${id}-${value}`}
        aria-labelledby={`${id}-${value}-tab`}
        tabIndex={0}
      >
        {children}
      </div>
    </div>
  );
}
