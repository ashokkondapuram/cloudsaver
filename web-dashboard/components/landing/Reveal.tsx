import {type ReactNode} from 'react';

type RevealProps = {
  children: ReactNode;
  className?: string;
  /** Retained for callers using the previous entrance wrapper. */
  delay?: number;
};

/** Keep content visible immediately, including before hydration and without motion. */
export function Reveal({children, className}: RevealProps) {
  return <div className={className}>{children}</div>;
}
