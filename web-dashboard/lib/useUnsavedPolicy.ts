'use client';

import {useEffect} from 'react';

/** Warn before leaving a policy draft; keep it in memory only. */
export function useUnsavedPolicy(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = '';};
    const navigate = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !(event.target instanceof Element)) return;
      const target = event.target.closest<HTMLAnchorElement | HTMLButtonElement>('a[href], button[role="tab"], button[data-discard-policy-draft]');
      if (!target || target.closest('dialog') || target.getAttribute('aria-selected') === 'true') return;
      if (target instanceof HTMLAnchorElement && (target.target === '_blank' || target.hasAttribute('download') || target.getAttribute('href')?.startsWith('#') || target.href === window.location.href)) return;
      if (!window.confirm('Discard your unsaved rule changes and leave this policy?')) {
        event.preventDefault(); event.stopPropagation();
      }
    };
    const tabKey = (event: KeyboardEvent) => {
      if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key) || !(event.target instanceof Element) || !event.target.closest('button[role="tab"]')) return;
      if (!window.confirm('Discard your unsaved rule changes and leave this policy?')) {event.preventDefault(); event.stopPropagation();}
    };
    window.addEventListener('beforeunload', beforeUnload);
    document.addEventListener('keydown', tabKey, true);
    document.addEventListener('click', navigate, true);
    return () => {window.removeEventListener('beforeunload', beforeUnload); document.removeEventListener('click', navigate, true); document.removeEventListener('keydown', tabKey, true);};
  }, [enabled]);
}
