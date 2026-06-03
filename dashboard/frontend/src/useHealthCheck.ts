import { useState, useEffect } from 'react';
import { HEALTH_URL } from './config';

export type HealthStatus = 'checking' | 'ok' | 'error';

export function useHealthCheck(intervalMs = 10000): HealthStatus {
  const [status, setStatus] = useState<HealthStatus>('checking');

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const res = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(3000) });
        if (!cancelled) setStatus(res.ok ? 'ok' : 'error');
      } catch {
        if (!cancelled) setStatus('error');
      }
    };

    check();
    const id = setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return status;
}
