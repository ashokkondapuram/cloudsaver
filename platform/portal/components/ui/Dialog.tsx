'use client';

import {useLayoutEffect, useRef, type ReactNode} from 'react';
import {X} from 'lucide-react';

export function Dialog({open, onClose, title, children, wide = false, dismissible = true}: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean; dismissible?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const canDismiss = useRef(dismissible); canDismiss.current = dismissible;
  useLayoutEffect(() => {
    const element = ref.current;
    if (!open || !element) return;
    const previous = document.activeElement as HTMLElement | null;
    element.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      requestAnimationFrame(() => {if (previous?.isConnected && !document.querySelector('dialog[open]')) previous.focus({preventScroll: true});});
    };
  }, [open]);
  if (!open) return null;
  return <dialog ref={ref} aria-label={title} aria-modal="true" className={`dialog ${wide ? 'wide' : ''}`}
    onCancel={event => {event.preventDefault(); if (canDismiss.current) close.current();}}
    onClick={event => {if (event.target === ref.current && canDismiss.current) close.current();}}>
    <div className="dialog-surface">
      <div className="dialog-heading"><h2>{title}</h2>{dismissible && <button type="button" className="icon-button" aria-label={`Close ${title}`} onClick={onClose}><X size={18}/></button>}</div>
      {children}
    </div>
  </dialog>;
}
