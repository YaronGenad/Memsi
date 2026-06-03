import React from 'react';
import { HealthStatus } from '../useHealthCheck';

interface Props {
  status: HealthStatus;
}

const COLOR: Record<HealthStatus, string> = {
  checking: '#f59e0b',
  ok: '#22c55e',
  error: '#ef4444',
};

const LABEL: Record<HealthStatus, string> = {
  checking: 'בודק חיבור...',
  ok: 'מחובר',
  error: 'לא מחובר',
};

export const HealthIndicator: React.FC<Props> = ({ status }) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      fontSize: 13,
      color: COLOR[status],
      direction: 'rtl',
    }}
  >
    <span
      style={{
        width: 10,
        height: 10,
        borderRadius: '50%',
        background: COLOR[status],
        display: 'inline-block',
      }}
    />
    {LABEL[status]}
  </div>
);
