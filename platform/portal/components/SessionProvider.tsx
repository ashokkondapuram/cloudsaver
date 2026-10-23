'use client';

import {createContext, useCallback, useContext, useEffect, useState, type ReactNode} from 'react';
import {authRequest} from '../lib/api';
import {isOperator} from '../lib/labels';
import type {Session} from '../lib/types';

type SessionState = {
  session: Session | null;
  loading: boolean;
  canWrite: boolean;
  /** Operator and billing turned on for the platform. */
  canManageBilling: boolean;
  refresh: () => Promise<Session | null>;
  signOut: () => Promise<void>;
};

type SessionResponse = Partial<Session> & {signed_in: boolean};
const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({children}: {children: ReactNode}) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    try {
      const body = await authRequest<SessionResponse>('session');
      const next = body.signed_in ? body as Session : null;
      setSession(next);
      return next;
    } catch {
      setSession(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);
  const signOut = useCallback(async () => {
    try {await authRequest('logout', {method: 'POST'});} catch {}
    setSession(null);
    window.location.assign('/sign-in?signed_out=1');
  }, []);
  useEffect(() => {void refresh();}, [refresh]);
  return <SessionContext.Provider value={{session, loading, canWrite: isOperator(session), canManageBilling: isOperator(session) && !!session?.billing_enabled, refresh, signOut}}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used inside SessionProvider');
  return context;
}
