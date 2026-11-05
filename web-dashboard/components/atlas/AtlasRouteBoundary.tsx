'use client';

import {usePathname} from 'next/navigation';
import {atlasRolloutForRoute} from '../../lib/atlas-page-rollout';

/** §12 route boundary — exposes current path and rollout metadata for Atlas e2e and audits. */
export function AtlasRouteBoundary({children}: {children: React.ReactNode}) {
  const pathname = usePathname() || '/';
  const rollout = atlasRolloutForRoute(pathname);
  const slug =
    rollout?.route === '/'
      ? 'overview'
      : rollout
        ? rollout.route.replace(/^\//, '').replace(/\//g, '-')
        : 'unknown';
  return (
    <div
      className="atlas-route-boundary"
      data-atlas-route={pathname}
      data-atlas-rollout={slug}
      data-atlas-status={rollout?.status ?? 'planned'}
    >
      {children}
    </div>
  );
}
