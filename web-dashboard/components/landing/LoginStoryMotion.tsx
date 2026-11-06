'use client';

import {type ReactNode} from 'react';
import {motion, useReducedMotion} from 'framer-motion';

/**
 * Staged entrance for the login marketing column — same animation stack as
 * [VengeanceUI](https://github.com/Ashutoshx7/VengeanceUI) (Framer Motion + Tailwind).
 * Respects prefers-reduced-motion.
 */
export function LoginStoryMotion({children}: {children: ReactNode}) {
  const reduceMotion = useReducedMotion();
  if (reduceMotion) return <>{children}</>;
  return (
    <motion.div
      className="login-story-motion"
      initial={{opacity: 0, y: 18}}
      animate={{opacity: 1, y: 0}}
      transition={{duration: 0.5, ease: [0.22, 1, 0.36, 1]}}
    >
      {children}
    </motion.div>
  );
}
