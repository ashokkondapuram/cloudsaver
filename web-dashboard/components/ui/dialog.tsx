'use client';

import {useLayoutEffect, useRef, type ReactNode} from 'react';
import {X} from 'lucide-react';

export function Dialog({open, onClose, title, children, drawer = false, className = '', returnFocusKey}: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; drawer?: boolean; className?: string; returnFocusKey?:string|null;
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
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      element.close(); document.body.style.overflow = previousOverflow;
      // Restore after React has removed the modal and the browser has finished
      // its native dialog focus handling and virtual rows have settled after resize.
      // A second frame resolves the current row if overflow changes remount it.
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const current=focusKey?document.querySelector<HTMLElement>(`[data-focus-return="${CSS.escape(focusKey)}"]`):null;
        const target=current||(previous?.isConnected?previous:null);
        if (target && !document.querySelector('dialog[open]')) target.focus({preventScroll:true});
      }));
    };
  }, [open]);
  if (!open) return null;
  return <dialog ref={ref} aria-label={title} aria-modal="true" className={`dialog ${drawer ? 'drawer' : ''} ${className}`} onCancel={e => {e.preventDefault(); close.current();}} onClick={e => {if (e.target === ref.current) close.current();}}>
    <div className="dialog-surface">
      <div className="dialog-heading"><h2>{title}</h2><button type="button" className="icon-button" aria-label={`Close ${title}`} onClick={onClose}><X size={18}/></button></div>
      {children}
    </div>
  </dialog>;
}
