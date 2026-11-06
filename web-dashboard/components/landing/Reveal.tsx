'use client';

import {type ReactNode} from 'react';
import {motion, useReducedMotion} from 'framer-motion';

type RevealProps = {
  children: ReactNode;
  /** Optional wrapper class (layout hooks only; keep tokens in children). */
  className?: string;
  /** Stagger entrance when multiple siblings use Reveal (seconds). */
  delay?: number;
};

/**
 * Lightweight entrance motion — same toolset as
 * [VengeanceUI](https://github.com/Ashutoshx7/VengeanceUI) (Framer Motion + Tailwind).
 * Use on marketing-first surfaces; skip dense tables/grids. Honors prefers-reduced-motion.
 */
export function Reveal({children, className, delay = 0}: RevealProps) {
  const reduceMotion = useReducedMotion();
  if (reduceMotion) return <div className={className}>{children}</div>;
  return (
    <motion.div
      className={className}
      initial={{opacity: 0, y: 16}}
      animate={{opacity: 1, y: 0}}
      transition={{duration: 0.45, delay, ease: [0.22, 1, 0.36, 1]}}
    >
      {children}
    </motion.div>
  );
}
