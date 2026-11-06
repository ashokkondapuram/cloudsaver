'use client';

import {useLayoutEffect, useRef, type ReactNode} from 'react';
import {X} from '@phosphor-icons/react';

let openDialogCount = 0;
let savedBodyOverflow = '';

function lockBodyScroll() {
  if (openDialogCount === 0) savedBodyOverflow = document.body.style.overflow;
  openDialogCount += 1;
  if (openDialogCount === 1) document.body.style.overflow = 'hidden';
}

function unlockBodyScroll() {
  openDialogCount = Math.max(0, openDialogCount - 1);
  if (openDialogCount === 0) document.body.style.overflow = savedBodyOverflow;
}

export function Dialog({open, onClose, title, children, drawer = false, className = '', returnFocusKey, headerExtra}: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; drawer?: boolean; className?: string; returnFocusKey?:string|null; headerExtra?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose); close.current = onClose;
  const returnKey=useRef(returnFocusKey);returnKey.current=returnFocusKey;
  useLayoutEffect(() => {
    const element = ref.current;
    if (!open || !element) return;
    const previous = document.activeElement as HTMLElement | null;
    const focusKey = returnKey.current||previous?.getAttribute('data-focus-return');
    element.showModal();
    lockBodyScroll();
    const closeButton = element.querySelector<HTMLElement>('.dialog-heading .icon-button');
    closeButton?.focus({preventScroll: true});
    return () => {
      element.close();
      unlockBodyScroll();
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (document.querySelector('dialog[open]')) return;
        const current=focusKey?document.querySelector<HTMLElement>(`[data-focus-return="${CSS.escape(focusKey)}"]`):null;
        const target=current||(previous?.isConnected?previous:null);
        if (target) target.focus({preventScroll:true});
      }));
    };
  }, [open]);
  if (!open) return null;
  return <dialog ref={ref} aria-label={title} aria-modal="true" className={`dialog ${drawer ? 'drawer' : ''} ${className}`} onCancel={e => {e.preventDefault(); close.current();}} onClick={e => {if (e.target === ref.current) close.current();}}>
    <div className="dialog-surface">
      <div className="dialog-heading"><h2>{title}</h2><div className="dialog-heading-actions">{headerExtra}<button type="button" className="icon-button" aria-label={`Close ${title}`} onClick={onClose}><X size={18} weight="regular"/></button></div></div>
      {drawer ? <div className="dialog-drawer-body">{children}</div> : children}
    </div>
  </dialog>;
}
