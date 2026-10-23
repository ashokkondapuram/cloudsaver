'use client';

import {useCallback, useEffect, useRef, useState, type DependencyList} from 'react';
import {errorMessage} from './api';

export function useLoad<T>(load: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const generation = useRef(0);
  const run = useCallback(load, deps);
  const reload = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setError('');
    try {
      const result = await run();
      if (current === generation.current) setData(result);
    } catch (cause) {
      if (current === generation.current) setError(errorMessage(cause));
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [run]);
  useEffect(() => {void reload();}, [reload]);
  return {data, setData, error, loading, reload};
}
