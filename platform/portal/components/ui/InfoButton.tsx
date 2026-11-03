'use client';

import {CircleHelp} from 'lucide-react';
import {useId, useState, type ReactNode} from 'react';

export function InfoButton({label, children}: {label: string; children: ReactNode}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return <span className="info-button-wrap">
    <button type="button" className="info-button" aria-expanded={open} aria-controls={panelId}
      aria-label={`About ${label}`} onClick={() => setOpen(value => !value)}>
      <CircleHelp size={15} aria-hidden="true"/>
    </button>
    {open && <span id={panelId} role="note" className="info-popover">{children}</span>}
  </span>;
}

export function FieldLabel({label, hint, info}: {label: string; hint?: string; info?: ReactNode}) {
  return <div className="field-label">
    <span className="field-label-row">
      <span>{label}</span>
      {info && <InfoButton label={label}>{info}</InfoButton>}
    </span>
    {hint && <span className="field-hint">{hint}</span>}
  </div>;
}
